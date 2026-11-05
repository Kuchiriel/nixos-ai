import type { Plugin } from "@opencode-ai/plugin"

// RTK OpenCode plugin — rewrites commands to use rtk for token savings.
// Requires: rtk >= 0.23.0 in PATH.
//
// 2026-10-08 (IMP-015 follow-up): o rewrite indiscriminado confundia modelos
// fracos (o agente pedia `python3 -m pytest`, recebia `rtk pytest` que roda o
// python do PATH sem pytest, e travava num erro que não era do código dele).
// Regras novas:
//   1. `norrtk` na linha de comando = passthrough garantido (opt-out por
//      chamada; o marcador é removido antes de executar).
//   2. Comandos com path explícito de venv/binário (./.venv, /nix/store,
//      python -m, ./script) NÃO são reescritos — o ambiente é do agente.
//   3. Falha do `rtk rewrite` = passthrough silencioso (como antes).
//
// A lógica de rewrite continua no binário rtk (registry.rs); este arquivo só
// filtra quando NÃO aplicar.

const NO_RTK_MARKERS = ["norrtk", "--no-rtk"]
// Prefixos/paths que indicam ambiente explícito do agente — rtk não toca.
const EXPLICIT_ENV_PATTERNS = [
  /^\.\//,             // ./.venv/bin/pytest, ./script.py
  /^\//,               // /abs/path/bin
  /\bpython3?\s+-m\b/, // python -m pytest (ambiente do agente importa)
  /\buv\s+run\b/,
  /\bnix\s+develop\b/,
  /\bnix-shell\b/,
]

export const RtkOpenCodePlugin: Plugin = async ({ $ }) => {
  try {
    await $`which rtk`.quiet()
  } catch {
    console.warn("[rtk] rtk binary not found in PATH — plugin disabled")
    return {}
  }

  return {
    "tool.execute.before": async (input, output) => {
      const tool = String(input?.tool ?? "").toLowerCase()
      if (tool !== "bash" && tool !== "shell") return
      const args = output?.args
      if (!args || typeof args !== "object") return

      const command = (args as Record<string, unknown>).command
      if (typeof command !== "string" || !command) return

      // 1. Opt-out explícito por chamada: remove o marcador e executa cru.
      for (const marker of NO_RTK_MARKERS) {
        if (command.includes(marker)) {
          ;(args as Record<string, unknown>).command = command
            .split(marker).join("").replace(/\s{2,}/g, " ").trim()
          return
        }
      }

      // 2. Ambiente explícito do agente: não reescrever.
      for (const pattern of EXPLICIT_ENV_PATTERNS) {
        if (pattern.test(command)) return
      }

      try {
        const result = await $`rtk rewrite ${command}`.quiet().nothrow()
        const rewritten = String(result.stdout).trim()
        if (rewritten && rewritten !== command) {
          ;(args as Record<string, unknown>).command = rewritten
        }
      } catch {
        // rtk rewrite failed — pass through unchanged
      }
    },
  }
}
