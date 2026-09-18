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
principal. Fonte atual: [[../benchmarks/README|/home/nixos/projects/nixos-ai/docs/README.md]].

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
| `architecture-proposal-legacy.md` | `architecture/ADR-001-agent-platform.md` (com ressalva: é uma proposta de época, não um ADR formal atual) |

> **Nota de integridade**: `architecture-proposal-legacy.md` é a proposta de estrutura de 2026-08-16 que antecedeu a consolidação. Se quiser que eu o mova para `audit/archive/` ou crie um inventário mais fino entre o que foi implementado vs o que foi apenas proposto, eu posso separar isso sem remover o conteúdo.

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
| `BP-BONSAI-TEST.md` | Testes com Bonsai (histórico) |
| `STATE-OF-2026-09-09.md` | Snapshot de estado do sistema (histórico) |
| `MISSAO-2026-09-09.md` | Conteúdo da missão de 2026-09-09 (histórico) |

### `misc-forensics/` — Forense e incidentes documentados

Documentos de investigação de episódios pontuais que não são guia operacional e podem conter afirmações não validadas por teste.

| Arquivo | Foco |
|---------|------|
| `FORENSIC-SYSTEM-COHERENCE-2026-09-08.md` | Coerência do sistema em 2026-09-08 |
| `LOCAL-MODEL-EVALUATION-2026-09-08.md` | Avaliação de modelo local |
| `LOCAL-MODEL-ROUTING-FORENSIC-2026-09-08.md` | Roteamento de modelo local |
| `DEEP-INTEGRATION-REDTEAM-2026-09-08.md` | Integração e red team |
| `P0-ATAQUE-2026-09-08.md` | Episódio de ataque P0 |
| `UX-ABISMO-2026-09-08.md` | Investigação de UX |
| `CHATGPT-ATTACK-PROMPT.md` | Prompt de ataque via ChatGPT (histórico) |

### `_trash/` — NÃO INDEXAR

Arquivos que **não devem** ser incluídos no corpus RAG:

| Arquivo | Motivo |
|---------|--------|
| `aider-chat-history.md` | 731KB de log bruto de chat — ruído semântico massivo |
| `context-engineering-duplicate.md` | Duplicata explícita — conteúdo em `architecture/context-engineering.md` |
| `moe-profiling-results.json` | JSON de profiling bruto — não é documentação |
| `JARVIS-COMPARISON.mmd` | Duplicata do `.md` equivalente |

---
**Ver também:** [[../architecture/system-overview|/home/nixos/projects/nixos-ai/docs/architecture/system-overview.md]] | [[../audit/INDEX|/home/nixos/projects/nixos-ai/docs/architecture/INDEX.md]] | [[../README|/home/nixos/projects/nixos-ai/docs/README.md]]

---
**Nota de validação**: os documentos listados aqui foram arquivados por critério narrativo/temporal; onde possível o arquivamento foi alinhado ao que o código/docs atuais dizem, mas alguns itens podem ainda precisar de decisão manual para confirmar que não há versão viva que os substituiu.
