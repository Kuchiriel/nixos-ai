# IMPROVEMENT-ROADMAP — aprovadas/pendentes (2026-11-19)

## Concluídas nesta missão
1. Checkpoint persistente (`PROJECT-AUDIT-STATE.md` + log append-only).
2. Mapa arquitetural real (`ARCHITECTURE-MAP.md`).
3. Auditorias: Knowledge, OpenCode Continuity, NixOS (`docs/audit/`).
4. Correções P1: AGENTS injection, model route v2, hub close, Task.project,
   guard de compactação, redaction de IP, quarentena privada de PHI.

## Pendentes (próximas, em ordem de impacto)
1. **#18 A/B de chunking** — runner resiliente em execução; fechar com convergência
   medida (single 1 checker vs chunks 3 checkers) quando 12/12 válidas.
2. **RAG recall** — gate fechado em `b907a442` (recall@8 0.93, MRR 0.762 com
   15 perguntas, ver `RAG-EVAL.md`). Resta opcional: recall da pergunta
   "chars per chunk" (o candidato não entra no top-k cru) e backfill do
   payload canônico nos pontos antigos (`8834e98c`), que exige reindexar.
3. **Compactação** — substituir resumo degenerado no core (hook só avisa).
4. **ADR-003** — aguardar convergência `dev.py→agent_loop.py`; não micro-patch.
5. **Sync host↔phone** — escolher canônico por ferramenta (4 divergentes);
   nunca overwrite cego; report-only hoje.
6. **Checkpoint verificável** — associar task/agent/HEAD/arquivos/fila/vault/RAG/testes
   em um único registro assinado (reutilizar scripts existentes, não criar outro).

## Fora de escopo sem autorização
- Migrações/cleanup em Qdrant de produção.
- `nixos-rebuild switch`, `rebuild-host.sh`, restart de llama-server, boot/VM/Hyper-V.
- Reescrita de histórico Git, rotação de credenciais.
- Exclusão de notas do Vault ou dados persistentes.
