// Memory + safety plugin — declarative via home-manager (12/10).
// Plain .js (not .ts) on purpose: `node --check` validates it with zero
// toolchain; opencode loads .js and .ts identically from plugins/.
//
// Verified APIs in this opencode version (mirrors rtk.ts, same loader):
//   - "tool.execute.before" with MUTABLE output.args (rtk rewrites
//     args.command through it — the deny below uses the same channel)
//   - "experimental.session.compacting" with output.context.push (docs)
// NOT implemented: session.created/idle auto-recall — this version has
// no verified context-injection API (event hooks are side-effect only).
// The recall half stays an AGENTS.md mandate (opencode loads AGENTS.md
// automatically); this plugin covers compaction survival + guardrails.

const ROOT_DELETE =
  /(^|[;&|\s])rm\s+[^;&|]*-[a-z]*r[a-z]*f[^;&|]*\s+(\/(\s|$|;)|~(\s|$|;))/;

const COMPACTION_MEMORY = `## Memory protocol (auto-injected pre-compaction)
Recall BEFORE acting in the new session: jarvis_recall top_k=5 on the
active topic. At task end / topic switch: jarvis_remember (fact, event,
decision, error). Routing — decision>1 session: memory + note; resume
pointers: vault handoff note (git-synced); ground truth: VERDADES.md +
checker run; transient: chat only, never stored; secrets: names only.
Validate live state on wake: model tiers, service PIDs vs git log,
/run/current-system vs booted generation (a reboot may have reverted
a test-activated switch).`;

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
    "experimental.session.compacting": async (input, output) => {
      if (output && Array.isArray(output.context)) {
        output.context.push(COMPACTION_MEMORY);
      }
    },
  };
};
