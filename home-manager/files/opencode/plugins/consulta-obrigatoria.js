// consulta-obrigatoria.js — force consulta de MCP antes de ação de decisão.
//
// PROBLEMA: o memory.js injeta as regras de rehydrate/recall/rag_search no
// system prompt, mas e tudo convençao. O agente pode rodar um comando
// destrutivo sem nunca ter consultado o que ja existe.
//
// SOLUCAO: hook em tool.execute.before. Antes de qualquer ação que muda
// estado (bash destrutivo, edição de arquivo, coord_post, spawn), o plugin
// verifica se o agente chamou pelo menos um MCP de consulta
// (rehydrate, rag_search, recall, lessons) na sessão atual. Se nao, a
// ação é barrada com um erro claro indicando qual MCP chamar primeiro.
//
// BYPASS: variável OPENCODE_NO_CONSULT_GUARD=1 desativa; comandos read-only
// (grep, cat, ls, git status/diff/log sem --) não são barrados.
//
// AÇÕES BARRADAS sem consulta prévia:
//   - bash com rm/mv/dd/> / redirect de escrita / nixos-rebuild / docker
//     system prune / pip install / npm install -g / systemctl start|stop
//   - str_replace / write_file (edição de arquivo)
//   - jarvis_coord_post (publicar claim no bus)
//   - jarvis_agent_spawn / agent-wake (criar ou acordar agente)
//
// Rastreamento: chama de jarvis_* de consulta marca a sessão como "consultada".
// Reset a cada nova sessão (o hook de contexto roda a cada turno).

import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const DISABLE = process.env.OPENCODE_NO_CONSULT_GUARD === "1";

// Comandos que nunca são barrados (leitura pura).
const READ_ONLY_RE = /^\s*(echo|printf|cat|head|tail|less|more|grep|rg|awk|sed|cut|sort|uniq|wc|find|ls|pwd|whoami|date|hostname|uptime|free|df|du|ps|ss|netstat|git\s+(status|diff|log|show|ls-files|branch|remote|config\s+--get|list|stash\s+list|rev-parse|diff--stat)\b|nix\s+(flake\s+check|search|eval|build\b.*--no-link|ls|registry|why-depends)\b)/i;

// Comandos de escrita/estado que exigem consulta prévia.
const STATE_CHANGE_RE = /^\s*(rm\s|mv\s|cp\s|>\s|>>\s|dd\s|nixos-rebuild|docker\s+system\s+prune|pip\s+install|npm\s+install\s+-g|curl\s.*-X\s+(POST|PUT|DELETE)|systemctl\s+(start|stop|restart|enable|disable)|reboot|shutdown)/i;

// Marcador de sessao consultada. Chave = sessionID.
const CONSULTED = new Set();

// MCP de consulta (qualquer um deles satisface o requisito).
const CONSULT_MCP_RE = /^(jarvis_)?(rehydrate|rag_search|recall|lessons)$/;

// Ações MCP que exigem consulta prévia.
const ACTION_MCP_RE = /^(jarvis_)?(coord_post|agent_spawn|agent_wake|str_replace|write_file)$/;

function sessionKey(ctx) {
  try { return String(ctx?.sessionID ?? ctx?.session?.id ?? ""); } catch { return ""; }
}

function markConsulted(toolName, sid) {
  if (CONSULT_MCP_RE.test(String(toolName ?? ""))) {
    if (sid) CONSULTED.add(sid);
    else CONSULTED.add("global"); // fallback: alguma consulta ocorreu
  }
}

function isConsulted(sid) {
  return CONSULTED.has(sid || "global");
}

function isReadOnlyCommand(command) {
  return READ_ONLY_RE.test(command);
}

function isStateChangeCommand(command) {
  return STATE_CHANGE_RE.test(command);
}

function consultBlockMessage(sid) {
  const label = sid && sid !== "global" ? `sessão ${sid.slice(0, 8)}` : "esta sessão";
  return `CONSULTA OBRIGATÓRIA não cumprida em ${label}.\n` +
    `Antes desta ação, chame pelo menos um MCP de consulta:\n` +
    `  • jarvis_rehydrate(task="...") — início de sessão / problema repetido\n` +
    `  • jarvis_recall(query="...") — decisão/fato/erro do passado\n` +
    `  • jarvis_rag_search(query="...", collection="code") — código/doc onde vive X\n` +
    `  • jarvis_lessons(query="...") — armadilha já registrada para este erro\n` +
    `Não rode cego. Leia o que já existe antes de agir.\n` +
    `Bypass: OPENCODE_NO_CONSULT_GUARD=1 (só se souber o que está fazendo).`;
}

// ── opencode v2 ──
export default {
  id: "consulta-obrigatoria",
  async setup(ctx) {
    if (DISABLE) return;

    // 1) Rastrear chamadas de consulta para marcar a sessão.
    await ctx.tool.hook("tool.call", async (event) => {
      const tool = String(event?.tool ?? event?.name ?? "");
      const sid = sessionKey(ctx);
      markConsulted(tool, sid);
    });

    // 2) Bloquear ações de estado sem consulta prévia.
    await ctx.tool.hook("execute.before", (event) => {
      const tool = String(event?.tool ?? "").toLowerCase();
      const args = event?.input ?? {};
      const sid = sessionKey(ctx);

      // Chamada de MCP de ação?
      if (ACTION_MCP_RE.test(tool)) {
        if (!isConsulted(sid)) {
          event.blocked = true;
          event.output = { blocked: true, error: consultBlockMessage(sid) };
          return;
        }
      }

      // Comando bash de mudança de estado?
      if ((tool === "bash" || tool === "shell") && typeof args.command === "string") {
        const cmd = args.command;
        if (isReadOnlyCommand(cmd)) return;
        if (isStateChangeCommand(cmd)) {
          if (!isConsulted(sid)) {
            event.blocked = true;
            event.output = { blocked: true, error: consultBlockMessage(sid) };
            return;
          }
        }
      }
    });

    // 3) Lembrete no system prompt quando ainda não houve consulta.
    await ctx.session.hook("context", (event) => {
      const sid = sessionKey(event);
      if (!isConsulted(sid)) {
        event.system.push({
          type: "text",
          text: "## ⚠ Consulta obrigatória pendente\n" +
            "Você ainda não chamou nenhum MCP de consulta " +
            "(rehydrate/recall/rag_search/lessons) nesta sessão. " +
            "Antes de qualquer ação de decisão, consulte o que já existe.\n",
        });
      }
    });
  },
};
