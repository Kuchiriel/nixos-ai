"""Completion policy — DONE baseado em evidência, nunca em afirmação.

Regra P0: o Agent não pode declarar conclusão quando:
- o último resultado de tool é erro (trailing-error);
- arquivos que ele disse ter escrito não existem;
- .py escrito não compila (AST);
- nada executou com sucesso (zero ground truth).

Veredito: VERIFIED | UNVERIFIED | STUCK | FAILED + evidence/missing.
Sem NLP de intenção: só fatos estruturais do run (mensagens + árvore).
"""

from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


def _norm(s: str) -> str:
    """Minúsculas sem acentos p/ casar súplicas com/sem digitação correta.

    O modelo escreve "ajudá-lo" mas o padrão diz "ajudar" (fix-git real:
    handoff escapou pelo acento e herdou VERIFIED vazio).
    """
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn")


@dataclass
class CompletionVerdict:
    status: str  # VERIFIED | UNVERIFIED | STUCK | FAILED
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


_CREATION_VERBS = re.compile(
    r"(criad[oa]|criou|foi criado|escrit[oa]|escrevi|salv[oa]|salvei|"
    r"created|wrote|written|saved|adicionad[oa]|adicionei|"
    r"\bwrite\b|\bcreate\b|\bsave\b|\bgenerate\b)",
    re.IGNORECASE,
)
_PATH_LIKE = re.compile(r"[`\"']?([\w\-./]+\.(?:py|md|nix|txt|json|sh|toml))[,.`\"']?")

# Placeholder literal em VALOR de JSON (d3 20/09: alert.json válido com
# "rule_id" → VERIFIED vácuo). GAIA-2: soft check task-agnóstico no verifier
# contra reward hacking; AgentLTL: vacuous-pass; harbor-robot: gates com
# checks semânticos além dos de interface. Só full-value + <TOKEN>, nunca
# substring ("ALERTS" contém "TS" e é texto legítimo).
_PLACEHOLDER_VALUES = frozenset({
    "TS", "TBD", "TODO", "FIXME", "XXX", "UNKNOWN", "rule_id",
    "severity_level", "placeholder", "sample", "example", "dummy", "fake",
    "REPLACE_ME", "$PLACEHOLDER", "events []", "matches []", "[]", "{}",
    "...", "omitted",
})
_PLACEHOLDER_TOKEN = re.compile(r"<[A-Z][A-Z0-9_]*>")


def _find_placeholder_value(data):
    """Valor placeholder literal em estrutura JSON (vácuo válido)."""
    if isinstance(data, dict):
        for v in data.values():
            hit = _find_placeholder_value(v)
            if hit is not None:
                return hit
    elif isinstance(data, list):
        for v in data:
            hit = _find_placeholder_value(v)
            if hit is not None:
                return hit
    elif isinstance(data, str):
        if (data in _PLACEHOLDER_VALUES
                or _PLACEHOLDER_TOKEN.fullmatch(data)):
            return data
    return None
_CONTENT_VERBS = re.compile(
    r"(declara|declarad[oa]|cont[ée]m|valor|diz que|states?|"
    r"says?|contains?|shows?|reads?|is `)",
    re.IGNORECASE,
)

# Afirmação de MODIFICAÇÃO (vs artefato/conteúdo): "fiz merge",
# "corrigi", "recuperei" — exige ação mutante no run (Gaia2: grade
# write-actions). Sem mutação = conclusão falsa clássica (observado:
# checkout master + "merge feito", nada fundido).
_CHANGE_VERBS = re.compile(
    r"(fiz o? merge|merge (feito|conclu[ií]do|aplicado)|merg(e|ed|ing)|"
    r"mesclad[oa]s?|corrigid[oa]s?|\bfixed\b|recuperad[oa]s?|"
    r"restaurad[oa]s?|revertid[oa]s?|cherry-pick(ed)?|migrad[oa]s?)",
    re.IGNORECASE,
)

_GIT_MUTATING = re.compile(
    r"\bgit\s+(merge|commit|push|cherry-pick|rebase|revert|am|apply"
    r"|stash\s+(apply|pop|push)|reset|rm|mv|checkout\s+(-b|-B|--orphan)"
    r"|checkout\b[^\n;|&]*--[^\n;|&]*)",
    re.IGNORECASE,
)
_FILE_MUTATING = re.compile(
    r"(?<![\w\-])(cp|mv|rm|touch|tee|install|ln)\s+[\"']?[\w\-./]",
    re.IGNORECASE,
)

# Afirmação de NADA-A-FAZER ("no changes were made", "não encontrei"):
# para task que pedia modificação, declarar ociosidade sem nenhuma ação
# mutante e sem verificação é conclusão sem evidência (sanitize real:
# 4 book_search fora do alvo + "cannot find any" → VERIFIED vazio).
# Casado SEM acento (_norm).
_NOOP_CLAIM = re.compile(
    r"(no changes were made|no change (was|were) (made|needed|necessary)|"
    r"nenhuma altera|nenhuma mudanca|nenhuma mudança|nenhuma modifica|"
    r"nao ha nada|não há nada|cannot find any|nao encontrei|"
    r"não encontrei|already clean|ja esta limpo|já está limpo|"
    r"nothing to (do|fix|change))",
    re.IGNORECASE,
)

# Pedido de ajuda ao usuário (handoff, não conclusão): cobre súplicas
# sem ponto de interrogação ("forneça mais detalhes", "would you like").
# Casado SEM acento (_norm): "posso ajudá-lo" tem que pegar.
_HANDOFF = re.compile(
    r"(forneca mais detalhes|por favor,? "
    r"(informe|me diga|forneca|envie|diga|execute|rode)|would you like|"
    r"quer que eu|posso ajudar|como posso ajudar|let me know|me avise|"
    r"fico no aguardo|precisa de mais|execute o seguinte|rode .* no terminal|"
    r"run the following|try again|tente novamente|verifique o caminho|"
    r"verify the path|se voce puder me informar|provide the correct path|"
    r"please ensure|certifique-se|ensure that)",
    re.IGNORECASE,
)


def _claimed_change(messages: list[dict]) -> bool:
    """Texto final afirma ter MODIFICADO algo (merge/fix/recuperação)."""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            if _CHANGE_VERBS.search(m["content"]):
                return True
            break
    return False


# Afirmação de EDIÇÃO DE CONTEÚDO (vs operação git): "sanitize",
# "replace", "atualizei" — exige ESCRITA de conteúdo (write_file/
# str_replace com sucesso ou redirect), não basta git-op. Split
# necessário: sanitize real afirmou "replacing" tendo só git-ops
# irrelevantes (recovery branch!) e passou (falso VERIFIED).
_CONTENT_CHANGE_VERBS = re.compile(
    r"(sanitiz\w*|replac\w*|substitu\w*|remov\w*|remoção|remoçao|"
    r"limp(ei|ado|o|ou)\b|"
    r"\b(updated|modified|edited|editei|editado|atualiz\w*|modific\w*))",
    re.IGNORECASE,
)


def _claimed_content_change(messages: list[dict]) -> bool:
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            if _CONTENT_CHANGE_VERBS.search(m["content"]):
                return True
            break
    return False


def _claimed_noop(messages: list[dict]) -> bool:
    """Texto final declara NADA-A-FAZER (sem mudanças/sem achados)."""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            if _NOOP_CLAIM.search(_norm(m["content"])):
                return True
            break
    return False


# Verificação pós-sanitização OFFLINE (não precisa de grep): para task
# de limpeza de segredos, os arquivos que o modelo disse ter editado são
# lidos e varridos por shapes de valor. Pega nome-vs-valor (L4 real:
# trocou AWS_ACCESS_KEY_ID mas deixou AKIA... no valor) sem depender de
# o modelo rodar grep.
_SECRET_SHAPES = (
    r"AKIA[0-9A-Z]{16}",
    r"ghp_[A-Za-z0-9]{36}",
    r"hf_[A-Za-z0-9]{10,}",
    r"aws_secret.{0,10}[A-Za-z0-9/+=]{30,}",
)


def _residual_secret_in_file(fp: Path) -> list[tuple[str, str]]:
    """Valores de segredo restantes num arquivo: (padrão, valor) — só
    forma compacta do valor (máx 40 chars) p/ instruir substituição sem
    vazar segredo integral nos logs."""
    try:
        txt = fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for pat in _SECRET_SHAPES:
        for m in re.finditer(pat, txt, re.IGNORECASE):
            out.append((pat, m.group(0)[:40]))
            if len(out) >= 3:
                return out
    return out


def _residual_secret_paths(messages: list[dict], root: Path) -> list[str]:
    out = []
    for _n, _a in _successful_calls(messages):
        if _n not in ("write_file", "str_replace"):
            continue
        _p = str(_a.get("path", ""))
        if not _p:
            continue
        fp = (root / _p) if not Path(_p).is_absolute() else Path(_p)
        if not fp.is_file():
            continue
        try:
            txt = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in _SECRET_SHAPES:
            if re.search(pat, txt, re.IGNORECASE):
                out.append(f"{_p} ainda contém padrão de segredo")
                break
    return out


def _successful_calls(messages: list[dict]) -> list[tuple[str, dict]]:
    """(tool_name, args) das chamadas com resultado sem ERROR.

    Intenção não basta: leitura que falhou não ancora nada (sanitize
    real: 3 reads falhos + 'cannot find any' — grounded vazio).
    book_search/book_resume NÃO contam (índice de audiobooks, não repo).
    """
    out = []
    for i, m in enumerate(messages):
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            name = fn.get("name", "")
            if name in ("book_search", "book_resume"):
                continue
            try:
                import json
                a = fn.get("arguments", {})
                a = json.loads(a) if isinstance(a, str) else a
            except Exception:
                a = {}
            nxt = messages[i + 1] if i + 1 < len(messages) else {}
            if nxt.get("role") == "tool":
                c = (nxt.get("content") or "").strip()
                if c and not c.upper().startswith("ERROR"):
                    out.append((name, a if isinstance(a, dict) else {}))
    return out


def _mutating_shell(cmd: str) -> bool:
    """Comando shell que muta estado (git conteudista ou escrita/leitura)."""
    return bool(_GIT_MUTATING.search(cmd) or _FILE_MUTATING.search(cmd))


def _shell_cmds(messages: list[dict]) -> list[str]:
    """Comandos executados via execute_shell/jarvis_execute."""
    out = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            if fn.get("name") not in ("execute_shell", "jarvis_execute"):
                continue
            try:
                import json
                a = fn.get("arguments", {})
                a = json.loads(a) if isinstance(a, str) else a
                cmd = (a.get("cmd") or a.get("command") or "") if isinstance(
                    a, dict) else ""
            except Exception:
                continue
            if cmd:
                out.append(cmd)
    return out


_DENIAL_WORDS = (r"não existe|não há|não encontrado|not found|no such file|"
                 r"ausente|missing")
_PATH_EXT = r"[\w\-./]+\.(?:py|md|nix|txt|json|sh|toml)"
_DENIAL = re.compile(
    rf"(?:{_DENIAL_WORDS})\b.{{0,40}}?[`\"']?({_PATH_EXT})"
    rf"|`?[`\"']?({_PATH_EXT})[`\"']?.{{0,40}}?(?:{_DENIAL_WORDS})",
    re.IGNORECASE,
)


def _denied_but_observed(messages: list[dict]) -> list[str]:
    """Nega na resposta o que a observação continha (ex.: N2 real).

    'servico.nix não existe' quando o ls listou servico.nix = falsa
    conclusão semântica detectável estruturalmente (containment).
    """
    observed = "\n".join(
        m.get("content", "") for m in messages if m.get("role") == "tool")
    if not observed:
        return []
    out = []
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            for mm in _DENIAL.finditer(m["content"]):
                p = mm.group(1) or mm.group(2)
                if p in observed and p not in out:
                    out.append(p)
            break
    return out


def _claimed_artifacts(messages: list[dict]) -> list[str]:
    """Arquivos que o texto final afirma ter criado/escrito."""
    out = []
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            text = m["content"]
            if _CREATION_VERBS.search(text):
                for mm in _PATH_LIKE.finditer(text):
                    p = mm.group(1)
                    if p not in out:
                        out.append(p)
            break
    return out


def _claimed_contents(messages: list[dict]) -> list[str]:
    """Paths cujo CONTEÚDO o texto final afirma conhecer (elo H1 16/09:
    respondeu 'é `default`' sem nunca ler o arquivo — chave no lugar
    do valor). Simétrico a _claimed_artifacts."""
    out = []
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            text = m["content"]
            if _CONTENT_VERBS.search(text):
                for mm in _PATH_LIKE.finditer(text):
                    p = mm.group(1)
                    if p not in out:
                        out.append(p)
            break
    return out


def _read_paths(messages: list[dict]) -> list[str]:
    """Paths passados a read_file (intenção de leitura)."""
    out = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            if fn.get("name") == "read_file":
                try:
                    import json
                    a = fn.get("arguments", {})
                    a = json.loads(a) if isinstance(a, str) else a
                    if isinstance(a, dict) and a.get("path"):
                        out.append(str(a["path"]))
                except Exception:
                    pass
    return out


def _written_paths(messages: list[dict]) -> list[str]:
    """Paths passados a write_file/str_replace (intenção de escrita)."""
    out = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            if fn.get("name") in ("write_file", "str_replace"):
                try:
                    import json
                    a = fn.get("arguments", {})
                    a = json.loads(a) if isinstance(a, str) else a
                    if isinstance(a, dict) and a.get("path"):
                        out.append(str(a["path"]))
                except Exception:
                    pass
    return out


_REDIR = re.compile(
    r"(?:^|[;&|])\s*[^>|]*?(>>?)\s*[\"']?([\w\-./]+\.[\w]+)[\"']?")
_TEE = re.compile(
    r"\btee\s+(?:-a\s+)?[\"']?([\w\-./]+\.[\w]+)[\"']?")


def _shell_write_paths(messages: list[dict]) -> list[str]:
    """Alvos de redirecionamento em execute_shell (Gaia2 write-action).

    Escrita via shell (`>`, `>>`, `tee`) É ação de escrita no mundo —
    sem isso, artefato criado por shell e afirmado no final vira falso
    UNVERIFIED ("sem escrita") mesmo existindo no disco. Conservador:
    só tokens com extensão (exclui `>&2`, `/dev/null`, `2>`); `*` excluído.
    """
    out = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            if fn.get("name") not in ("execute_shell", "jarvis_execute"):
                continue
            try:
                import json
                a = fn.get("arguments", {})
                a = json.loads(a) if isinstance(a, str) else a
                cmd = (a.get("cmd") or a.get("command") or "") if isinstance(
                    a, dict) else ""
            except Exception:
                continue
            if not cmd:
                continue
            for mm in _REDIR.finditer(cmd):
                p = mm.group(2)
                if "*" not in p and p not in out:
                    out.append(p)
            for mm in _TEE.finditer(cmd):
                p = mm.group(1)
                if "*" not in p and p not in out:
                    out.append(p)
    return out


def _is_error_output(content: str) -> bool:
    """Output de tool é erro? Prefixo ERROR ou traceback Python.

    Traceback não começa com ERROR mas é falha inequívoca (csv real:
    `import pandas` com ModuleNotFoundError contou como SUCESSO e o
    modelo seguiu achando que tinha lido o CSV).
    """
    c = (content or "").strip()
    return c.upper().startswith("ERROR") or "Traceback (most recent call last)" in c


def _last_tool_error(messages: list[dict]) -> str | None:
    """Conteúdo do último resultado de tool, se for erro."""
    for m in reversed(messages):
        if m.get("role") == "tool":
            c = (m.get("content") or "").strip()
            if _is_error_output(c):
                return c[:200]
            return None
    return None


def _any_tool_success(messages: list[dict]) -> bool:
    for m in messages:
        if m.get("role") == "tool":
            c = (m.get("content") or "").strip()
            if c and not _is_error_output(c):
                return True
    return False


def _pending_recovery_notes(messages: list[dict]) -> list[str]:
    """Notas de recuperação do próprio harness ainda abertas?

    STATE(unexecuted_script:X) sem execução posterior de X, ou
    STATE(unread_refs:Y) sem leitura posterior bem-sucedida de Y.
    VERIFIED com nota pendente = over-claim (L8 real 2x: VERIFIED sem
    alert.json porque scripts nunca rodaram). Mecânico, sem saber a task.
    """
    import json as _jl
    pend: list[str] = []

    def _args(tc: dict) -> dict:
        try:
            fn = tc.get("function", tc) if isinstance(tc, dict) else {}
            if not isinstance(fn, dict):
                return {}
            a = fn.get("arguments", {})
            a = _jl.loads(a) if isinstance(a, str) else a
            return a if isinstance(a, dict) else {}
        except Exception:
            return {}

    def _exec_after(idx: int, base: str) -> bool:
        for m in messages[idx + 1:]:
            for tc in m.get("tool_calls") or []:
                a = _args(tc)
                if (tc.get("function", {}) or {}).get("name") == "execute_shell":
                    cmd = str(a.get("cmd", ""))
                    if (f"./{base}" in cmd or re.search(
                            r"\b(python3?|bash|sh)\s+\S*" + re.escape(base), cmd)):
                        return True
        return False

    def _read_ok_after(idx: int, ref: str) -> bool:
        for i in range(idx + 1, len(messages)):
            m = messages[i]
            for tc in m.get("tool_calls") or []:
                a = _args(tc)
                if (tc.get("function", {}) or {}).get("name") != "read_file":
                    continue
                if str(a.get("path", "")) not in (ref, ref.rsplit("/", 1)[-1]):
                    continue
                nxt = messages[i + 1] if i + 1 < len(messages) else {}
                if nxt.get("role") == "tool" and not _is_error_output(
                        str(nxt.get("content", ""))):
                    return True
        return False

    for i, m in enumerate(messages):
        c = str(m.get("content", ""))
        mm = re.search(r"STATE\(unexecuted_script:([^)]+)\)", c)
        if mm:
            for p in mm.group(1).split(","):
                p = p.strip()
                if p and not _exec_after(i, p.rsplit("/", 1)[-1]):
                    pend.append(f"script escrito nunca executado: {p}")
        mm = re.search(r"STATE\(unread_refs:([^)]+)\)", c)
        if mm:
            for r in mm.group(1).split(","):
                r = r.strip()
                if r and not _read_ok_after(i, r):
                    pend.append(f"referência nunca lida: {r}")
    return pend


def missing_deliverables(messages: list[dict], root,
                           all_writes=None) -> list[str]:
    """Deliverables `*.sh` citados no prompt original que não existem.

    Fatorado p/ reuso: check_completion (veredito) e o loop do Agent
    (progress-check periódico mid-run). Task-grounded, sem ensinar solução.
    """
    if all_writes is None:
        all_writes = _written_paths(messages)
    out: list[str] = []
    _task_text = ""
    for _m in messages:
        if _m.get("role") == "user" and "STATE(" not in str(
                _m.get("content", "")):
            _task_text = str(_m.get("content", ""))
            break
    if _task_text:
        for _need in sorted(set(re.findall(
                r"[A-Za-z0-9_.\-]+\.sh\b", _task_text))):
            _fp = root / _need
            if not _fp.exists() and not any(
                    str(_w).endswith(_need) for _w in all_writes):
                out.append(
                    f"prompt requires {_need} which doesn't exist yet "
                    f"— create it if it's a deliverable, otherwise clarify")
        # Generalização (Ciclo 5/L9-werr: task pedia write report.json +
        # summary.txt, nada escrito, VERIFIED vácuo — o mecanismo acima só
        # cobria *.sh). Artefatos citados no prompt COM verbo de criação
        # (write/create/save...) valem o mesmo: SUCCESS refere-se ao
        # estado atual (PHASE 16), não a afirmações.
        if _CREATION_VERBS.search(_task_text):
            for _mm in _PATH_LIKE.finditer(_task_text):
                _need = _mm.group(1)
                if _need.endswith(".sh"):
                    continue  # já coberto acima
                _fp = root / _need
                if _fp.exists() or any(
                        str(_w).endswith(_need) for _w in all_writes):
                    continue
                out.append(
                    f"prompt requires {_need} which doesn't exist yet "
                    f"— create it if it's a deliverable, otherwise clarify")
    return out


def check_completion(messages: list[dict],
                     project_root: str | None = None) -> CompletionVerdict:
    """Veredito estrutural de conclusão."""
    ev: list[str] = []
    miss: list[str] = []
    if project_root is None:
        # Mesma base do _safe_path (resolve_base): CWD destacado resolve
        # relativo no CWD — sem isso, arquivo criado no cwd ganhava
        # 'não existe' (falso-negativo L1 real).
        try:
            from jarvis.core.devtools import resolve_base
            root = resolve_base()
        except Exception:
            root = Path(".")
    else:
        root = Path(project_root)
    ok = True

    if not _any_tool_success(messages):
        return CompletionVerdict("UNVERIFIED", [],
                                 ["nenhuma tool com sucesso (zero ground truth)"])

    trailing = _last_tool_error(messages)
    if trailing is not None:
        ok = False
        miss.append(f"último resultado é erro: {trailing[:120]}")

    # Recuperação pendente apontada pelo próprio harness (P5/RBW):
    # nota aberta = trabalho sabidamente incompleto — nunca VERIFIED.
    for _pend in _pending_recovery_notes(messages):
        ok = False
        miss.append(_pend)

    _all_writes = _written_paths(messages)
    for p in _shell_write_paths(messages):
        if p not in _all_writes:
            _all_writes.append(p)
    for p in _all_writes:
        fp = (root / p) if not Path(p).is_absolute() else Path(p)
        if not fp.exists():
            ok = False
            miss.append(f"arquivo escrito não existe: {p}")
            continue
        ev.append(f"arquivo existe: {p}")
        if fp.suffix == ".py":
            try:
                ast.parse(fp.read_text(encoding="utf-8"))
                ev.append(f"{p} compila (AST)")
            except (SyntaxError, OSError) as e:
                ok = False
                miss.append(f"{p} não compila: {e}")
        # Binário escrito como texto via write_file = falso PARQUET/DB
        # (observado: data.parquet com conteúdo "name,age,city" via write_file
        # contou como VERIFIED — arquivo existe mas não é parquet).
        if fp.suffix == ".parquet":
            try:
                head = fp.read_bytes()[:4]
                if head != b"PAR1" and fp.stat().st_size < 500:
                    # Escrita textual sem execução de pandas = dummy
                    _has_exec = any(
                        n in ("execute_shell", "jarvis_execute")
                        for n, _ in _successful_calls(messages))
                    if not _has_exec:
                        ok = False
                        miss.append(
                            f"{p} é texto (não parquet binário) — use execute_shell `python3 -c \"import pandas as pd; pd.read_csv(...).to_parquet(...)\"`")
                    elif head != b"PAR1":
                        ok = False
                        miss.append(f"{p} não começa com PAR1 (parquet inválido)")
                elif head == b"PAR1":
                    ev.append(f"{p} é parquet válido (header PAR1)")
            except OSError:
                pass
        if fp.suffix == ".sh" and fp.is_file():
            try:
                import stat as _st
                if not bool(fp.stat().st_mode & _st.S_IXUSR):
                    # Script afirmado como fixado mas sem permissão de execução
                    # (fix-permissions real: write sem chmod → VERIFIED vazio)
                    for _n, _a in _successful_calls(messages):
                        if _n in ("write_file", "str_replace") and str(_a.get("path","")).endswith(".sh"):
                            ok = False
                            miss.append(f"{p} sem permissão de execução — rode `chmod +x {p}` (call separada; `&&` é bloqueado)")
                            break
            except OSError:
                pass
            # Execution-based verification (Code-as-Harness 2605.18747):
            # .sh escrito exige EVIDÊNCIA de execução — chmod sozinho não
            # prova nada (L8 real: scripts nunca rodaram → VERIFIED vazio).
            # Generaliza STATE(unexecuted_script) p/ todo .sh escrito no run,
            # sem depender de nota emitida pelo harness. Mecânico, sem saber
            # a task: tentativa de execução conta (falha de run cai na regra
            # trailing-error separadamente).
            import json as _jl2
            _base = p.rsplit("/", 1)[-1]

            def _args_of(_tc: dict) -> dict:
                try:
                    _fn = _tc.get("function", {}) or {}
                    _a = _fn.get("arguments", {})
                    _a = _jl2.loads(_a) if isinstance(_a, str) else _a
                    return _a if isinstance(_a, dict) else {}
                except Exception:
                    return {}

            _widx: int | None = None
            for _i, _m in enumerate(messages):
                for _tc in _m.get("tool_calls") or []:
                    _fn = ((_tc.get("function", {}) or {}).get("name"))
                    if _fn not in ("write_file", "str_replace"):
                        continue
                    if str(_args_of(_tc).get("path", "")).endswith(_base):
                        _widx = _i
                        break
                if _widx is not None:
                    break
            _ran = False
            if _widx is not None:
                for _m in messages[_widx + 1:]:
                    for _tc in _m.get("tool_calls") or []:
                        _fn = ((_tc.get("function", {}) or {}).get("name"))
                        if _fn not in ("execute_shell", "jarvis_execute"):
                            continue
                        _cmd = str(_args_of(_tc).get("cmd", ""))
                        if (f"./{_base}" in _cmd or re.search(
                                r"\b(bash|sh)\s+\S*" + re.escape(_base),
                                _cmd)):
                            _ran = True
                            break
                    if _ran:
                        break
            if _widx is not None and not _ran:
                ok = False
                miss.append(
                    f"{p} escrito mas nunca executado — rode `chmod +x {p}` "
                    f"e execute (`./{_base}` ou `bash {_base}`) em DUAS "
                    f"calls separadas (`&&` é bloqueado) antes de declarar "
                    f"conclusão")
        # JSON de recuperação sem execução real (sqlite real: write dummy sem sqlite3/python)
        if fp.name == "recover.json":
            _has_sql = any(
                "sqlite" in str(a).lower() or "trunc.db" in str(a).lower()
                for _, a in _successful_calls(messages) if _ in ("execute_shell","jarvis_execute"))
            if not _has_sql:
                # Dummy escrito sem tocar o DB = falso VERIFIED
                ok = False
                miss.append(
                    f"{p} escrito sem executar sqlite — use `execute_shell` com `sqlite3` ou `python3 -c` lendo trunc.db")

    # Afirmação de criação sem chamada de escrita: "criei X" sem nenhum
    # write_file/str_replace no run = falsa conclusão clássica (observado:
    # C2 afirmou dobra.py sem chamar write). Só vale quando o run usou
    # tools (runs puramente textuais não têm como provar nada estrutural).
    _used_tools = any(m.get("tool_calls") for m in messages)
    if _used_tools:
        # Cobertura de deliverables citados no prompt (L8 real 5x: modelo
        # queima todos os turns na parte 1 e a parte 2 nunca começa).
        # Task-grounded sem ensinar solução: extrai *.sh do prompt original
        # e cobra existência. Fraseado condicional (não manda criar o que
        # pode ser só referência): criar se deliverable, esclarecer se não.
        for _dm in missing_deliverables(messages, root, _all_writes):
            ok = False
            miss.append(_dm)
        # Artefato .json inválido no CWD (L8v23: alert/report gerados pelo
        # script, inválidos, e NADA no loop acusou — validator só enxerga
        # tool results, nunca arquivos). Mecânico e genérico: parseia e o
        # erro exato vira miss (sem ensinar conteúdo). Só top-level (outputs
        # vivem no CWD; inputs em subdirs intactos). >1MB pula (raro).
        import json as _jl3
        try:
            _root_jsons = sorted(root.glob("*.json"))
        except Exception:
            _root_jsons = []
        for _jf in _root_jsons:
            try:
                if _jf.stat().st_size > 1_000_000:
                    continue
                _txt = _jf.read_text(encoding="utf-8")
                _data = _jl3.loads(_txt)
                # Placeholder em VALOR de JSON válido (d3 20/09: "rule_id"
                # passou no parse e deu VERIFIED vácuo; s3/w2 confirmam a
                # classe). Scan task-agnóstico: full-value + <TOKEN>.
                _ph = _find_placeholder_value(_data)
                if _ph is not None:
                    ok = False
                    miss.append(
                        f"{_jf.name} contains placeholder value {_ph!r} — "
                        f"compute the real value from inputs and rewrite "
                        f"(passes syntax, fails semantics)")
                    break
            except Exception as _e:
                ok = False
                _diag = str(_e)[:120]
                # Defeito mais comum do modelo fraco: chaves sem aspas
                # (`{timestamp:` estilo YAML). Nomeia o defeito exato em
                # vez de só mandar regenerar (L8v24: 3 ciclos sem achar).
                import re as _re3
                _m = _re3.search(r"\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*:",
                                 _txt[:2000])
                if _m:
                    _diag += (" — keys need double quotes: "
                              '{"' + _m.group(1) + '": ...}')
                miss.append(
                    f"{_jf.name} is not valid JSON: {_diag} — "
                    f"regenerate it (python3 + json.dumps, never hand-write)")
                break
        _created = _claimed_artifacts(messages)
        _made = set(_written_paths(messages)) | set(
            _shell_write_paths(messages))
        # tools determinísticas que PRODUZEM arquivos contam como escrita.
        for _n, _a in _successful_calls(messages):
            if _n == "build_json_dataset" and _a.get("out"):
                _made.add(str(_a["out"]))
        for c in _created:
            # Sufixo vale (igual a regra de conteúdo): 'nota.txt'
            # afirmada após write de 'trabalho/nota.txt' (L1 real).
            if not any(c == g or c.endswith(g) or g.endswith(c)
                       for g in _made):
                ok = False
                miss.append(f"afirma artefato sem escrita: {c}")
        _grounded = set(_read_paths(messages)) | set(_made)
        for c in _claimed_contents(messages):
            if not any(c.endswith(g) or g.endswith(c) for g in _grounded):
                ok = False
                miss.append(f"afirma conteúdo sem leitura: {c} "
                            f"(leia o arquivo antes de declarar o valor)")
        for d in _denied_but_observed(messages):
            ok = False
            miss.append(f"nega evidência observada: {d}")
        # Afirmação de modificação sem nenhuma ação mutante no run
        # (write_file/str_replace, redirecionamento, git conteudista,
        # cp/mv/rm): checkout+leitura não fundem nada (fix-git real).
        if _claimed_change(messages):
            _mutated = bool(_made) or any(
                _mutating_shell(c) for c in _shell_cmds(messages))
            if not _mutated:
                ok = False
                miss.append("afirma modificação sem ação de escrita/mutação "
                            "(nenhum write, redirect ou git conteudista no run)")
        # Edição de CONTEÚDO afirmada ("sanitize", "replacing") exige
        # ESCRITA de conteúdo com sucesso — git-op irrelevante não
        # satisfaz (sanitize real: recovery branch + "successfully
        # sanitized", segredos intactos).
        if _claimed_content_change(messages):
            _content_writes = [
                str(a.get("path")) for n, a in _successful_calls(messages)
                if n in ("write_file", "str_replace") and a.get("path")]
            # sanitize_secrets / build_json_dataset (determinísticos) geram
            # conteúdo por si — não dependem de write/str_replace do modelo
            # (L4/L5 real).
            for _n, _a in _successful_calls(messages):
                if _n == "sanitize_secrets" and _a.get("root"):
                    _content_writes.append(str(_a.get("root")))
                if _n == "build_json_dataset" and _a.get("out"):
                    _content_writes.append(str(_a.get("out")))
            for _p in _shell_write_paths(messages):
                _fp = (root / _p) if not Path(_p).is_absolute() else Path(_p)
                if _fp.exists() and _p not in _content_writes:
                    _content_writes.append(_p)
            if not _content_writes:
                ok = False
                miss.append("afirma edição de conteúdo sem escrita "
                            "bem-sucedida (nenhum write_file/str_replace "
                            "com sucesso no run)")
        # Número "calculado" sem cálculo executado (L2 real: 15.0
        # escrito de cabeça em vez de 11.4286). Se o artefato escrito é SÓ
        # um número, ele não veio do prompt nem das observações e nenhum
        # execute_shell com sucesso rodou: aritmética mental não é prova.
        for _n, _a in _successful_calls(messages):
            if _n != "write_file":
                continue
            try:
                _v = float(str(_a.get("content", "")).strip())
            except (TypeError, ValueError):
                continue
            _seen = " ".join(
                str(m.get("content", "")) for m in messages
                if m.get("role") in ("user", "tool"))
            _prior = []
            for _m in re.findall(r"-?\d+(?:\.\d+)?", _seen):
                try:
                    _prior.append(float(_m))
                except ValueError:
                    pass
            # Sem bypass por shell: shell executado NÃO prova que O
            # NÚMERO saiu dele — só vale se o valor aparece nas
            # observações (L2 real: python rodou, 15.0 escrito antes).
            if not any(abs(_v - _x) < 1e-9 for _x in _prior):
                ok = False
                miss.append("valor numérico escrito sem cálculo executado "
                            "(rode `python3 -c` e regrave com o resultado)")
                break
        # Sanitização incompleta: task de limpeza de segredos com valor
        # residual nos arquivos editados = NÃO concluído (L4 real).
        if _claimed_content_change(messages):
            _resid = _residual_secret_paths(messages, root)
            if _resid:
                ok = False
                miss.append("; ".join(_resid) + " — edite os VALORES, "
                            "não os nomes, até nenhum padrão restar")
        # Nada-a-fazer declarado sem mutação nem verificação (ver acima).
        if _claimed_noop(messages):
            _mutated = bool(_made) or any(
                _mutating_shell(c) for c in _shell_cmds(messages))
            _ok_calls = _successful_calls(messages)
            _grounded_ok = any(
                n in ("read_file", "list_directory", "semantic_search",
                      "code_search", "execute_shell") for n, _ in _ok_calls)
            if not _mutated and not _grounded_ok:
                ok = False
                miss.append("declara nada a fazer sem evidência "
                            "(nenhuma ação mutante nem busca/leitura com "
                            "sucesso no repo)")

    if ok:
        ev.append("sem erro final; artefatos verificados")
        # Handoff não é conclusão: final em forma de pergunta ao usuário
        # ("quer que eu busque?") com tools irrelevantes não prova nada
        # (observado: 4 book_search numa task git → VERIFIED vazio).
        # Nem toda súplica termina com "?": pedido de mais detalhes/
        # oferta de ajuda ("forneça mais detalhes", "would you like")
        # também é handoff (observado: dragão/Hobbit alucinado → VERIFIED).
        _last_assistant = next(
            (m.get("content", "") for m in reversed(messages)
             if m.get("role") == "assistant" and m.get("content")), "")
        _substantive = any(
            e for e in ev if not e.startswith("sem erro final"))
        _tail = _last_assistant.rstrip()
        if not _substantive and (
                _tail.endswith("?") or _HANDOFF.search(_norm(_tail))):
            return CompletionVerdict(
                "UNVERIFIED", ev,
                miss + ["termina pedindo ao usuário (handoff, "
                        "não conclusão verificada)"])
        return CompletionVerdict("VERIFIED", ev, [])
    return CompletionVerdict("UNVERIFIED", ev, miss)


def classify_error(output: str) -> str:
    """Classificação grosseira p/ política de retry (harness, não modelo)."""
    o = (output or "").lower()
    if "timed out" in o or "timeout" in o or "temporar" in o:
        return "transient"
    if "denied" in o or "not allowed" in o or "approval" in o:
        return "policy"
    if "not found" in o or "no such file" in o:
        return "missing"
    if "invalid" in o or "malformed" in o or "unknown tool" in o:
        return "bad-request"
    if o.startswith("error"):
        return "failed"
    return "ok"
