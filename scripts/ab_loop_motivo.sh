#!/usr/bin/env bash
# ab_loop_motivo.sh - Classifica o motivo de cada resultado do laboratorio A/B.
#
# Uso: source este arquivo e chame classifica_motivo <rc> <patch_bytes> <run.log> <lane>.
# Exemplo: motivo=$(classifica_motivo "$rc" "$pbytes" "$run_log" "$lane")
#
# Regras: patch vazio com Review Failed e review; se o stash rejeitado passar
# no checker fixo em uma copia temporaria, e review_wrong; rc diferente de
# zero, timeout ou HTTP 429 sao infra; o restante e checker.

AB_REPO="${AB_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

ab_log_tem_review_failed() {
    local log_file="$1"
    [ -f "$log_file" ] || return 1
    grep -Eqi 'Review [Ff]ailed$|Review failed:' "$log_file"
}

ab_log_tem_erro_infra() {
    local log_file="$1" rc="$2"
    [ "$rc" != "0" ] && return 0
    [ -f "$log_file" ] || return 1
    grep -Eqi '(^|[^0-9])429([^0-9]|$)|(^|[^[:alpha:]])timeout([^[:alpha:]]|$)|timed[[:space:]]+out|rate.?limit|too many requests' "$log_file"
}

ab_stash_ref_rejeitado() {
    local lane="$1" ref subject
    while IFS=$'\t' read -r ref subject; do
        case "$subject" in
            *nightwatch-autosave-uncommitted*)
                printf '%s\n' "$ref"
                return 0
                ;;
        esac
    done < <(git -C "$lane" stash list --format='%gd%x09%gs' 2>/dev/null)
    return 1
}

# Override este funcao em testes para usar um checker sintetico.
ab_run_checker() {
    local audit_dir="$1"
    AB_AUDIT_DIR="$audit_dir" timeout 180 nix develop "$AB_REPO" -c bash -c \
        'cd "$AB_AUDIT_DIR" && python3 -m pytest -q checker.py'
}

ab_checker_passa_stash() {
    local lane="$1" stash_ref audit_dir rc checker_output
    stash_ref=$(ab_stash_ref_rejeitado "$lane") || return 1
    audit_dir=$(mktemp -d /tmp/ab-review-audit.XXXXXX) || return 1

    if ! cp -a "$lane/." "$audit_dir/"; then
        rm -rf "$audit_dir"
        return 1
    fi

    if ! git -C "$audit_dir" stash apply "$stash_ref" >/dev/null 2>&1; then
        git -C "$audit_dir" reset --hard HEAD >/dev/null 2>&1 || true
        git -C "$audit_dir" clean -fd >/dev/null 2>&1 || true
        if ! git -C "$lane" stash show -p --binary "$stash_ref" 2>/dev/null \
             | git -C "$audit_dir" apply --whitespace=nowarn - >/dev/null 2>&1; then
            rm -rf "$audit_dir"
            return 1
        fi
    fi

    # Um stash vazio nao e evidencia de patch rejeitado.
    if [ -z "$(git -C "$audit_dir" status --porcelain 2>/dev/null)" ]; then
        rm -rf "$audit_dir"
        return 1
    fi

    checker_output=$(ab_run_checker "$audit_dir" 2>&1)
    rc=$?
    rm -rf "$audit_dir"
    [ -z "$checker_output" ] || printf '%s\n' "$checker_output" >&2
    return "$rc"
}

# G1 (17/11): a deteccao de review_wrong dependia do stash VIVO da lane, e o
# proprio lab destroi a lane a cada ciclo (rm -rf + mkdir): o mesmo evento
# virava review num instante e review_wrong no seguinte. Aqui a captura e
# feita NO MOMENTO da rejeicao: o diff rejeitado vai para arquivo, o checker
# roda numa COPIA em /tmp e o veredito fica gravado ao lado. A classificacao
# passa a ler esse artefato, e so cai no caminho antigo se ele nao existir.

ab_review_meta_path() {
    local log_dir="$1" prefix="$2"
    printf '%s/review-%s.meta\n' "$log_dir" "$prefix"
}

# Grava diff + veredito do checker do patch rejeitado. Nao toca na lane.
# Devolve 0 se capturou (accepted|rejected), 1 se nao deu para capturar.
ab_captura_rejeicao() {
    local lane="$1" log_dir="$2" prefix="$3"
    local meta stash_ref audit_dir rc checker_output diff_file sha
    meta="$(ab_review_meta_path "$log_dir" "$prefix")"
    [ -f "$meta" ] && return 0
    stash_ref=$(ab_stash_ref_rejeitado "$lane") || return 1
    diff_file="$log_dir/patch-review-$prefix.diff"
    git -C "$lane" stash show -p --binary "$stash_ref" > "$diff_file" 2>/dev/null || return 1
    [ -s "$diff_file" ] || return 1
    sha=$(sha256sum "$diff_file" 2>/dev/null | cut -d' ' -f1)
    audit_dir=$(mktemp -d /tmp/ab-review-capture.XXXXXX) || return 1
    if ! cp -a "$lane/." "$audit_dir/"; then
        rm -rf "$audit_dir"
        return 1
    fi
    if ! git -C "$audit_dir" stash apply "$stash_ref" >/dev/null 2>&1; then
        git -C "$audit_dir" reset --hard HEAD >/dev/null 2>&1 || true
        git -C "$audit_dir" clean -fd >/dev/null 2>&1 || true
        if ! git -C "$lane" stash show -p --binary "$stash_ref" 2>/dev/null              | git -C "$audit_dir" apply --whitespace=nowarn - >/dev/null 2>&1; then
            rm -rf "$audit_dir"
            return 1
        fi
    fi
    if [ -z "$(git -C "$audit_dir" status --porcelain 2>/dev/null)" ]; then
        rm -rf "$audit_dir"
        return 1
    fi
    checker_output=$(ab_run_checker "$audit_dir" 2>&1)
    rc=$?
    rm -rf "$audit_dir"
    local verdict="unknown"
    if [ "$rc" = "0" ]; then
        verdict="accepted"
    elif [ -n "$checker_output" ]; then
        verdict="rejected"
    fi
    {
        printf 'diff_sha256=%s\n' "$sha"
        printf 'diff_file=%s\n' "$diff_file"
        printf 'checker=%s\n' "$verdict"
        printf 'checker_output=%s\n' "$(printf '%s' "$checker_output" | tr -d '"' | cut -c1-160)"
        printf 'ts=%s\n' "$(date +%s)"
    } > "$meta"
    return 0
}

# Le o artefato de captura. Devolve accepted|rejected|unknown.
ab_review_meta_verdict() {
    local meta="$1" v=""
    [ -f "$meta" ] || { printf 'unknown\n'; return 1; }
    v=$(grep -E '^checker=' "$meta" 2>/dev/null | head -1 | cut -d= -f2-)
    [ -n "$v" ] || v="unknown"
    printf '%s\n' "$v"
    [ "$v" != "unknown" ]
}

classifica_motivo() {
    local rc="$1" pbytes="$2" run_log="$3" lane="$4" meta="${5:-}"

    if [ "$pbytes" = "0" ] && ab_log_tem_review_failed "$run_log"; then
        # G1: artefato capturado no momento da rejeicao (diff + veredito do
        # checker). Se existe, ele manda: nao depende do stash vivo.
        if [ -n "$meta" ] && [ -f "$meta" ]; then
            case "$(ab_review_meta_verdict "$meta")" in
                accepted) printf 'review_wrong\n'; return 0 ;;
                rejected) printf 'review\n'; return 0 ;;
            esac
        fi
        if ab_checker_passa_stash "$lane"; then
            printf 'review_wrong\n'
        else
            printf 'review\n'
        fi
        return 0
    fi

    if ab_log_tem_erro_infra "$run_log" "$rc"; then
        printf 'infra\n'
        return 0
    fi

    printf 'checker\n'
}
