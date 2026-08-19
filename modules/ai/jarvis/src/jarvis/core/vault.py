"""Memória de longo prazo do JARVIS — vault markdown git-syncado.

Fase 7 (pendência "resumo de longo prazo/sessões"). Inspiração do usuário:
o `m3ta-brain`/`shared-brain-vault` do repo AGENTS (Sascha Koenig) — um vault
markdown versionado em git como cérebro de longo prazo.

Fluxo (`jarvis vault summarize`):
  1. lê os eventos episódicos recentes (Qdrant `memories`) desde a última
     execução (janela configurável, default 7 dias);
  2. chama o LLM local para condensar em markdown estruturado (lições,
     decisões, fatos);
  3. grava em `vault/<YYYY-MM>.md` (uma seção por resumo) — o vault é um
     repo git (iniciado sob demanda) para sync/backup;
  4. grava o resumo de volta na memória episódica (kind=fact, meta
     `summary`) — o `recall` semântico continua sendo o caminho de busca.

RAG (conhecimento) ≠ memória episódica (experiência) ≠ vault (síntese):
o vault é a camada de síntese — o que sobra quando o detalhe é condensado.
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.core.config import Config, get_config
from jarvis.core.memory import EpisodicMemory, KIND_FACT
from jarvis.providers.llm import LLMClient

_SUMMARY_PROMPT = """\
Você é o JARVIS, a IA de bordo de um sistema NixOS. Condense os eventos \
episódicos abaixo em um resumo markdown de longo prazo (máx ~50 linhas), \
em PT-BR, agrupado por tipo:

## Lições (erro → fix que funcionou)
## Decisões
## Fatos e preferências
## Padrões observados

Não invente nada além do que está nos eventos; omita detalhe operacional \
efêmero (comandos pontuais) — o objetivo é o que vale lembrar semanas \
depois.

Eventos:
{events}
"""


class MemoryVault:
    """Síntese de longo prazo: memória episódica → markdown versionado."""

    def __init__(
        self,
        config: Config | None = None,
        memory: EpisodicMemory | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self._cfg = config or get_config()
        self._memory = memory or EpisodicMemory(self._cfg)
        self._llm = llm or self._memory._llm

    # --- infra ---

    @property
    def vault_dir(self) -> Path:
        return self._cfg.vault_dir

    def _ensure_vault(self) -> Path:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        if not (self.vault_dir / ".git").exists():
            self._git("init", "-q")
        return self.vault_dir

    def _git(self, *args: str) -> bool:
        """Executa git no vault de forma defensiva — falha silenciosa."""
        try:
            subprocess.run(
                ["git", "-C", str(self.vault_dir), *args],
                capture_output=True, timeout=30, check=False,
            )
            return True
        except (OSError, subprocess.SubprocessError):  # noqa: BLE001
            return False

    def _month_file(self, ts: float) -> Path:
        return self.vault_dir / f"{datetime.fromtimestamp(ts):%Y-%m}.md"

    # --- leitura ---

    def list_notes(self) -> list[str]:
        """Arquivos .md do vault (mais recentes primeiro)."""
        if not self.vault_dir.exists():
            return []
        return sorted(
            (p.name for p in self.vault_dir.glob("*.md")),
            reverse=True,
        )

    # --- síntese ---

    def _collect_events(self, since_days: int, limit: int = 1000) -> list[dict[str, Any]]:
        cutoff = time.time() - since_days * 86400
        events = self._memory.recent(limit=limit)
        return [e for e in events if e.get("ts", 0) >= cutoff]

    @staticmethod
    def _format_events(events: list[dict[str, Any]]) -> str:
        lines = []
        for e in sorted(events, key=lambda e: e.get("ts", 0)):
            ts = datetime.fromtimestamp(e.get("ts", 0)).strftime("%Y-%m-%d %H:%M")
            kind = e.get("kind", "event")
            text = e.get("text", "").strip()
            if kind == "lesson":
                task = e.get("task", "")
                err = e.get("error_pattern", "")
                fix = e.get("fix", "")
                text = f"task={task!r} error={err!r} fix={fix!r}"
            lines.append(f"- [{kind}] {ts}: {text}")
        return "\n".join(lines)

    def summarize(self, since_days: int = 7, *, commit: bool = True) -> dict[str, Any]:
        """Condensa os eventos recentes no vault e devolve o resultado."""
        events = self._collect_events(since_days)
        if not events:
            return {"written": False, "reason": "no_events", "count": 0}

        prompt = _SUMMARY_PROMPT.format(events=self._format_events(events))
        try:
            summary = self._llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=800,
            ).strip()
        except Exception as exc:  # noqa: BLE001
            return {"written": False, "reason": f"llm_error: {exc}", "count": len(events)}

        now = time.time()
        month_file = self._month_file(now)
        self._ensure_vault()
        heading = f"## Resumo {datetime.fromtimestamp(now):%Y-%m-%d %H:%M} ({len(events)} eventos)\n"
        with month_file.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{heading}\n\n{summary}\n")

        if commit:
            self._git("add", "-A")
            self._git("commit", "-q", "-m", f"jarvis: resumo de memória {datetime.fromtimestamp(now):%Y-%m-%d}")

        # escreve de volta na memória episódica → recall semântico acha o resumo
        fact_text = (
            f"Resumo de memória de longo prazo ({datetime.fromtimestamp(now):%Y-%m-%d}, "
            f"{len(events)} eventos): {summary[:900]}"
        )
        fact_id = None
        try:
            fact_id = self._memory.remember_fact(fact_text, summary=True,
                                                 source=str(month_file.name))
        except Exception:  # noqa: BLE001
            pass

        try:
            from jarvis.providers.telegram import send_notification

            send_notification(
                f"🧠 Vault: resumo semanal gravado ({len(events)} eventos) "
                f"em {month_file.name}"
            )
        except Exception:  # noqa: BLE001 — notificação nunca quebra o resumo
            pass

        return {
            "written": True,
            "path": str(month_file),
            "count": len(events),
            "fact_id": fact_id,
        }
