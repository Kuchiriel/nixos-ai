#!/usr/bin/env bash
# ab_loop.test.sh - Testa a classificacao de motivo do laboratorio A/B.
#
# Uso: bash scripts/ab_loop.test.sh
# Exemplo: bash scripts/ab_loop.test.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/ab_loop_motivo.sh
. "$REPO/scripts/ab_loop_motivo.sh"

TMP="$(mktemp -d /tmp/ab-motivo-test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

assert_motivo() {
    local expected="$1" actual="$2" label="$3"
    if [ "$actual" != "$expected" ]; then
        printf 'FAIL %s: esperado %s, veio %s\n' "$label" "$expected" "$actual" >&2
        exit 1
    fi
    printf 'ok %s: %s\n' "$label" "$actual"
}

printf 'clean\n' > "$TMP/clean.log"
printf 'upstream rejected request with HTTP 429\n' > "$TMP/429.log"
printf 'provider timeout while waiting\n' > "$TMP/timeout.log"
printf 'Review Failed\n' > "$TMP/review.log"

assert_motivo checker "$(classifica_motivo 0 512 "$TMP/clean.log" "$TMP/missing-lane")" 'resultado normal'
assert_motivo infra "$(classifica_motivo 1 0 "$TMP/clean.log" "$TMP/missing-lane")" 'rc diferente de zero'
assert_motivo infra "$(classifica_motivo 0 0 "$TMP/429.log" "$TMP/missing-lane")" 'HTTP 429'
assert_motivo infra "$(classifica_motivo 0 0 "$TMP/timeout.log" "$TMP/missing-lane")" 'timeout'
assert_motivo review "$(classifica_motivo 0 0 "$TMP/review.log" "$TMP/missing-lane")" 'review sem stash'

lane="$TMP/lane"
mkdir -p "$lane"
git -C "$lane" init -q -b main
git -C "$lane" config user.email lab@local
git -C "$lane" config user.name lab
printf 'original\n' > "$lane/change.txt"
git -C "$lane" add change.txt
git -C "$lane" commit -q -m baseline
printf 'rejected patch\n' > "$lane/change.txt"
git -C "$lane" stash push -q -m nightwatch-autosave-uncommitted

ab_run_checker() {
    [ -f "$1/change.txt" ] && grep -Fq 'rejected patch' "$1/change.txt"
}
assert_motivo review_wrong "$(classifica_motivo 0 0 "$TMP/review.log" "$lane")" 'review rejeitado errado'

ab_run_checker() { return 1; }
assert_motivo review "$(classifica_motivo 0 0 "$TMP/review.log" "$lane")" 'review rejeitado certo'

# G1 (17/11): com o artefato capturado no momento da rejeicao, o motivo
# nao depende mais do stash vivo (que o lab destroi no ciclo seguinte).
# Mesmo sem stash na lane, o meta decide.
meta_dir="$TMP/meta"
mkdir -p "$meta_dir"
meta="$meta_dir/review-api-L3-120000.meta"

printf 'diff_sha256=deadbeef\n' > "$meta"
printf 'diff_file=%s/patch-review-api-L3-120000.diff\n' "$meta_dir" >> "$meta"
printf 'checker=accepted\n' >> "$meta"
printf 'checker_output=5 passed\n' >> "$meta"
printf 'ts=0\n' >> "$meta"

assert_motivo review_wrong "$(classifica_motivo 0 0 "$TMP/review.log" "$TMP/missing-lane" "$meta")" \
    'G1: meta accepted decide sem stash vivo'

printf 'checker=rejected\n' > "$meta"
assert_motivo review "$(classifica_motivo 0 0 "$TMP/review.log" "$TMP/missing-lane" "$meta")" \
    'G1: meta rejected decide sem stash vivo'

printf 'checker=unknown\n' > "$meta"
assert_motivo review "$(classifica_motivo 0 0 "$TMP/review.log" "$TMP/missing-lane" "$meta")" \
    'G1: meta desconhecido cai no caminho antigo'

# G1: a captura grava diff + veredito e nao toca na lane
cap_dir="$TMP/cap"
mkdir -p "$cap_dir"
cap_lane="$TMP/cap-lane"
mkdir -p "$cap_lane"
git -C "$cap_lane" init -q -b main
git -C "$cap_lane" config user.email lab@local
git -C "$cap_lane" config user.name lab
printf 'original\n' > "$cap_lane/change.txt"
git -C "$cap_lane" add change.txt
git -C "$cap_lane" commit -q -m baseline
printf 'rejected patch\n' > "$cap_lane/change.txt"
git -C "$cap_lane" stash push -q -m nightwatch-autosave-uncommitted

ab_run_checker() {
    [ -f "$1/change.txt" ] && grep -Fq 'rejected patch' "$1/change.txt"
}
if ab_captura_rejeicao "$cap_lane" "$cap_dir" "api-L3-120000"; then
    meta_c="$cap_dir/review-api-L3-120000.meta"
    [ -s "$cap_dir/patch-review-api-L3-120000.diff" ] || { echo 'FAIL G1: diff nao gravado' >&2; exit 1; }
    grep -q '^checker=accepted' "$meta_c" || { echo 'FAIL G1: veredito do checker ausente' >&2; exit 1; }
    assert_motivo review_wrong "$(classifica_motivo 0 0 "$TMP/review.log" "$TMP/missing-lane" "$meta_c")" \
        'G1: captura decide o motivo sem o stash vivo'
    printf 'ok G1: captura grava diff e veredito\n'
else
    echo 'FAIL G1: captura nao rodou' >&2
    exit 1
fi

printf 'todos os testes passaram\n'
