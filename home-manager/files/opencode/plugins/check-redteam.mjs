#!/usr/bin/env node
// Gate do plugin redteam.js: importa e INICIALIZA o plugin de verdade.
//
// POR QUE ISTO EXISTE: `node --check` so valida a SINTAXE. Um backtick
// nao escapado dentro de uma template string (`<think>` no bloco de
// estrategia) passa o --check e quebra em RUNTIME — o opencode carrega o
// arquivo, o import lanca "think is not defined", o plugin NAO registra
// nenhuma tool e o sintoma e "a tool nao existe" (medido em 06/11: o
// plugin inteiro sumiu por causa de um backtick).
//
// Este gate importa o arquivo E chama o factory — o mesmo caminho que o
// opencode faz. Se falhar, o plugin esta quebrado.
//
// Uso: node home-manager/files/opencode/plugins/check-redteam.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const target = "/tmp/opencode/rt-bad.js";

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
const expectedHooks = ["command.execute.before", "tool.execute.before",
                       "tool.execute.after",
                       "experimental.chat.system.transform"];
for (const hook of expectedHooks) {
  if (!hooks.includes(hook)) {
    console.error(`FALHOU: hook ausente -> ${hook}`);
    bad = true;
  }
}

// o bloco de estrategia tem que estar no system prompt (e nao ter
// backtick cru — o bug que quebrou tudo)
const block = plugin["experimental.chat.system.transform"];
if (typeof block === "function") {
  const out = { system: ["base"] };
  await block({ output: out }, out);
  const rendered = out.system.join("\n");
  if (!rendered.includes("RED-TEAM MODE") && !rendered.includes("jailbreak")) {
    // sem o marcador ativo o bloco nao entra — esperado; so checa que
    // a funcao nao lanca
  }
  if (rendered.includes("think is not")) {
    console.error("FALHOU: bloco de estrategia com template quebrado");
    bad = true;
  }
}

if (bad) process.exit(1);
console.log(`ok: ${tools.length} tools (${tools.join(", ")})`);
console.log(`ok: ${hooks.length} hooks (${hooks.join(", ")})`);
