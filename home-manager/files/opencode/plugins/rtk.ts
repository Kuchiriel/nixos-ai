// RTK OpenCode plugin — rewrites commands to use rtk for token savings.
// DUAL-MODE (2026-11-07): opencode 1.x (>=1.18.29) executes server() (V1
// object form); opencode v2 reads the default export's id+setup(). Same
// behavior in both runtimes; the only delta is hook registration.
// Requires: rtk >= 0.23.0 in PATH.
//
// 2026-10-08 (IMP-015 follow-up): o rewrite indiscriminado confundia modelos
// fracos (o agente pedia `python3 -m pytest`, recebia `rtk pytest` que roda o
// python do PATH sem pytest, e travava num erro que não era do código dele).
// Regras: norrtk = opt-out; paths explícitos (./, /, python -m, nix develop)
// não são reescritos; falha do rtk = passthrough silencioso.

import { execFileSync, spawnSync } from "node:child_process";

const NO_RTK_MARKERS = ["norrtk", "--no-rtk"];
// Prefixos/paths que indicam ambiente explícito do agente — rtk não toca.
const EXPLICIT_ENV_PATTERNS = [
  /^\.\//,             // ./.venv/bin/pytest, ./script.py
  /^\//,               // /abs/path/bin
  /\bpython3?\s+-m\b/, // python -m pytest (ambiente do agente importa)
  /\buv\s+run\b/,
  /\bnix\s+develop\b/,
  /\bnix-shell\b/,
];

// rtk rewrite exits 3 when it rewrote the command (non-fatal — the rewritten
// string is on stdout). Read stdout regardless of the exit code; treat a
// throw/empty output as "no rewrite".
const runRewrite = (command) => {
  const res = spawnSync("rtk", ["rewrite", command], {
    encoding: "utf8",
    stdio: ["pipe", "pipe", "pipe"],
  });
  return String(res.stdout ?? "");
};

function rewriteCommand(command) {
  for (const marker of NO_RTK_MARKERS) {
    if (command.includes(marker)) {
      return command.split(marker).join("").replace(/\s{2,}/g, " ").trim();
    }
  }
  for (const pattern of EXPLICIT_ENV_PATTERNS) {
    if (pattern.test(command)) return command;
  }
  try {
    const rewritten = runRewrite(command).trim();
    if (rewritten && rewritten !== command) return rewritten;
  } catch {
    // rtk rewrite failed — passthrough
  }
  return command;
}

function hasRtk() {
  try {
    execFileSync("which", ["rtk"], { stdio: "ignore" });
    return true;
  } catch {
    console.warn("[rtk] rtk binary not found in PATH — plugin disabled");
    return false;
  }
}

const bashLike = (t) => {
  const n = String(t ?? "").toLowerCase();
  return n === "bash" || n === "shell";
};

// shared hook body (opencode 1 tool.execute.before / v2 tool.hook execute.before)
const applyRewrite = (tool, args) => {
  if (!bashLike(tool)) return;
  if (!args || typeof args !== "object") return;
  const record = args;
  const command = record.command;
  if (typeof command !== "string" || !command) return;
  record.command = rewriteCommand(command);
};

export default {
  id: "rtk",
  // opencode v2: registers the hook on the tool domain.
  async setup(ctx) {
    if (!hasRtk()) return;
    await ctx.tool.hook("execute.before", (event) => {
      applyRewrite(event.tool, event.input);
    });
  },
  // opencode 1: the object the loader (>=1.18.29) calls to get its hooks.
  async server() {
    if (!hasRtk()) return {};
    return {
      "tool.execute.before": async (
        input,
        output,
      ) => {
        applyRewrite(input?.tool, output?.args);
      },
    };
  },
};
