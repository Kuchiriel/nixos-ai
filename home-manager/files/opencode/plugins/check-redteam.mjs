#!/usr/bin/env node
// Gate dos plugins redteam: importa e INICIALIZA o plugin do SERVIDOR,
// importa o plugin do TUI e testa a logica do comando /jailbreak num
// arquivo de estado temporario.
//
// POR QUE ISTO EXISTE: `node --check` so valida a SINTAXE. Um backtick
// nao escapado dentro de uma template string (`<think>` no bloco de
// estrategia) passa o --check e so quebra em RUNTIME — o opencode carrega
// o arquivo, o import lanca "think is not defined", o plugin NAO registra
// nenhuma tool e o sintoma e "a tool nao existe" (medido em 06/11: o
// plugin inteiro sumiu por causa de um backtick).
//
// Este gate importa os arquivos E chama o factory — o mesmo caminho que o
// opencode faz. Se falhar, o plugin esta quebrado.
//
// Uso: node home-manager/files/opencode/plugins/check-redteam.mjs
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const target = join(here, "redteam.js");
const tuiTarget = join(here, "..", "tui-plugins", "redteam-tui.js");

// Estado ISOLADO antes de qualquer import: os dois plugins leem o path do
// estado no load do modulo (OPENCODE_REDTEAM_STATE). Sem isto o gate
// escreveria no estado real do dono.
const tmp = mkdtempSync(join(tmpdir(), "redteam-gate-"));
process.env.OPENCODE_REDTEAM_STATE = join(tmp, "redteam.json");
// O audit tambem e isolado: o gate nao escreve no log real do dono.
process.env.OPENCODE_REDTEAM_AUDIT = join(tmp, "redteam-audit.log");

// Backticks balanceados: um `<think>` cru dentro de uma template string
// passa o `node --check` (que so valida sintaxe) e so quebra em RUNTIME,
// tirando TODAS as tools do plugin (medido 2x em 06/11). O import abaixo
// pegaria, mas o erro aparece tarde e com sintoma enganoso — melhor
// falhar aqui, com a mensagem certa.
const src = readFileSync(target, "utf8");
let ticks = 0;
for (let i = 0; i < src.length; i++) {
  if (src[i] === "`" && src[i - 1] !== "\\") ticks++;
}
if (ticks % 2 !== 0) {
  console.error(`FALHOU: ${ticks} backticks nao escapados (deve ser par) — `
    + "um backtick cru dentro de template string quebra o plugin em runtime");
  process.exit(1);
}

let mod;
try {
  mod = await import(pathToFileURL(target).href + "?t=" + Date.now());
} catch (e) {
  console.error(`FALHOU no import: ${e?.message ?? e}`);
  process.exit(1);
}

const factory = mod.RedTeamOpenCodePlugin;
if (typeof factory !== "function") {
  console.error("FALHOU: RedTeamOpenCodePlugin nao e uma funcao exportada");
  process.exit(1);
}

let plugin;
try {
  plugin = await factory({});
} catch (e) {
  console.error(`FALHOU na init: ${e?.message ?? e}`);
  process.exit(1);
}

const expected = ["redteam_matrix", "redteam_payload", "redteam_probe",
                  "redteam_crescendo"];
const tools = Object.keys(plugin.tool || {});
const hooks = Object.keys(plugin).filter((k) => typeof plugin[k] === "function");

let bad = false;
for (const name of expected) {
  if (!tools.includes(name)) {
    console.error(`FALHOU: tool ausente -> ${name}`);
    bad = true;
  }
}
// O comando /jailbreak saiu do servidor: a rota de command do servidor
// sempre chama o modelo depois do hook (medido 07/11). O comando e
// resolvido no TUI (tui-plugins/redteam-tui.js).
const expectedHooks = ["chat.message", "tool.execute.before",
                       "tool.execute.after",
                       "experimental.chat.system.transform"];
for (const hook of expectedHooks) {
  if (!hooks.includes(hook)) {
    console.error(`FALHOU: hook ausente -> ${hook}`);
    bad = true;
  }
}
if (hooks.includes("command.execute.before")) {
  console.error("FALHOU: command.execute.before voltou — o comando do TUI "
    + "precisa ser local (o command() do servidor sempre chama o modelo)");
  bad = true;
}

// o bloco de estrategia tem que estar no system prompt (e nao ter
// backtick cru — o bug que quebrou tudo)
const block = plugin["experimental.chat.system.transform"];
if (typeof block === "function") {
  const out = { system: ["base"] };
  await block({ output: out }, out);
  const rendered = out.system.join("\n");
  if (!rendered.includes("RED-TEAM MODE") && !rendered.includes("jailbreak")) {
    // sem o marcador ativo o bloco nao entra — esperado; so checa que a
    // funcao nao lanca
  }
  if (rendered.includes("think is not")) {
    console.error("FALHOU: bloco de estrategia com template quebrado");
    bad = true;
  }
}

// ── o plugin do TUI ─────────────────────────────────────────────────────
// O arquivo do TUI nao pode ficar em ~/.config/opencode/plugins/: o
// servidor auto-descobre {plugin,plugins}/*.{ts,js} e REJEITA um plugin
// so-de-TUI (readV1Plugin: "must default export an object with server()").
for (const name of readdirSync(here)) {
  if (/^redteam-tui\./.test(name)) {
    console.error(`FALHOU: ${name} esta no diretorio de plugins do servidor — `
      + "o plugin do TUI tem que ficar em ../tui-plugins/");
    bad = true;
  }
}

if (!existsSync(tuiTarget)) {
  console.error(`FALHOU: plugin do TUI ausente -> ${tuiTarget}`);
  rmSync(tmp, { recursive: true, force: true });
  process.exit(1);
}

let tui;
try {
  tui = await import(pathToFileURL(tuiTarget).href + "?t=" + Date.now());
} catch (e) {
  console.error(`FALHOU no import do plugin do TUI: ${e?.message ?? e}`);
  rmSync(tmp, { recursive: true, force: true });
  process.exit(1);
}

const def = tui.default;
if (!def || typeof def.tui !== "function" || typeof def.id !== "string") {
  console.error("FALHOU: o plugin do TUI precisa default export { id, tui }");
  bad = true;
}
if (typeof tui.handleJailbreakCommand !== "function") {
  console.error("FALHOU: handleJailbreakCommand nao exportado pelo plugin do TUI");
  bad = true;
}
if (typeof tui.parseJailbreak !== "function") {
  console.error("FALHOU: parseJailbreak nao exportado pelo plugin do TUI");
  bad = true;
}

if (!bad) {
  const run = (args) => tui.handleJailbreakCommand(args);
  const readState = () => JSON.parse(readFileSync(process.env.OPENCODE_REDTEAM_STATE, "utf8"));

  const check = (cond, message) => {
    if (!cond) {
      console.error("FALHOU: " + message);
      bad = true;
    }
  };

  check(tui.parseJailbreak("/jailbreak on") === "on",
    "parseJailbreak nao extrai os args");
  check(tui.parseJailbreak("/jailbreak") === "",
    "parseJailbreak sem args");
  check(tui.parseJailbreak("como uso /jailbreak?") === null,
    "parseJailbreak sequestrou uma frase normal");
  check(tui.parseJailbreak("oi") === null,
    "parseJailbreak aceitou texto que nao e comando");

  run("term add alvo decoyUm decoyDois");
  let st = readState();
  check(st.deception.length === 1 && st.deception[0].termo === "alvo",
    "term add nao gravou o termo");
  check(Array.isArray(st.deception[0].decoys) && st.deception[0].decoys.length === 2,
    "term add nao gravou as N decoys");
  check(run("term list").includes("alvo"),
    "term list nao mostra o termo");

  run("term rm alvo");
  st = readState();
  check(st.deception.length === 0, "term rm nao removeu");

  run("on");
  st = readState();
  check(st.enabled === true, "on nao ligou o modo");

  run("pair palavraReal palavraDecoy");
  st = readState();
  check(st.trigger === "palavraReal" && st.decoy === "palavraDecoy",
    "pair nao trocou o par");

  run("reset");
  st = readState();
  check(st.enabled === false && !st.trigger && !st.decoy && st.deception.length === 0,
    "reset nao limpou o estado");

  // a escrita e atomica: nao pode sobrar arquivo .tmp no diretorio
  const leftovers = readdirSync(tmp).filter((f) => f.includes(".tmp-"));
  check(leftovers.length === 0,
    "a escrita do estado deixou arquivo temporario: " + leftovers.join(", "));
}

// ── o hook do servidor: sanitizacao + rede de seguranca do comando ──────
if (!bad && typeof plugin["chat.message"] === "function") {
  const check = (cond, message) => {
    if (!cond) {
      console.error("FALHOU: " + message);
      bad = true;
    }
  };

  // (a) o comando /jailbreak nunca deve chegar cru no modelo
  const cmdOut = { parts: [{ type: "text", text: "/jailbreak on" }] };
  await plugin["chat.message"]({}, cmdOut);
  check(!cmdOut.parts[0].text.includes("/jailbreak on"),
    "o comando /jailbreak passou cru para o modelo");
  check(cmdOut.parts[0].text.includes("LOCAL do TUI"),
    "a rede de seguranca do comando nao avisou que o comando e local do TUI");

  // (b) a sanitizacao de deception: o termo real sai, a 1a decoy entra
  const stateFile = process.env.OPENCODE_REDTEAM_STATE;
  const raw = JSON.parse(readFileSync(stateFile, "utf8"));
  raw.deception = [{ termo: "termoSecreto", decoys: ["termo. Secreto", "termoSecreto2"] }];
  raw.enabled = true;
  raw.trigger = "gatilhoReal";
  raw.decoy = "gatilhoDecoy";
  writeFileSync(stateFile, JSON.stringify(raw, null, 2), "utf8");

  const sanOut = { parts: [{ type: "text", text: "use termoSecreto e gatilhoReal" }] };
  await plugin["chat.message"]({}, sanOut);
  const text = sanOut.parts[0].text;
  check(!text.includes("termoSecreto"),
    "a sanitizacao de deception deixou o termo real no prompt");
  check(text.includes("termo. Secreto"),
    "a sanitizacao de deception nao usou a 1a decoy");
  check(!text.includes("gatilhoReal"),
    "a sanitizacao do par trigger/decoy deixou o trigger no prompt");
  check(text.includes("gatilhoDecoy"),
    "a sanitizacao do par nao usou o decoy");

  // (c) a direcao IN da lista de deception: a decoy volta a ser o termo
  // real nos args da tool — e isso tem que FICAR NO AUDIT LOG (medido
  // 07/11: so o par era auditado, a lista nao).
  const toolOut = { args: { filePath: "/tmp/x", content: "termo. Secreto" } };
  await plugin["tool.execute.before"]({ tool: "write" }, toolOut);
  check(toolOut.args.content === "termoSecreto",
    "a recomposicao da lista de deception nao devolveu o termo real");
  const auditFile = process.env.OPENCODE_REDTEAM_AUDIT
    || join(homedir(), ".local/state/opencode/redteam-audit.log");
  const audit = existsSync(auditFile) ? readFileSync(auditFile, "utf8") : "";
  check(audit.includes("decoy->termo"),
    "a recomposicao da lista de deception nao foi auditada");

  // (d) a rede de seguranca tem que mascarar os args da tool-call do
  // assistant: o plugin reescreve os args in-place para o termo real e o
  // modelo ve a propria tool call (MEDIDO 07/11: o modelo respondia
  // "conteudo segredo" — a palavra real vazava de volta).
  const msgs = [{
    parts: [
      { type: "text", text: "gravando" },
      {
        type: "tool",
        tool: "write",
        state: {
          status: "completed",
          input: { filePath: "/tmp/x", content: "termo. Secreto" },
          output: "ok",
        },
      },
    ],
  }];
  await plugin["experimental.chat.messages.transform"]({}, { messages: msgs });
  const callArgs = msgs[0].parts[1].state.input;
  check(!JSON.stringify(callArgs).includes("termoSecreto"),
    "a rede de seguranca deixou o termo real nos args da tool-call "
    + "(o modelo aprende a palavra pela propria tool call)");
  check(JSON.stringify(callArgs).includes("termo. Secreto"),
    "a rede de seguranca nao colocou a decoy nos args da tool-call");
}
// Um api falso reproduz o que o TUI oferece: registerLayer (slash command),
// intercept (tecla), renderer.currentFocusedEditor (o texto do prompt) e
// ui.dialog (a resposta local). O teste prova que o Enter com
// "/jailbreak ..." e CONSUMIDO (o prompt nao recebe a tecla -> nenhuma
// mensagem, nenhum turno de modelo) e que a resposta sai num dialogo.
if (!bad && typeof tui.tui === "function") {
  const check = (cond, message) => {
    if (!cond) {
      console.error("FALHOU: " + message);
      bad = true;
    }
  };

  let layer = null;
  let hook = null;
  let consumed = 0;
  let cleared = null;
  let dialog = null;
  const editor = {
    plainText: "/jailbreak term add alvo decoyUm",
    setText(value) {
      cleared = value;
    },
  };
  const fakeApi = {
    keymap: {
      registerLayer(value) {
        layer = value;
        return () => {};
      },
      intercept(name, fn) {
        hook = fn;
        return () => {};
      },
    },
    renderer: {
      get currentFocusedEditor() {
        return editor;
      },
    },
    ui: {
      dialog: {
        open: false,
        replace(render) {
          dialog = render();
        },
        clear() {},
      },
      DialogAlert: (props) => props,
      DialogPrompt: (props) => props,
    },
  };

  await tui.tui(fakeApi);

  check(!!layer, "o plugin do TUI nao registrou nenhum layer de comandos");
  const cmd = layer && layer.commands && layer.commands[0];
  check(cmd && cmd.slashName === "jailbreak",
    "o slash command nao foi registrado com slashName=jailbreak");
  check(cmd && cmd.namespace === "palette",
    "o slash command nao foi registrado no namespace palette");
  check(typeof hook === "function", "o interceptor de tecla nao foi registrado");

  if (typeof hook === "function") {
    hook({
      event: { name: "return" },
      consume() {
        consumed++;
      },
    });
    check(consumed === 1, "o Enter nao foi consumido (o prompt ainda receberia a tecla)");
    check(cleared === "", "o prompt nao foi limpo depois do comando");
    check(!!dialog && typeof dialog.message === "string",
      "a resposta do comando nao foi entregue no dialogo local");
    check(dialog && dialog.message.includes("alvo"),
      "a resposta do comando nao traz o termo adicionado");
  }

  // uma tecla que nao e o comando nao pode ser consumida
  consumed = 0;
  editor.plainText = "uma frase normal";
  if (typeof hook === "function") {
    hook({ event: { name: "return" }, consume() { consumed++; } });
    check(consumed === 0, "o interceptor sequestrou uma frase que nao e comando");
  }
}

rmSync(tmp, { recursive: true, force: true });

if (bad) process.exit(1);
console.log(`ok: ${tools.length} tools (${tools.join(", ")})`);
console.log(`ok: ${hooks.length} hooks (${hooks.join(", ")})`);
console.log("ok: plugin do TUI importado e logica do /jailbreak testada");
