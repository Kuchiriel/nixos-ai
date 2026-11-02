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

// Coordination rules — PINNED, copied verbatim. Never summarize, never
// rewrite: that is what compaction does worst (2608.22752).
// LANGUAGE: English on purpose. Everything an LLM reads is English — small
// local models (bonsai) do not understand pt-BR, and a rule the model cannot
// read is a rule that does not exist.
const PINNED_GUARDS = `## Coordination rules (pinned — never summarize)
- claim before speaking: \`scripts/agent-roster.py claim --name <n> --lane <lane> --repo <repo> --files <globs>\`
- delivery: \`scripts/agent-msg.sh --to <name> "text"\` (the target runs) · \`--note "text"\` (enters the session, does NOT run) · \`--cancel <id>\` (aborts the target turn)
- never use wtype/focus to talk to another agent: it blocks the human's typing
- wake: \`agents-watcher.sh\` wakes via the API and filters by repo/lane`;

// The harness rule for the RESCUE (what was missing).
const REHYDRATE_RULE = `## Rehydration (first tool of the session)
First tool of a new session, right after a compaction, or whenever a problem
looks like a repeat: \`jarvis_jarvis_rehydrate(task="<what you are about to
do>")\` (opencode prefixes MCP tools with the server key, so the exposed
name is \`jarvis_jarvis_rehydrate\`).
One call returns: pinned guards + queue top + HANDOFF + memories + lessons +
RAG + roster. Cheaper than redoing the diagnosis.
ONE call only — do not repeat it (the rescue already returned the state; the
rest is at the paths). Repeating burns context (measured: 293k input tokens
in a loop).
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
## After compaction: the FIRST tool call is jarvis_rehydrate(task="...")
The rules below are PINNED (copied exactly — never summarize):
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
    //
    // MERGE, não push: o system prompt é UM bloco só (medido: 1 bloco,
    // 20073 chars). Push cria um SEGUNDO system message e o template do
    // modelo (Qwen3.5 + Jinja) aborta com "System message must be at the
    // beginning" — erro real achado na 1ª medição (run A: rc=1, 77s, vazio).
    // Por isso: anexa ao ÚLTIMO bloco (mantém a contagem → 1 system message)
    // e fica no fim do prompt = posição de maior recência (2510.05381).
    "experimental.chat.system.transform": async (input, output) => {
      if (process.env.OPENCODE_NO_REHYDRATE_INJECT === "1") return;
      if (!output || !Array.isArray(output.system)) return;
      if (output.system.length === 0) {
        output.system.push(REHYDRATE_RULE);
        return;
      }
      const last = output.system.length - 1;
      output.system[last] = `${output.system[last] ?? ""}\n\n${REHYDRATE_RULE}`;
    },
    "experimental.session.compacting": async (input, output) => {
      if (output && Array.isArray(output.context)) {
        output.context.push(COMPACTION_MEMORY);
      }
    },
  };
};
