"""Post-tool-call validation layer.

Verifies tool execution results BEFORE they reach the model, preventing
the model from acting on incorrect assumptions about tool outcomes.

Principle: MODEL = UNTRUSTED COMPONENT, HARNESS = CONTROL LAYER.

The model may:
- claim success when a command actually failed
- interpret partial output as complete
- hallucinate file contents after write_file
- miss error patterns in shell output

This module catches these cases and injects corrective information.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.core.logging import get_logger

log = get_logger("validator")


@dataclass
class ValidationResult:
    """Result of validating a tool call output."""
    valid: bool
    enhanced_output: str  # original or corrected output
    warnings: list[str]   # issues found
    severity: str         # "ok" | "warning" | "error"


def _locate_candidates(path: str, limit: int = 5) -> list[str]:
    """Candidatos p/ file-not-found: rglob do basename a partir do CWD.

    O harness SABE onde o arquivo está (0.05s) — antes o modelo recebia
    só "not found" e desistia pedindo o path ao usuário (observado 4/4
    runs UX). Best-effort: nunca levanta, nunca trava o loop.

    Retorna "abs (rel)": ABSOLUTO primeiro — reads resolvem relativos
    contra a RAIZ DO PROJETO, não o cwd; quando os dois divergem (task
    fora de repo), o relativo sozinho MENTE e o modelo repete o mesmo
    erro (heterogeneous real: `ls` mostrava os CSVs e o modelo relia o
    relativo). Primazia pro absoluto; relativo mantido p/ compat.
    """
    name = Path(path).name.strip()
    if not name:
        return []
    try:
        out = []
        for p in Path.cwd().rglob(name):
            if len(out) >= limit:
                break
            try:
                rel = str(p.relative_to(Path.cwd()))
            except ValueError:
                rel = str(p)
            out.append(f"{p} (rel: {rel})" if rel != str(p) else rel)
        return out
    except Exception:
        return []


def _git_root() -> Path | None:
    """Repo git mais próximo acima do CWD (best-effort, nunca levanta).

    Suporte ao sensor git-forense: só pathlib, sem subprocess — seguro
    em sandbox e em qualquer CWD.
    """
    try:
        d = Path.cwd()
        for _ in range(12):
            if (d / ".git").exists():
                return d
            if d.parent == d:
                break
            d = d.parent
    except Exception:
        pass
    return None


# Padrões de segredo (shape, não valor): verificação pós-sanitização.
# NUNCA ecoar valores — só tipo + contagem (logs não vazam segredo).
_SECRET_PATTERNS = [
    ('aws-key', r'AKIA[0-9A-Z]{16}'),
    ('github-token', r'ghp_[A-Za-z0-9]{36}'),
    ('hf-token', r'hf_[A-Za-z0-9]{10,}'),
    ('aws-secret', r'aws_secret.{0,10}[A-Za-z0-9/+=]{30,}'),
]


def _remaining_secrets(text: str, limit: int = 3) -> list[str]:
    found = []
    for kind, pat in _SECRET_PATTERNS:
        try:
            n = len(re.findall(pat, text or ''))
        except re.error:
            continue
        if n:
            found.append(f'{kind}x{n}')
        if len(found) >= limit:
            break
    return found


def _secret_sweep_hint(args: dict, full_path: 'Path | None' = None) -> 'str | None':
    """Verificação pós-sanitização: edição com cheiro de placeholder.

    Se old é UPPER_SNAKE (nome de chave) ou new é <placeholder>, lê o
    arquivo (limitado, best-effort) e relata TIPOS de segredo restantes
    (nunca valores). Retorna hint ou None.
    """
    try:
        _old = str(args.get('old', args.get('content', '')))
        _new = str(args.get('new', args.get('content', '')))
    except Exception:
        return None
    import re as _re2
    smells = (bool(_re2.fullmatch(r'[A-Z][A-Z0-9_]*_[A-Z0-9_]+', _old))
              or ('<' in _new and '>' in _new))
    if not smells:
        return None
    path = str(args.get('path', ''))
    if not path:
        return None
    try:
        fp = Path(path) if os.path.isabs(path) else Path.cwd() / path
        if not fp.is_file() or fp.stat().st_size > 200_000:
            return None
        left = _remaining_secrets(fp.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return None
    if left:
        return ('sanitização INCOMPLETA: ainda há ' + ', '.join(left)
                + ' neste arquivo (tipos, não valores). Edite os VALORES, '
                'não os nomes — confirme com grep depois.')
    return ('sanitização: nenhum padrão de segredo restante neste arquivo. '
            'Bom sinal — confira os demais hits.')


class ToolValidator:
    """Validates tool call results before passing to the model."""
    # Patterns that indicate shell command failure
    SHELL_ERROR_PATTERNS = [
        r"(?i)^error[:\s]",
        r"(?i)^fatal[:\s]",
        r"(?i)^traceback \(most recent",
        r"(?i)^segmentation fault",
        r"(?i)^permission denied",
        r"(?i)^no such file or directory",
        r"(?i)^command not found",
        r"(?i)^nix.*error",
        r"(?i)^build failed",
        r"(?i)^FAILED",
    ]

    # Patterns that indicate test failure
    TEST_FAILURE_PATTERNS = [
        r"(\d+) failed",
        r"FAILED",
        r"ERRORS",
        r"FAILED\b.*\d+",
    ]

    def validate(self, func_name: str, args: dict[str, Any],
                 output: str, exit_code: int | None = None) -> ValidationResult:
        """Validate a tool result. Returns enhanced output with warnings."""

        if func_name == "execute_shell":
            return self._validate_shell(args, output, exit_code)
        elif func_name == "write_file":
            return self._validate_write(args, output)
        elif func_name == "str_replace":
            return self._validate_str_replace(args, output)
        elif func_name == "read_file":
            return self._validate_read(args, output)
        elif func_name == "run_tests":
            return self._validate_tests(output)
        else:
            return ValidationResult(valid=True, enhanced_output=output,
                                    warnings=[], severity="ok")

    def _validate_shell(self, args: dict, output: str,
                        exit_code: int | None) -> ValidationResult:
        """Validate shell command output."""
        warnings = []
        enhanced = output

        # Check for error patterns
        for pattern in self.SHELL_ERROR_PATTERNS:
            if re.search(pattern, output):
                warnings.append(f"Shell output contains error pattern: {pattern}")
                break

        # Check exit code
        if exit_code is not None and exit_code != 0:
            warnings.append(f"Command exited with code {exit_code}")

        # jq recebeu TEXTO onde esperava arquivos/JSON (L8 real: `grep ... |
        # jq -r '.matches[]'` — grep solta linhas de log e jq tenta abrir
        # cada palavra como arquivo). Conhecimento de tool (precedente L2
        # awk): texto se parseia com grep/awk; JSON se constrói com
        # jq -n/--arg ou python3 json.dumps. Só dispara na assinatura.
        if re.search(r"jq:\s*error:\s*could not open file", output,
                     re.IGNORECASE):
            warnings.append(
                "jq got TEXT where it expected files: don't pipe grep "
                "output into jq (log lines are not JSON files). Parse text "
                "with grep/awk into shell vars, then build JSON with "
                "`jq -n --arg ...` or python3 json.dumps")

        # Check for empty output on commands that should produce output
        cmd = args.get("cmd", "")
        if not output.strip() and any(cmd.startswith(p) for p in
                                       ("cat", "head", "tail", "grep", "rg")):
            warnings.append("Command produced empty output — file may not exist or may be empty")

        # Saída longa e ruidosa: grep/find varrendo demais (sanitize real:
        # find+grep listou 20+ arquivos incl. .git e o modelo repetiu a
        # mesma busca 3x sem estreitar). Só em saída grande — sem ruído
        # no caminho feliz curto.
        _lines = output.count("\n") + (1 if output.strip() else 0)
        if _lines > 40 and re.search(
                r"(grep|find|rg|ls(\s+-R|\s+.*\*))", cmd):
            warnings.append(
                f"saída longa ({_lines} linhas): restrinja o escopo antes "
                "de repetir — exclua .git (`--exclude-dir=.git`), fixe o "
                "diretório/tipo, ou use semantic_search; repetir a mesma "
                "busca não filtra nada"
            )

        # Árvore limpa não prova nada perdido: mudanças podem estar em
        # commit dangling/stash/outra branch (fix-git real: `git status`
        # limpo e o modelo concluiu "nada a fazer"). 1 linha, só no caso
        # limpo — recon antes de declarar.
        _clean = ("nothing to commit" in output.lower()
                  and "working tree clean" in output.lower())
        if _clean and re.search(r"\bgit\s+status\b", cmd):
            warnings.append(
                "git status limpo ≠ nada perdido: confira o HISTÓRICO antes "
                "de concluir — `git reflog -n 20`; "
                "`git log --all --oneline -n 20`; `git stash list`; `git branch -a`."
            )

        # Grounding de reflog/fsck: o modelo LEU o dangling e declarou
        # "failed with ambiguous argument" (fix-git real: f0fcc1d "Move to
        # Stanford" estava no output). O harness extrai os candidatos —
        # parse determinístico que o modelo pequeno não faz sozinho.
        if (re.search(r"\bgit\s+(reflog|fsck)\b", cmd)
                and not getattr(self, "secret_task", False)):
            _found = []
            for _line in output.splitlines():
                _m = re.match(r"\s*([0-9a-f]{7,40})\s+(.*\S)\s*$", _line)
                if _m and len(_found) < 5:
                    _found.append(f"{_m.group(1)[:12]} '{_m.group(2)[:80]}'")
            if _found:
                # UMA próxima ação (não menu): modelo pequeno diante de
                # opções lê todas e executa nenhuma (fix-git real: viu o
                # candidato e foi rodar log --all). Prioriza linhas de
                # COMMIT ("commit: msg") sobre movimentações (checkout/
                # clone): o dangling procurado é um commit, não um move.
                _commits = [f for f in _found if "commit:" in f]
                _first = (_commits[0] if _commits else _found[0]).split(
                    " ", 1)[0]
                warnings.append(
                    "reflog/fsck: commit detectado: " + "; ".join(_found)
                    + f". NEXT: `git show {_first} --stat` (confirma); "
                    f"depois `git checkout -b recovery {_first}` + "
                    "`git merge recovery`."
                )

        # Check for NixOS-specific errors
        if "infinite recursion" in output.lower():
            warnings.append("Infinite recursion detected — likely a Nix evaluation error")
        if "attribute" in output.lower() and "missing" in output.lower():
            warnings.append("Missing attribute — check Nix expression syntax")

        # Biblioteca ausente neste interpretador (csv real: ModuleNotFoundError
        # contou como leitura ok). NixOS-first: NUNCA pip install global —
        # ache o interpretador certo (`ls ~/kvenv/bin/python*`, `which -a
        # python3`, `nix develop --command`) em vez de instalar.
        if "modulenotfounderror" in output.lower().replace(" ", ""):
            warnings.append(
                "ModuleNotFoundError: este python não tem a biblioteca — NÃO "
                "rode pip install global. Procure o interpretador certo "
                "(`ls ~/kvenv/bin/python* 2>/dev/null; which -a python3`) e "
                "rode com ele (`<python> -c 'import ...'` para confirmar)."
            )

        # Chaining negado pela política (sanitize real: find+grep com `;`
        # negado 3x seguidas). Segurança não negocia (`;|&&||` injetam
        # comandos), mas o modelo precisa do caminho permitido: UM comando
        # simples por chamada, um de cada vez.
        if "chaining operators not allowed" in output.lower():
            _sug = ("Divida: UMA tool call por comando simples "
                    "(ex.: `grep -r KEY dir/`, depois leia os arquivos).")
            # find+exec é invenção de chaining; o substituto direto é grep.
            if re.search(r"\bfind\b.*-exec\b", cmd):
                _sug = ("use `grep -rlE 'AKIA|ghp_|hf_' .` (procura os "
                        "arquivos com VALORES de segredo) — `find -exec` "
                        "é bloqueado; o grep sozinho faz a mesma coisa.")
            warnings.append(
                "chaining (`;`, `&&`, `||`, `|`) é BLOQUEADO por segurança — "
                "não insista na mesma forma. " + _sug
            )

        # Merge no-op: "Already up to date" quando a task pedia fundir
        # MUDANÇAS (fix-git real: `git merge master` EM CIMA da master —
        # direção invertida). Direção se verifica, não se presume.
        if (re.search(r"\bgit\s+merge\b", cmd)
                and "already up to date" in output.lower()):
            warnings.append(
                "git merge foi NO-OP (Already up to date): direção "
                "provavelmente invertida. Confira `git branch "
                "--show-current` e se o commit alvo está FORA dela "
                "(`git branch --contains <hash>` vazio = não fundido). "
                "Recuperar dangling = `git checkout -b <nova> <hash>` "
                "E DEPOIS `git merge <nova>` a partir do destino."
            )

        # Pós-inspeção sem ação (fix-git real: `git show` do dangling OK e
        # o modelo EXPLICOU o checkout+merge em vez de executar). NEXT
        # singular: inspecionou → age agora, não narra.
        if (re.search(r"\bgit\s+show\b", cmd)
                and re.search(r"(diff --git|commit [0-9a-f]{7,40}|"
                              r"\d+ files? changed)", output)):
            warnings.append(
                "git show confirmou o conteúdo: EXECUTE agora, não explique "
                "— `git checkout -b recovery <hash>` e em seguida "
                "`git merge recovery` (uma tool call por turno)."
            )

        # Quoting aninhado em python -c (L2 real: aspas dentro de aspas
        # 3x SyntaxError). Padrão robusto: grave .py via write_file e rode
        # `python3 arquivo.py` — shell de citação simples não aninha.
        if ("syntaxerror" in output.lower()
                and re.search(r"\bpython3?\s+-c\b", cmd)):
            warnings.append(
                "python -c com quoting aninhado falhou: NÃO reinsista na "
                "mesma forma. Grave o script com write_file (ex.: "
                "calc.py) e rode `python3 calc.py`."
            )

        # Erro em .py próprio: EDITE o arquivo, não volte ao -c (L2 real:
        # calc.py com header-bug abandonado por 3x -c falho). O arquivo
        # persiste — itere nele com str_replace até rodar limpo.
        if ("traceback (most recent call last)" in output.lower()
                and re.search(r"\bpython3?\s+([\w\-./]+\.py)\b", cmd)):
            import re as _re3
            _m = _re3.search(r"\bpython3?\s+([\w\-./]+\.py)\b", cmd)
            _py = _m.group(1) if _m else "script.py"
            warnings.append(
                f"traceback em {_py} (arquivo, não one-liner): EDITE-O com "
                f"str_replace (oldString exato do trecho quebrou) e rode de "
                f"novo — NÃO volte ao `python3 -c`."
            )

        # Caça a segredos pelo NOME acha docs; VALORES acham segredos
        # (L4 real: grep 'AWS_ACCESS_KEY_ID' afogou em README/docs). Se o
        # padrão grepado é UPPER_SNAKE (nome de chave), grepe TAMBÉM os
        # shapes de valor: `AKIA[0-9A-Z]{16}`, `ghp_`, `hf_` (rg aceita).
        if (re.search(r"\b(grep|rg)\b", cmd)
                and re.search(r"[A-Z][A-Z0-9_]*_[A-Z0-9_]+", cmd)):
            warnings.append(
                "grep por NOME DE CHAVE acha docs; segredos têm VALORES: "
                "grepe também `AKIA[0-9A-Z]{16}`, `ghp_`, `hf_` — priorize "
                "arquivos COM VALOR, ignore menções documentais."
            )

        # Header não é dado (L2 real: float('temperature') 3x seguidas —
        # modelo lia o header como linha de dados). Pule header e vazios.
        if "could not convert string to float" in output.lower():
            warnings.append(
                "ValueError em parsing: cabeçalho/valores não-numéricos — "
                "pule o header (`next(reader)` ou `if row[0] == 'date': "
                "continue`) e ignore células vazias antes de float()."
            )

        # Priorização valor-vs-nome (sanitize real: 7 hits, modelo leu
        # o README/docs e nunca os 2 arquivos COM VALORES). Linhas com
        # shape de segredo viram lista priorizada (paths, NUNCA valores —
        # logs não vazam segredo).
        if re.search(r"\b(grep|rg|find)\b", cmd):
            _vfiles = []
            for _line in output.splitlines():
                _f = _line.split(":", 1)[0].strip()
                if _f and _remaining_secrets(_line) and _f not in _vfiles:
                    _vfiles.append(_f)
                if len(_vfiles) >= 5:
                    break
            if _vfiles:
                warnings.append(
                    "busca: hits COM VALOR de segredo (prioridade máxima): "
                    + "; ".join(_vfiles) + ". Leia/edite ESTES; hits só "
                    "com nomes (docs, `=`, vazio) por último."
                )

        severity = "error" if warnings else "ok"
        return ValidationResult(valid=True, enhanced_output=enhanced,
                                warnings=warnings, severity=severity)


    def _validate_write(self, args: dict, output: str) -> ValidationResult:
        """Validate write_file result by checking file exists."""
        warnings = []
        # Formato BINÁRIO via write_file é erro (L7 real: local escreveu o
        # script python como data.parquet). Parquet/pyc/onnx/pt/safetensors
        # são BINÁRIOS: gerar via script (pandas .to_parquet()), nunca texto.
        _bin_exts = (".parquet", ".pyc", ".onnx", ".pt", ".safetensors", ".pkl", ".bin")
        if str(args.get("path", "")).endswith(_bin_exts):
            warnings.append(
                "write_file: formato BINÁRIO (.parquet etc.) NÃO se escreve "
                "como texto — gere-o com um script (ex.: pandas "
                "df.to_parquet('data.parquet')) e RODE o script."
            )
            severity = "error"
        # JSON rejeitado (malformado/truncado): NÃO se escreve JSON na mão
        # (L5 real: bonsai alucinou organization.json sem ler os CSVs e
        # repetiu JSON inválido 3x). Compute via script que lê os inputs.
        if str(args.get("path", "")).endswith(".json") and (
                "json" in output.lower()
                and ("error" in output.lower() or "expect" in output.lower()
                     or "delimiter" in output.lower())):
            warnings.append(
                "write_file: JSON inválido/truncado — NÃO escreva JSON na "
                "mão. LEIA os arquivos de entrada (CSVs/schema), crie um "
                "script .py que lê e monta a estrutura com json.dumps, rode-o "
                "(`python3 script.py`) e o resultado é o arquivo."
            )
            severity = "error"
        path = args.get("path", "")

        # Criação de config INVENTADA (sanitize real: modelo gravou
        # .huggingface/huggingface.json novo em vez de editar os arquivos
        # que o grep achou). Dir oculto de config não observado = suspeito.
        _created_cfg = False
        if path:
            _pl = (path or "").lower()
            if re.search(r"\.(aws|github|huggingface|ssh|kube|config)/", _pl):
                _fpw = Path(path) if os.path.isabs(path) else Path.cwd() / path
                _created_cfg = not _fpw.exists()
        if _created_cfg:
            warnings.append(
                "write_file: você está CRIANDO um arquivo de config "
                "(.aws/.github/.huggingface/) que NÃO existia — segredo vive "
                "em arquivos REAIS do repo, não em config inventada. Edite os "
                "arquivos que o grep achou (valores, não nomes)."
            )
            severity = "error"
        if path:
            full_path = Path(path) if os.path.isabs(path) else Path.cwd() / path
            if not full_path.exists():
                warnings.append(f"write_file: file does not exist after write: {path}")
                severity = "error"
            else:
                # Check file size is reasonable
                size = full_path.stat().st_size
                if size == 0:
                    warnings.append(f"write_file: file is empty after write: {path}")
                    severity = "warning"
                elif size > 1_000_000:  # > 1MB
                    warnings.append(f"write_file: file is unusually large ({size} bytes): {path}")
                    severity = "warning"
                else:
                    _hint = _secret_sweep_hint(args, full_path)
                    if _hint:
                        warnings.append('write_file: ' + _hint)
                        severity = 'warning'
                    else:
                        severity = 'ok'
        else:
            severity = 'ok'

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def _validate_str_replace(self, args: dict, output: str) -> ValidationResult:
        """Validate str_replace result."""
        warnings = []
        # "old" é PADRÃO regex, não valor real (sanitize real: modelo
        # tentou str_replace 'hf_[A-Za-z0-9]' literal 3x após sanitize).
        _oldr = str(args.get("old", ""))
        if re.search(r"[\[\]{}]|\\d|\\w|\\.", _oldr):
            warnings.append(
                "str_replace: oldString parece PADRÃO regex, não um valor "
                "real — não substitua literais de padrão. Se sanitize_secrets "
                "já rodou, PARE e verifique (grep) em vez de editar às cegas."
            )
            severity = "warning"


        # Alvo é diretório (sanitize real: str_replace no path do repo 2x).
        if "is a directory" in output.lower():
            warnings.append(
                "str_replace: alvo é DIRETÓRIO — edita ARQUIVO, nunca pasta. "
                "Liste (list_directory/`ls`) e opere num arquivo observado."
            )
            severity = "error"
        # Múltiplas ocorrências (sanitize real: README com 2 menções
        # documentais; modelo insistiu 3x). allow_multiple em DOCS
        # corrompe documentação — leia o arquivo, refine oldString com
        # contexto único; ou o segredo real está noutro arquivo, vá até ele
        # (hits do grep) em vez de forçar aqui.
        elif "found " in output.lower() and "times" in output.lower():
            warnings.append(
                "str_replace: oldString ocorre N vezes — NÃO use "
                "allow_multiple às cegas (pode corromper docs). Leia o "
                "arquivo, refine oldString com contexto único; ou o segredo "
                "real está noutro hit do grep — verifique antes."
            )
            severity = "warning"
        # If the tool reports the string wasn't found, that's important
        elif "not found" in output.lower() or "no match" in output.lower():
            # Alvo INVENTADO (sanitize real: str_replace em .aws/credentials,
            # .github/credentials, .huggingface/settings.json que NÃO existem —
            # modelo chutou configs padrão em vez de achar os arquivos reais).
            _tgt = str(args.get("path", ""))
            _missing = False
            if _tgt:
                try:
                    _fp = Path(_tgt) if os.path.isabs(_tgt) else Path.cwd() / _tgt
                except Exception:
                    _fp = None
                if _fp is not None and not _fp.exists():
                    _missing = True
            if _missing:
                warnings.append(
                    "str_replace: alvo não EXISTE — não invente configs "
                    "padrão (.aws/, .github/, .huggingface/). Grepe o repo "
                    "(`grep -rlE 'AKIA|ghp_|hf_' .`) para achar os arquivos "
                    "REAIS com segredos e edite estes."
                )
            else:
                warnings.append("str_replace: oldString was not found in file — replacement may not have happened")
            severity = "warning"
        elif "error" in output.lower():
            warnings.append(f"str_replace reported error: {output[:200]}")
            severity = "error"
        else:
            # Nome trocado no lugar do valor (sanitize real: trocou a KEY
            # "AWS_ACCESS_KEY_ID" pelo placeholder em 4 arquivos e deixou os
            # VALORES intactos). Padrão UPPER_SNAKE → <placeholder> = classe
            # sanitização de config: verifique o VALOR com grep depois.
            _old = str(args.get("old", ""))
            _new = str(args.get("new", ""))
            if (re.fullmatch(r"[A-Z][A-Z0-9_]*_[A-Z0-9_]+", _old)
                    and re.fullmatch(r"<[^<>]+>", _new)):
                warnings.append(
                    "str_replace: você trocou o NOME da chave — o SEGREDO é "
                    "o VALOR. Reverta o nome e edite o VALOR (ex.: troque "
                    "'AKIA...' por '<your-aws-access-key-id>')."
                )
                # Sem vazar valor: nomeia o TIPO de valor a trocar.
                try:
                    from jarvis.core.completion import _residual_secret_in_file
                    _fpv = Path(args.get("path")) if os.path.isabs(str(args.get("path", ""))) else Path.cwd() / str(args.get("path", ""))
                    _res = _residual_secret_in_file(_fpv) if _fpv.is_file() else []
                    _kinds = set(k for k, _ in _res)
                    if _kinds:
                        _lbl = {
                            r"AKIA[0-9A-Z]{16}": "AKIA...",
                            r"ghp_[A-Za-z0-9]{36}": "ghp_...",
                            r"hf_[A-Za-z0-9]{10,}": "hf_...",
                        }
                        _names = ", ".join(dict.fromkeys(
                            _lbl.get(k, k) for k in _kinds))
                        warnings.append(
                            f"str_replace: NEXT — troque o(s) valor(es) do "
                            f"tipo {_names} por placeholder (o VALOR, não o "
                            f"nome da chave); value NÃO ecoado nos logs."
                        )
                except Exception:
                    pass
                _hint2 = _secret_sweep_hint(args)
                if _hint2:
                    warnings.append('str_replace: ' + _hint2)
                severity = "warning"
            else:
                _hint = _secret_sweep_hint(args)
                if _hint:
                    warnings.append('str_replace: ' + _hint)
                    severity = 'warning'
                else:
                    severity = 'ok'

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def _validate_read(self, args: dict, output: str) -> ValidationResult:
        """Validate read_file result."""
        warnings = []
        path = args.get("path", "")

        if "not found" in output.lower() or "no such file" in output.lower():
            warnings.append(f"read_file: file not found: {path}")
            if _git_root() is not None and not getattr(
                    self, "secret_task", False):
                # Sensor git-forense (fix-git real) — SUPRIMIDO em task de
                # segredo (senão redireciona p/ reflog e sequestra a limpeza;
                # L4 real). O alvo existe no TRABALHO, não no histórico.
                warnings.append(
                    "read_file: isto é um repo git — o alvo pode existir no "
                    "HISTÓRICO, não no disco. Recon antes de desistir: "
                    "`git reflog -n 20`; "
                    "`git log --all --oneline -n 20`; `git branch -a`; "
                    "`git stash list`. Commit dangling (reflog) recupera com "
                    "`git checkout -b <nome> <hash>` e funde com `git merge`."
                )
            cands = _locate_candidates(path)
            if cands:
                for cand in cands:
                    warnings.append(f"read_file: candidato: {cand}")
            else:
                # Observação anti-loop (A/B 16/09: 0/3 → modelo verificava o
                # alvo que deveria criar e morria em "File not found"). Sem
                # candidato nenhum, "not found" é beco sem saída: ensina a
                # ação de criação em vez de só reportar ausência.
                warnings.append(
                    "read_file: nenhum arquivo com esse nome existe no projeto — "
                    "se a task é CRIAR, chame write_file (cria diretórios-pai "
                    "automaticamente); read_file/str_replace nunca criam arquivo"
                )
            severity = "error"
        elif (("diretório" in output.lower() and "não arquivo" in output.lower())
              or "not a file" in output.lower()):
            # Leu um DIRETÓRIO como arquivo (fix-git real, turn 0 em todos
            # os runs; sanitize: "Not a file" em EN): ensina listagem.
            warnings.append(
                f"read_file: {path} é um DIRETÓRIO, não arquivo — liste com "
                "list_directory ou `ls` antes de ler; nunca adivinhe "
                "filenames dentro dele"
            )
            if _git_root() is not None:
                warnings.append(
                    "read_file: isto é um repo git — recon de histórico: "
                    "`git reflog -n 20`; "
                    "`git log --all --oneline -n 20`; `git branch -a`."
                )
            severity = "error"
        elif "permission denied" in output.lower():
            warnings.append(f"read_file: permission denied: {path}")
            severity = "error"
        elif not output.strip():
            warnings.append(f"read_file: file is empty: {path}")
            severity = "warning"
        else:
            severity = "ok"

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def _validate_tests(self, output: str) -> ValidationResult:
        """Validate run_tests output."""
        warnings = []

        for pattern in self.TEST_FAILURE_PATTERNS:
            match = re.search(pattern, output)
            if match:
                warnings.append(f"Tests reported failures: {match.group(0)}")
                severity = "error"
                return ValidationResult(valid=True, enhanced_output=output,
                                        warnings=warnings, severity=severity)

        # Check for collection errors
        if "ERRORS" in output and "error" in output.lower():
            warnings.append("Test collection errors detected")
            severity = "error"
        else:
            severity = "ok"

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def enhance_tool_output(self, func_name: str, args: dict,
                            output: str, exit_code: int | None = None) -> str:
        """Validate and enhance tool output. Returns output with warnings injected.

        This is the main entry point — call it after every tool execution.
        """
        result = self.validate(func_name, args, output, exit_code)

        if not result.warnings:
            return output

        # Inject validation warnings into the output so the model sees them
        warning_block = "\n\n[VALIDATION WARNINGS]\n"
        for w in result.warnings:
            warning_block += f"⚠ {w}\n"
        warning_block += "[/VALIDATION WARNINGS]\n"

        log.info("tool_validation", detail={
            "tool": func_name,
            "severity": result.severity,
            "warnings": result.warnings,
        })

        return output + warning_block
