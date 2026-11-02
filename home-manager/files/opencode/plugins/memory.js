// Memory + safety plugin — declarative via home-manager (12/10).
// Plain .js (not .ts) on purpose: `node --check` validates it with zero
// toolchain; opencode loads .js and .ts identically from plugins/.
//
// Verified APIs in this opencode version (v1.18.34 — tag v1.18.34,
// packages/plugin/src/index.ts):
//   - "tool.execute.before" with MUTABLE output.args (rtk rewrites
//     args.command through it — the deny below uses the same channel)
//   - "experimental.session.compacting" with output.context.push (docs)
//   - "experimental.chat.system.transform" with output.system.push  ← NOVO
//     (o comentário antigo deste arquivo dizia que não existia API de
//     injeção de contexto: era FALSO nesta versão — verificado no source)
//   - "experimental.chat.messages.transform" com output.messages.push
//
// POR QUE a injeção existe (pesquisa 02/11, docs/REHYDRATACAO-E-COORDENACAO.md):
//   - O resgate dependia de o agente LEMBRAR de chamar recall/rag_search →
//     disciplina, não harness. Agora o harness injeta a regra.
//   - Contexto é recurso finito: a injeção é MINUTA (~6 linhas), sem estado
//     (2510.05381: contexto longo fere mesmo com retrieval perfeita;
//     2602.11988: AGENTS.md inflado = +20-23% custo e ganho zero).
//   - Guardas de coordenação são PINADAS (não resumíveis): 5 compactações
//     derrubam a aderência a regras de 53% -> 10% (2608.22752).
//
// A/B: OPENCODE_NO_REHYDRATE_INJECT=1 desliga a injeção (medição M2 e
// rollback sem rebuild — ver docs/REHYDRATACAO-E-COORDENACAO.md §5).

// Root-delete: rm com flag recursiva+force apontando para / ou ~.
// A flag pode vir em qualquer ordem (-rf, -fr, -Rf, -fR) e maiúscula (-R é
// recursiva no rm). Hole antigo: o padrão exigia 'r' antes de 'f', então
// `rm -fr /` passava reto (achado pelo teste do plugin, 02/11).
const ROOT_DELETE =
  /(^|[;&|\s])rm\s+[^;&|]*-[a-zA-Z]*(?:[rR][a-zA-Z]*[fF]|[fF][a-zA-Z]*[rR])[^;&|]*\s+(\/(\s|$|;|\*)|\~(\s|$|;))/;

// Regras de coordenação — PINADAS, copiadas literalmente. Nunca resumir,
// nunca reescrever: é o que a compactação faz de pior (2608.22752).
const PINNED_GUARDS = `## Guardas de coordenação (pinadas — não resumir)
- claim antes de falar: \`scripts/agent-roster.py claim --name <n> --lane <lane> --repo <repo> --files <globs>\`
- entrega: \`scripts/agent-msg.sh --to <nome> "texto"\` (o alvo roda) · \`--note "texto"\` (entra na sessão, NÃO roda) · \`--cancel <id>\` (aborta o turno)
- nunca wtype/focus para falar com outro agente: trava o typing do humano
- wake: \`agents-watcher.sh\` acorda via API e filtra por repo/lane`;

// Regra do harness para o RESGATE (o que faltava).
const REHYDRATE_RULE = `## Re-hidratação (primeira tool da sessão)
1ª tool de uma sessão nova, ou logo após uma compactação, ou ao tropeçar num
problema que parece repetido: \`jarvis_rehydrate(task="<o que vou fazer>")\`.
Devolve em 1 chamada: guardas + fila + HANDOFF + memórias + lições + RAG +
roster. É mais barato que refazer o diagnóstico.
${PINNED_GUARDS}`;

const COMPACTION_MEMORY = `## Memory protocol (auto-injected pre-compaction)
Recall BEFORE acting in the new session: jarvis_recall top_k=5 on the
active topic. At task end / topic switch: jarvis_remember (fact, event,
decision, error). Routing — decision>1 session: memory + note; resume
pointers: vault handoff note (git-synced); ground truth: VERDADES.md +
checker run; transient: chat only, never stored; secrets: names only.
Validate live state on wake: model tiers, service PIDs vs git log,
/run/current-system vs booted generation (a reboot may have reverted a
test-activated switch).
## Pós-compactação: a PRIMEIRA tool call é jarvis_rehydrate(task="...")
As guardas abaixo são PINADAS (copiadas exatas — não resumir):
${PINNED_GUARDS}`;

export const MemoryOpenCodePlugin = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      const tool = String(input?.tool ?? "").toLowerCase();
      if (tool !== "bash" && tool !== "shell") return;
      const args = output?.args;
      if (!args || typeof args !== "object") return;
      const command = args.command;
      if (typeof command !== "string" || !command) return;
      // Unanchored root deletes are never legit (rm -rf /, ~, /*).
      // Scoped deletes (/home/.../x, /tmp/...) pass through untouched.
      // Deny runs through the SAME args channel rtk rewrites through.
      if (ROOT_DELETE.test(command)) {
        args.command =
          "echo 'DENIED by memory-plugin: unanchored root delete. " +
          "Rescue ladder: git commit > trash dir > verified snapshot. " +
          "Narrow the path.' >&2; exit 1";
      }
    },
    // (02/11) Regra do resgate no system prompt — MINUTA, sem estado.
    // É o que transforma "lembre-se de reidratar" em regra do harness.
    "experimental.chat.system.transform": async (input, output) => {
      if (process.env.OPENCODE_NO_REHYDRATE_INJECT === "1") return;
      if (output && Array.isArray(output.system)) {
        output.system.push(REHYDRATE_RULE);
      }
    },
    "experimental.session.compacting": async (input, output) => {
      if (output && Array.isArray(output.context)) {
        output.context.push(COMPACTION_MEMORY);
      }
    },
  };
};
