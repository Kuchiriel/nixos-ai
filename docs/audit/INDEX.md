# Índice de Auditorias — nixos-ai

> Índice cronológico de todas as auditorias do projeto.
> **Regra BUFFY §8**: Distinguir CURRENT_STATE (audit/current/) de HISTORICAL (audit/completed/).

## Auditorias Ativas (itens ainda abertos)

| Auditoria | Data | Foco | Itens abertos |
|-----------|------|------|---------------|
| [[CONTROL-PLANE-AUDIT-2026-09-03]] | 2026-09-03 | EventBus, SSE, CommandRegistry | SSE→browser, Telegram, Voice |
| [[CONTROL-PLANE-AUDIT-2026-09-03-HARDENING]] | 2026-09-03 | Hardening e segurança | Ver doc |
| [[SESSION-AUDIT-2026-09-04]] | 2026-09-04 | Personas, pipeline E2E | 9/10 personas não testadas, 0 handovers |
| [[FULL-REPO-AUDIT-2026-09-03]] | 2026-09-03 | Auditoria completa do repo | Ver doc |

## Auditorias Concluídas (todos os itens resolvidos)

| Auditoria | Data | Foco | Resultado |
|-----------|------|------|-----------|
| [[AUDIT-2026-08-29]] | 2026-08-29 | Auditoria inicial | ✅ Resolvido |
| [[FORENSIC-VERIFICATION-2026-09-03]] | 2026-09-03 | Verificação forense P0-P3 | ✅ 10/10 findings resolvidos |
| [[HARNESS-AUDIT-2026-09-01]] | 2026-09-01 | Harness Nightwatch | ✅ Resolvido |
| [[BENCHMARK-AUDIT-2026-09-01]] | 2026-09-01 | Auditoria de benchmarks | ✅ Resolvido |
| [[GAP-ANALYSIS-2026-08-29]] | 2026-08-29 | Gap analysis (ChatGPT) | ✅ P0.1-P0.4 resolvidos; P1.2 framework |
| [[CONTROL-PLANE-AUDIT]] | (sem data) | Auditoria base do control plane | ✅ Base resolvida |

## Inventário Legado

| Arquivo | Foco |
|---------|------|
| [[01-current-nixos]] | Estado do NixOS atual |
| [[02-legacy-inventory]] | Inventário do sistema legado |
| [[03-legacy-functionality-map]] | Mapa funcional do legado |

## Achados Críticos Consolidados (BUFFY §13)

Da auditoria forense (2026-09-03), todos resolvidos:

| Finding | Severidade | Status |
|---------|------------|--------|
| `--dry-run` não conectado no persona_executor | P0 | ✅ FIXED |
| Hardcoded `/home/nixos/projects` | P1 | ✅ FIXED |
| `files_changed` reportava candidatos, não mudanças reais | P2 | ✅ FIXED |
| `except Exception: pass` silenciava erros | P3 | ✅ FIXED |
| self_test.py referenciava módulos arquivados | P2 | ✅ FIXED |
| checkpoint.json não era por-projeto | P1 | ✅ FIXED |
| Agent loop nunca alimentava contexto de erro ao LLM | P0 | ✅ FIXED |
| Test count 302 declarado, 820 real | P0 | ✅ FIXED (859 atual) |

## Itens Abertos Prioritários (CURRENT_STATE)

De SESSION-AUDIT-2026-09-04:

- [ ] **10 personas definidas, 1 testada, 0 handovers testados** (HIGH)
- [ ] **Validação long-run >30min com LLM online** (HIGH — ver TODO-MISSAO P3-2)
- [ ] **Pipeline E2E real** (não mocks) — trajetória real de agente (HIGH)

---
**Ver também:** [[../architecture/nightwatch-components]]
[[../architecture/mission-consolidation]] | [[../architecture/agent-harness]]
[[../../HANDOFF]] | [[../../BUFFY]]
