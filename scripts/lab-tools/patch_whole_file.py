#!/usr/bin/env python3
"""Aplica o fallback de ARQUIVO INTEIRO no nightwatch/harness.py (17/11).

Por que: o patcher pede hunks (old_text/new_text). Medido no A/B: o bonsai
erra o hunk em 100% dos ciclos e a task morre com 0 bytes escritos — o
laboratorio nao mede capacidade, mede "acertou o substring?". Um modelo
pequeno acerta MUITO mais reescrever o arquivo todo (tokens sao baratos
localmente) e o SafeEditor valida antes de gravar.

Idempotente: se o marcador ja existe, nao faz nada.
"""
import sys
from pathlib import Path

P = Path(sys.argv[1] if len(sys.argv) > 1 else
         "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/nightwatch/harness.py")
src = P.read_text(encoding="utf-8")

MARCA = "_whole_file_retry"
if MARCA in src:
    print("ja aplicado")
    raise SystemExit(0)

ANTIGO = '''                    for file_patch in patches:
                        # Apply patch hunks to get new content
                        patch_ok, patched_content, patch_diff = apply_patch(file_patch)

                        if not patch_ok:
                            apply_errors.append(f"Patcher failed for {file_patch.path}: {patched_content}")
                            cp.record_operation(f"patch:{file_patch.path}", False, patched_content)
                            continue

                        # Validate and write via SafeEditor (atomic, validated)
                        resolved = _resolve_file_path(file_patch.path)
                        edit_result: EditResult = self.editor.apply_edit(
                            resolved, patched_content, validate=True
                        )
                        if edit_result.success:
                            applied_files.append(file_patch.path)
                            cp.record_operation(f"write:{file_patch.path}", True)
                        else:
                            apply_errors.extend(edit_result.errors)
                            cp.record_operation(f"write:{file_patch.path}", False, "; ".join(edit_result.errors))
'''

NOVO = '''                    for file_patch in patches:
                        # Apply patch hunks to get new content
                        patch_ok, patched_content, patch_diff = apply_patch(file_patch)
                        resolved = _resolve_file_path(file_patch.path)
                        _falhou = True

                        if patch_ok:
                            # Validate and write via SafeEditor (atomic, validated)
                            edit_result: EditResult = self.editor.apply_edit(
                                resolved, patched_content, validate=True
                            )
                            if edit_result.success:
                                applied_files.append(file_patch.path)
                                cp.record_operation(f"write:{file_patch.path}", True)
                                _falhou = False
                            else:
                                apply_errors.extend(edit_result.errors)
                                cp.record_operation(f"write:{file_patch.path}", False, "; ".join(edit_result.errors))
                        else:
                            apply_errors.append(f"Patcher failed for {file_patch.path}: {patched_content}")
                            cp.record_operation(f"patch:{file_patch.path}", False, patched_content)

                        if _falhou and os.environ.get("JARVIS_NO_WHOLE_FALLBACK") != "1":
                            # (17/11) FALLBACK ARQUIVO INTEIRO — o modo que o
                            # modelo fraco consegue. Medido no A/B: bonsai
                            # errava o hunk 2/2 e devolvia 0 bytes; a tarefa
                            # morria sem medir capacidade nenhuma.
                            _err = "; ".join(apply_errors[-3:]) or "patch nao aplicou"
                            _whole = self._whole_file_retry(file_patch.path, task.description, _err)
                            if _whole:
                                _er = self.editor.apply_edit(resolved, _whole, validate=True)
                                if _er.success:
                                    applied_files.append(file_patch.path)
                                    cp.record_operation(f"write-whole:{file_patch.path}", True)
                                    self.notify(f"🧩 Whole-file fallback OK: {file_patch.path}")
                                    _falhou = False
                                else:
                                    apply_errors.extend(_er.errors)
                                    cp.record_operation(f"write-whole:{file_patch.path}", False, "; ".join(_er.errors))
'''

if ANTIGO not in src:
    print("ERRO: bloco de aplicacao de patch nao encontrado (harness mudou?)", file=sys.stderr)
    raise SystemExit(2)
src = src.replace(ANTIGO, NOVO, 1)

METODO = '''    def _whole_file_retry(self, path: str, task_description: str, error_text: str) -> str | None:
        """(17/11) Pede o ARQUIVO INTEIRO quando o hunk nao aplica.

        Por que existe: modelos pequenos erram o substring exato do hunk mas
        acertam reescrever o arquivo — tokens sao baratos localmente e o
        SafeEditor valida antes de gravar. Sem isso o A/B media "acertou o
        hunk?" em vez de "resolveu a tarefa?" (bonsai: 0 bytes em 100%).
        """
        try:
            resolved = _resolve_file_path(path)
            if not resolved.exists() or not resolved.is_file():
                return None
            current = resolved.read_text(encoding="utf-8")
        except Exception:
            return None
        if len(current) > 24000:
            return None  # nao cabe no contexto de um modelo pequeno
        prompt = (
            "Rewrite ONE Python file completely. Return the COMPLETE new file content.\\n"
            f"Task: {task_description}\\n\\n"
            f"The previous attempt failed because: {error_text[:600]}\\n\\n"
            f"=== FILE: {path} ===\\n{current}\\n=== END OF FILE ===\\n\\n"
            "Reply with the full file only. No markdown fences, no commentary.\\n"
        )
        try:
            out = self.call_llm(prompt, 4096)
        except Exception:
            return None
        if not out or not out.strip():
            return None
        try:
            from nightwatch.safe_editor import strip_markdown_fences
            text = strip_markdown_fences(out).strip()
        except Exception:
            text = out.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
        # Guarda-corpo: precisa PARECER um arquivo Python e nao encolher demais
        _qq = chr(34) * 3
        _sq = chr(39) * 3
        if not (text.startswith(("import ", "from ", "#", "class ", "def ", "@", "#!/"))
                or text.startswith((_qq, _sq))):
            return None
        if len(text) < max(80, int(len(current) * 0.4)):
            return None
        return text if text.endswith("\\n") else text + "\\n"

'''

ANCORA = "    def _fail_task(self, task: Task, error: str) -> None:"
if ANCORA not in src:
    print("ERRO: ancora _fail_task nao encontrada", file=sys.stderr)
    raise SystemExit(3)
src = src.replace(ANCORA, METODO + ANCORA, 1)

P.write_text(src, encoding="utf-8")
print(f"OK: fallback de arquivo inteiro aplicado em {P}")
