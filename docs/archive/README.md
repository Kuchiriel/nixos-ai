# Archive — Documentação Histórica

> Contém documentação que já não é a fonte de verdade ativa,
> mas que é preservada para rastreabilidade histórica.

## Critério de Arquivamento

Um documento é movido para archive/ quando:
1. Foi **supersedido** por uma versão mais recente em `architecture/` ou `audit/`
2. É um **resultado histórico** (benchmark de data passada, diagnóstico resolvido)
3. É **material de pesquisa** que informou decisões já tomadas
4. É um **componente legado** substituído por módulo mais recente

**Regra**: Nunca deletar — sempre mover para archive/. Manter referência ao
módulo substituto quando aplicável.

## Subdiretórios

### `benchmarks/` — Benchmarks Históricos

Resultados de performance anteriores à adoção do Qwen3.6-35B-A3B como modelo
principal. Fonte atual: [[../benchmarks/README]].

| Arquivo | Data | Supersedido por |
|---------|------|-----------------|
| `aider-benchmark-legacy.md` | Pré-2026-08 | `benchmarks/performance-evidence-audit.md` |
| `baseline.md` | 2026-08 | `benchmarks/ncmoe-sweep.md` |
| `benchmark-definitivo-2026-08-26.md` | 2026-08-26 | Benchmark 2026-09-02 (BUFFY §12) |
| `llama-moe-benchmark-final.md` | 2026-08 | `benchmarks/gpu-moe-fix-2026-08-28.md` |
| `mlock-benchmark-results.md` | 2026-08 | Não aplicável (descontinuado) |
| `moe-benchmark-results.md` | 2026-08 | `benchmarks/ncmoe-sweep.md` |
| `resource-calculation.md` | 2026-08 | BUFFY §12 |

### `diagnostics/` — Diagnósticos Históricos

Investigações de performance e thermal já resolvidas.

| Arquivo | Diagnóstico | Status |
|---------|------------|--------|
| `attention-bottleneck-diagnostic.md` | Bottleneck de atenção MoE | Resolvido via ncmoe |
| `ehs-diagnostico-por-que-6porcento.md` | Expert hit rate 6% | Resolvido |
| `ehs-overlap-diagnostico-final.md` | Expert overlap | Resolvido |
| `moe-execution-path-diagnostic.md` | Path de execução MoE | Resolvido |
| `moe-gargalo-diagnostico.md` | Gargalo MoE | Resolvido |
| `thermal-curve-analysis.md` | Curva thermal | Informativo |
| `thermal-throttling-diagnostic.md` | Thermal throttling | Resolvido |
| `truth-30-vs-18-tok-s.md` | Investigação de velocidade | Resolvido |

### `legacy-components/` — Arquitetura Legada

Componentes de arquitetura que foram redesenhados ou substituídos.

| Arquivo | Substituído por |
|---------|----------------|
| `legacy-audio-calibration.md` | `jarvis-voice` (NixOS service) |
| `legacy-compiler-expert.md` | `modules/ai/jarvis/` (harness atual) |
| `legacy-inventory-findings.md` | `audit/legacy/` (inventário atual) |
| `architecture-audit.md` | `audit/current/FULL-REPO-AUDIT-2026-09-03.md` |
| `architecture-proposal-legacy.md` | `architecture/ADR-001-agent-platform.md` |

### `research/` — Pesquisa Histórica

Material de pesquisa que informou decisões de arquitetura, mas não é guia operacional.

| Arquivo | Informou |
|---------|---------|
| `rtx4050-vs-mundo-tok-s.md` | Escolha do modelo e configuração ncmoe |
| `harness-audit-2026-08-27.md` | Design do nightwatch harness atual |
| `harness-gap-analysis.md` | Gaps resolvidos no harness v2 |
| `chatgpt-conversation-2026-08-27.md` | Gap analysis ChatGPT |
| `claude-web-prompt-template.md` | Template de prompt web (histórico) |
| `llama-moe-optimization.md` | Otimização MoE (supersedido por ncmoe-sweep) |

### `_trash/` — NÃO INDEXAR

Arquivos que **não devem** ser incluídos no corpus RAG:

| Arquivo | Motivo |
|---------|--------|
| `aider-chat-history.md` | 731KB de log bruto de chat — ruído semântico massivo |
| `context-engineering-duplicate.md` | Duplicata explícita — conteúdo em `architecture/context-engineering.md` |
| `moe-profiling-results.json` | JSON de profiling bruto — não é documentação |
| `JARVIS-COMPARISON.mmd` | Duplicata do `.md` equivalente |

---
**Ver também:** [[../architecture/system-overview]] | [[../audit/INDEX]]
