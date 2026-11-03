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
//     (the old comment in this file said there was no context injection
//     API: it was FALSE in this version — verified in the source)
//   - "experimental.chat.messages.transform" with output.messages.push
//
// WHY the injection exists (research 02/11, docs/REHYDRATACAO-E-COORDENACAO.md):
//   - The rescue depended on the agent REMEMBERING to call recall/rag_search →
//     discipline, not harness. Now the harness injects the rule.
//   - Context is a finite resource: the injection is TINY (~6 lines), stateless
//     (2510.05381: long context hurts even with perfect retrieval;
//     2602.11988: an inflated AGENTS.md = +20-23% cost and zero gain).
//   - Coordination guardrails are PINNED (not summarizable): 5 compactions
//     drop the adherence to rules from 53% -> 10% (2608.22752).
//
// A/B: OPENCODE_NO_REHYDRATE_INJECT=1 turns the injection off (M2 measurement and
// rollback without a rebuild — see docs/REHYDRATACAO-E-COORDENACAO.md §5).

// Root-delete: rm with a recursive+force flag pointing at / or ~.
// The flag can come in any order (-rf, -fr, -Rf, -fR) and uppercase (-R is
// recursive in rm). Old hole: the pattern required 'r' before 'f', so
// `rm -fr /` sailed through (found by the plugin test, 02/11).
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
looks like a repeat: \`jarvis_rehydrate(task="<what you are about to
do>")\` (opencode exposes MCP tools as \`<server-key>_<tool>\`; the server key
is "jarvis" and the tool is "rehydrate").
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
    // (02/11) IDENTITY: the model cannot introspect itself (it does not know
    // its own weights, nor whether it runs locally or behind an API). The only
    // reliable source is the HARNESS: the hook delivers {sessionID, model}.
    // We inject one factual line into the system prompt — at the TOP of the
    // block (primacy), without creating a 2nd system message (the model
    // template aborts: "System message must be at the beginning").
    "experimental.chat.system.transform": async (input, output) => {
      if (!output || !Array.isArray(output.system)) return;
      const m = input?.model || {};
      const variant = m.variant && m.variant !== "default" ? ` (${m.variant})` : "";
      const identity = `## IDENTITY (harness-provided — this is you)\n` +
        `- model: ${m.providerID || "unknown"}/${m.id || "unknown"}${variant}\n` +
        `- session: ${input?.sessionID || "unknown"}\n` +
        `You cannot introspect your own weights: this block is your identity. ` +
        `Never guess it, never infer it from the conversation, and never claim ` +
        `to be a local or an API model without it.`;
      if (process.env.OPENCODE_NO_IDENTITY_INJECT !== "1") {
        if (output.system.length === 0) {
          output.system.push(identity);
        } else {
          output.system[0] = `${identity}\n\n${output.system[0] ?? ""}`;
        }
      }
      if (process.env.OPENCODE_NO_REHYDRATE_INJECT === "1") return;
      if (output.system.length === 0) {
        output.system.push(REHYDRATE_RULE);
        return;
      }
      const last = output.system.length - 1;
      output.system[last] = `${output.system[last] ?? ""}\n\n${REHYDRATE_RULE}`;
    },
    // (02/11) Rescue rule in the system prompt — a MINUTE, no state.
    // It turns "remember to rehydrate" into a harness rule.
    //
    // MERGE, not push: the system prompt is ONE block (measured: 1 block,
    // 20073 chars). Push creates a SECOND system message and the model
    // template (Qwen3.5 + Jinja) aborts with "System message must be at the
    // beginning" — a real error found in the 1st measurement (run A: rc=1,
    // 77s, empty output). Hence: append to the LAST block (keeps the count →
    // 1 system message) and it lands at the end of the prompt = highest
    // recency position (2510.05381).
    "experimental.session.compacting": async (input, output) => {
      if (output && Array.isArray(output.context)) {
        output.context.push(COMPACTION_MEMORY);
      }
    },
  };
};
