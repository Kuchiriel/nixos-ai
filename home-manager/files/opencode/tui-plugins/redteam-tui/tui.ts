// Plugin TUI do red-team (v2): o slash command /jailbreak roda LOCAL,
// sem passar pelo modelo.
//
// Replica o v1 (keymap.intercept) pela API NATIVA do v2 TUI: um comando
// de slash registrado via context.keymap.layer roda no processo do TUI —
// o texto nunca vira mensagem, nao ha turno de modelo, nao ha token gasto.
// Estado no MESMO arquivo do plugin do servidor
// (~/.local/state/opencode/redteam.json): o contrato entre os dois processos.
//
// v2: importado como PACKAGE (ver package.json + cli.json): o servidor NAO
// auto-descobre este arquivo (fica fora de plugins/) — mesma regra do v1.
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

const STATE =
  process.env.OPENCODE_REDTEAM_STATE ||
  join(homedir(), ".local/state/opencode/redteam.json");

const DEFAULT_STATE = {
  enabled: false,
  trigger: "",
  decoy: "",
  note: "",
  deception: [],
};

const HELP = [
  "Uso: /jailbreak <comando>",
  "  on                    liga o modo (transliteracao + bloco de estrategia)",
  "  off                   desliga",
  "  status                mostra o estado",
  "  pair <t> <d>          define o par trigger/decoy",
  "  term add <t> <d...>   termo na lista de deception (N decoys; a 1a e a forma vista pelo modelo)",
  "  term auto <t> [n]     gera n decoys do termo e joga na lista (padrao 4)",
  "  term rm <t>           remove o termo da lista",
  "  term list             lista os termos e as decoys",
  "  reset                 limpa tudo (off, sem par, lista vazia)",
].join("\n");

// Metodos legacy (comando antigo: /jailbreak deception add <termo> <metodo>).
const DECEPTION_METHODS = {
  split: {
    label: "split (segmentos separados por '. ')",
    encode: (s) => (s.includes(".") ? s.split(".").join(". ") : s),
  },
  leet: {
    label: "leet (a/e/o/i/s -> 4/3/0/1/5)",
    encode: (s) => s.replace(/a/g, "4").replace(/e/g, "3").replace(/o/g, "0")
      .replace(/i/g, "1").replace(/s/g, "5"),
  },
  b64: {
    label: "base64 (o termo inteiro codificado)",
    encode: (s) => Buffer.from(s, "utf8").toString("base64"),
  },
  xor: {
    label: "xor hex (chave JARVISCORE)",
    encode: (s) => {
      const key = "JARVISCORE";
      const bytes = Buffer.from(s, "utf8");
      const out = Buffer.alloc(bytes.length);
      for (let i = 0; i < bytes.length; i++) {
        out[i] = bytes[i] ^ key.charCodeAt(i % key.length);
      }
      return out.toString("hex");
    },
  },
  spaced: {
    label: "spaced (letra por letra)",
    encode: (s) => s.split("").join(" "),
  },
  reversed: {
    label: "reversed (a palavra ao contrario)",
    encode: (s) => s.split("").reverse().join(""),
  },
};

function loadState() {
  try {
    if (!existsSync(STATE)) return { ...DEFAULT_STATE };
    const raw = JSON.parse(readFileSync(STATE, "utf8"));
    return { ...DEFAULT_STATE, ...raw };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

function saveState(state) {
  mkdirSync(dirname(STATE), { recursive: true });
  // Escrita ATOMICA (tmp + rename): o servidor le esse arquivo a cada
  // hook. Um writeFileSync direto pode ser lido pela metade — o JSON
  // quebrado faz o loadState() cair no DEFAULT_STATE e o modo parece
  // "desligado" sozinho, sem aviso.
  const tmp = STATE + ".tmp-" + process.pid;
  writeFileSync(tmp, JSON.stringify(state, null, 2) + "\n", "utf8");
  renameSync(tmp, STATE);
}

// Quebra os args RESPITANDO aspas: `pair "Meu Termo" decoy` tem que
// chegar como 2 args (split por espaco colava a aspa no valor).
function splitArgs(text) {
  const out = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(String(text || "")))) {
    out.push(m[1] ?? m[2] ?? m[3]);
  }
  return out;
}

// Normaliza a lista para {termo, decoys[]}. Aceita o formato antigo
// (string) e o intermediario ({termo, metodo}).
function termEntries(state) {
  const raw = state.deception || [];
  return raw
    .map((x) => {
      if (typeof x === "string") {
        return { termo: x, decoys: [DECEPTION_METHODS.split.encode(x)] };
      }
      if (x && Array.isArray(x.decoys)) {
        return { termo: x.termo || "", decoys: x.decoys.filter(Boolean) };
      }
      if (x && x.termo) {
        const m = DECEPTION_METHODS[x.metodo] || DECEPTION_METHODS.split;
        return { termo: x.termo, decoys: [m.encode(x.termo)] };
      }
      return null;
    })
    .filter((x) => x && x.termo && x.decoys.length);
}

function entryTerm(entry) {
  if (!entry) return "";
  return typeof entry === "string" ? entry : entry.termo || "";
}

// Termo/decoy curtos quebram a transliteracao: a troca e por substring
// (medido 07/11: decoy "c" + termo "a." transformavam "echo" em "ea.ho"
// e "projects" em "projea.ts" — TUDO que contem a letra). O par e a
// lista so sao confiaveis com pedacos de 3+ chars.
const MIN_LEN = 3;


// Gera as decoys de um termo (os metodos do DECEPTION_METHODS).
// A 1a e a forma que o MODELO ve; as outras sao as alternativas que
// voltam ao termo real quando o modelo devolve qualquer uma delas.
// O dono: "era pra fazer lista de decoy, um so sim ajuda".
function gerarDecoys(termo, n = 4) {
  const out = [];
  for (const [nome, m] of Object.entries(DECEPTION_METHODS)) {
    let d;
    try {
      d = m.encode(termo);
    } catch {
      continue;
    }
    if (!d || d === termo) continue;
    if (termo.includes(d)) continue;   // fatia do termo: quebra a volta
    if (d.length < MIN_LEN) continue; // curta: reescreve o mundo
    if (!out.includes(d)) out.push(d);
  }
  return out.slice(0, Math.max(1, Math.min(8, n)));
}

export function handleJailbreakCommand(argsText) {
  const args = splitArgs(argsText);
  const sub = (args[0] || "status").toLowerCase();
  const state = loadState();

  if (sub === "on") {
    state.enabled = true;
    saveState(state);
    return [
      "Modo red-team LIGADO.",
      `  trigger (palavra real): ${state.trigger || "(nao definida)"}`,
      `  decoy  (grafia neutra): ${state.decoy || "(nao definida)"}`,
      "  Transliteracao: IN decoy->trigger (disco), OUT trigger->decoy (visao do modelo).",
      "  Use /jailbreak pair <trigger> <decoy> para trocar o par.",
    ].join("\n");
  }
  if (sub === "off") {
    state.enabled = false;
    saveState(state);
    return "Modo red-team DESLIGADO. Transliteracao suspensa.";
  }
  if (sub === "pair") {
    // ── COM 1 ARGUMENTO: gera a decoy (o modo que o dono quer) ────────
    // MEDIDO 08/11: o dono digitava a MESMA palavra nos dois lados
    // ("pair não não") e o par virava no-op (trigger == decoy) — a
    // traducao nao acontecia e o modelo via o termo real. E o par so
    // aceita UMA decoy, enquanto a lista aceita N.
    // Agora: /jailbreak pair <palavra> gera as decoys sozinho (o
    // trigger fica a palavra real, a decoy e a 1a gerada) e o par vira
    // tambem um item da LISTA (a lista e' a que aceita N decoys).
    if (args.length === 2) {
      const palavra = (args[1] || "").trim();
      if (!palavra) return "Uso: /jailbreak pair <palavra>\n";
      if (palavra.length < MIN_LEN) {
        return `palavra "${palavra}" tem ${palavra.length} chars — minimo ${MIN_LEN}.`;
      }
      const geradas = gerarDecoys(palavra);
      if (!geradas.length) return `nenhuma decoy util para "${palavra}".`;
      state.trigger = palavra;
      state.decoy = geradas[0];
      state.enabled = true;
      // a lista guarda TODAS as decoys (a 1a e a que o modelo ve)
      const others = (state.deception || []).filter((x) => entryTerm(x) !== palavra);
      const anterior = (state.deception || []).find((x) => entryTerm(x) === palavra);
      const prev = anterior && Array.isArray(anterior.decoys)
        ? anterior.decoys.filter(Boolean) : [];
      const merged = [...prev];
      for (const d of geradas) if (!merged.includes(d)) merged.push(d);
      others.push({ termo: palavra, decoys: merged });
      state.deception = others;
      saveState(state);
      return (
        `par + lista atualizados para "${palavra}" (modo LIGADO):\n` +
        `  decoy que o modelo ve: ${geradas[0]}\n` +
        `  lista (${merged.length} decoy(s)): ${merged.join(" | ")}\n` +
        "  (o termo real nunca sai do disco: a decoy entra no comando, o termo real volta)"
      );
    }
    if (args.length < 3) {
      return (
        "Uso: /jailbreak pair <palavra>            (gera as decoys)\n" +
        "     /jailbreak pair <trigger> <decoy>     (forma manual)\n" +
        `  atual: trigger=${state.trigger || "-"} decoy=${state.decoy || "-"}`
      );
    }
    const trigger = (args[1] || "").trim();
    const decoy = (args[2] || "").trim();
    // A DIRECAO: o PRIMEIRO e a palavra REAL (o que vai pro disco), o
    // SEGUNDO e a forma que o MODELO ve. Se o dono inverter (mesma
    // palavra nos dois, ou uma decoy no lugar do trigger), o par vira
    // no-op — e o plugin AVISA em vez de fingir que configurou.
    if (trigger === decoy) {
      return (
        `trigger e decoy sao a MESMA palavra ("${trigger}") — isso nao traduz nada.\n` +
        "  O 1o e a palavra REAL (vai pro disco), o 2o e a forma que o MODELO ve.\n" +
        "  Use /jailbreak pair <palavra> para o plugin gerar as decoys por voce."
      );
    }
    if (trigger.includes(decoy) || decoy.includes(trigger)) {
      return (
        `trigger "${trigger}" e decoy "${decoy}" sao fatias um do outro — a troca fica ambigua.\n` +
        "  Use /jailbreak pair <palavra> para o plugin gerar as decoys por voce."
      );
    }
    state.trigger = trigger;
    state.decoy = decoy;
    saveState(state);
    return (
      `Par atualizado: trigger="${state.trigger}" (palavra real) decoy="${state.decoy}" (forma do modelo)\n` +
      "  (o modo continua como estava; use /jailbreak on para ligar)"
    );
  }
  if (sub === "reset") {
    state.enabled = false;
    state.trigger = "";
    state.decoy = "";
    state.note = "";
    state.deception = [];
    saveState(state);
    return "Estado red-team resetado: modo off, sem par, lista de termos vazia.";
  }
  if (sub === "term" || sub === "termo" || sub === "deception") {
    const legacy = sub === "deception";
    const action = (args[1] || "list").toLowerCase();
    // ── auto: gera N decoys do termo, sem o dono digitar cada uma ──────
    // (o dono: "era pra fazer lista de decoy, um so nao ajuda").
    // Cada metodo do DECEPTION_METHODS vira uma decoy candidata; a 1a e a
    // forma que o modelo ve, as outras sao as alternativas que voltam ao
    // termo real quando o modelo devolve qualquer uma delas.
    if (action === "auto") {
      const term = (args[2] || "").trim();
      if (!term) {
        return "Uso: /jailbreak term auto <termo> [n]\n"
          + "  (gera n decoys do termo e joga na lista; padrao n=4)";
      }
      const n = Math.max(1, Math.min(8, parseInt(args[3] || "4", 10) || 4));
      if (term.length < MIN_LEN) {
        return `termo "${term}" tem ${term.length} chars — minimo ${MIN_LEN}.`;
      }
      const candidatos = [];
      for (const [nome, m] of Object.entries(DECEPTION_METHODS)) {
        let d;
        try {
          d = m.encode(term);
        } catch {
          continue;
        }
        if (!d || d === term) continue;
        if (term.includes(d)) continue;      // fatia do termo: quebra a volta
        if (d.length < MIN_LEN) continue;    // curta: reescreve o mundo
        if (!candidatos.includes(d)) candidatos.push({ d, metodo: nome });
      }
      if (!candidatos.length) {
        return `nenhuma decoy util para "${term}".`;
      }
      const escolhidas = candidatos.slice(0, n);
      const others = (state.deception || []).filter((x) => entryTerm(x) !== term);
      const anterior = (state.deception || []).find((x) => entryTerm(x) === term);
      const prev = anterior && Array.isArray(anterior.decoys)
        ? anterior.decoys.filter(Boolean) : [];
      const merged = [...prev];
      for (const e of escolhidas) if (!merged.includes(e.d)) merged.push(e.d);
      others.push({ termo: term, decoys: merged });
      state.deception = others;
      saveState(state);
      return (
        `termo "${term}" na lista (${others.length} termo(s)) — ${merged.length} decoy(s):\n` +
        `  ${merged.join(" | ")}\n` +
        `  (metodos: ${escolhidas.map((e) => e.metodo).join(", ")})\n` +
        "  (a 1a decoy e a forma que o modelo ve; qualquer decoy volta ao termo real no comando)"
      );
    }
    if (action === "add") {
      const term = (args[2] || "").trim();
      if (!term) {
        return "Uso: /jailbreak term add <termo> <decoy...>\n"
          + "  (o primeiro decoy e a forma que o modelo ve; o resto sao alternativas)";
      }
      let decoys;
      if (legacy) {
        const metodo = (args[3] || "split").toLowerCase().trim();
        if (!DECEPTION_METHODS[metodo]) {
          return `metodo desconhecido: ${metodo}\n`
            + "disponiveis: " + Object.keys(DECEPTION_METHODS).join(", ");
        }
        decoys = [DECEPTION_METHODS[metodo].encode(term)];
      } else {
        decoys = args.slice(3).map((s) => s.trim()).filter(Boolean);
        if (!decoys.length) {
          return "Uso: /jailbreak term add <termo> <decoy...>\n"
            + "  (informe pelo menos 1 decoy)";
        }
      }
      if (term.length < MIN_LEN) {
        return `termo "${term}" tem ${term.length} chars — minimo ${MIN_LEN}.\n`
          + "  (troca por substring: 1-2 chars quebram qualquer palavra do "
          + "prompt e de todo comando — o resto da lista nao foi gravado)";
      }
      const curta = decoys.find((d) => d.length < MIN_LEN);
      if (curta) {
        return `decoy "${curta}" tem ${curta.length} chars — minimo ${MIN_LEN}.\n`
          + "  (troca por substring: decoy curta reescreve qualquer palavra "
          + "que contenha ela — a lista nao foi gravada)";
      }
      const igual = decoys.find((d) => d === term);
      if (igual) {
        return `decoy "${igual}" e igual ao termo — nao serve de forma.\n`
          + "  (a decoy precisa ser DIFERENTE do termo real)";
      }
      // Decoy que e FATIA do termo quebra a recomposicao: o termo real
      // contem a decoy, entao a troca (por substring) remonte o termo
      // ("alvo.exemplo.gov" + decoy "alvo." -> "alvo.exemplo.gov.exemplo.gov").
      const fatia = decoys.find((d) => term.includes(d));
      if (fatia) {
        return `decoy "${fatia}" e um pedaco do termo "${term}".\n`
          + "  (a troca e por substring: a decoy dentro do termo remontaria "
          + "o termo — a lista nao foi gravada)";
      }
      // ACUMULA (medido 08/11): o dono adicionou varias decoys do mesmo
      // termo e o plugin SOBRESCREVIA a lista anterior — o `filter` tirava
      // o termo e o `push` trazia so as decoys novas. O dono: "eu tentei
      // varios decoys diferentes o plugin ta sobrecrevendo? era pra fazer
      // lista de decoy, um so nao ajuda". Agora as decoys novas SAO SOMADAS
      // as antigas (sem duplicar) e a ordem e preservada.
      const others = (state.deception || []).filter((x) => entryTerm(x) !== term);
      const anterior = (state.deception || []).find((x) => entryTerm(x) === term);
      const prevDecoys = anterior && Array.isArray(anterior.decoys)
        ? anterior.decoys.filter(Boolean) : [];
      const merged = [...prevDecoys];
      for (const d of decoys) if (!merged.includes(d)) merged.push(d);
      others.push({ termo: term, decoys: merged });
      state.deception = others;
      saveState(state);
      const novos = merged.length - prevDecoys.length;
      return (
        `termo "${term}" na lista (${others.length} termo(s)) — ${merged.length} decoy(s):\n` +
        `  ${merged.join(" | ")}\n` +
        (novos > 0
          ? `  (+${novos} decoy(s) nesta chamada; as anteriores foram mantidas)\n`
          : "  (nenhuma decoy nova — a lista ja tinha estas)\n") +
        "  (a 1a decoy e a forma que o modelo ve; qualquer decoy volta ao termo real no comando)"
      );
    }
    if (action === "rm" || action === "remove") {
      const term = (args[2] || "").trim();
      if (!term) return "Uso: /jailbreak term rm <termo>";
      const next = (state.deception || []).filter((x) => entryTerm(x) !== term);
      state.deception = next;
      saveState(state);
      return `removido "${term}" (restam ${next.length} termo(s)).`;
    }
    if (action === "clear") {
      state.deception = [];
      saveState(state);
      return "lista de termos limpa.";
    }
    if (action === "list") {
      const entries = termEntries(state);
      if (!entries.length) {
        return "lista de termos vazia.\n"
          + "  /jailbreak term add <termo> <decoy...>";
      }
      return (
        "lista de termos (decoy = forma que o modelo ve):\n" +
        entries.map((x) => `- ${x.termo} -> ${x.decoys.join(" | ")} (${x.decoys.length})`).join("\n")
      );
    }
    return "Uso: /jailbreak term <add|rm|list|clear>";
  }
  if (sub === "status") {
    const entries = termEntries(state);
    const formas = entries.map((x) => x.decoys[0]).filter(Boolean);
    return (
      `Modo red-team: ${state.enabled ? "LIGADO" : "desligado"}\n` +
      `  forma visivel: ${state.decoy || "-"}\n` +
      "  (a palavra real nao e mostrada — ela fica so no disco/comando)\n" +
      `  termos: ${entries.length}`
      + (entries.length ? ` — formas: ${formas.join(", ")}` : "") +
      `\n  estado:  ${STATE}`
    );
  }
  return HELP;
}

// So aceita o comando quando o prompt inteiro e o comando (ancorado):
// uma frase normal que cite "/jailbreak" no meio NAO e sequestrada.
export function parseJailbreak(text) {
  const m = /^\s*\/jailbreak(?:\s+([\s\S]*))?$/.exec(String(text || ""));
  if (!m) return null;
  return (m[1] || "").trim();
}

function currentText(api, focused) {
  const editor =
    (api.renderer && api.renderer.currentFocusedEditor) || focused || null;
  if (!editor || typeof editor.plainText !== "string") return "";
  return editor.plainText;
}

function clearPrompt(api) {
  const editor = api.renderer && api.renderer.currentFocusedEditor;
  if (!editor || typeof editor.setText !== "function") return;
  try {
    editor.setText("");
  } catch {
    /* o editor pode ter sido destruido no meio do ciclo */
  }
}

export default {
  id: "redteam-tui",
  async setup(context) {
    const showReply = (reply) => {
      try {
        Promise.resolve(
          context.ui?.dialog?.alert?.({ title: "red-team", message: reply }),
        ).catch(() => showToast(reply));
        return;
      } catch {
        showToast(reply);
      }
    };
    const showToast = (reply) => {
      try {
        context.ui?.toast?.show?.({ message: reply, variant: "info" });
        return;
      } catch {
        console.error("[redteam-tui] sem API de dialogo/toast para mostrar a resposta");
      }
    };

    context.keymap.layer(() => ({
      mode: "global",
      priority: 10,
      commands: [
        {
          id: "redteam.jailbreak",
          title: "/jailbreak — red-team local (sem turno de modelo)",
          group: "Red team",
          palette: true,
          slash: { name: "jailbreak", arguments: true },
          run: async (input) => {
            const text = String(input ?? "").trim();
            if (!text) {
              showReply(HELP);
              return;
            }
            showReply(handleJailbreakCommand(text));
          },
        },
      ],
    }));
  },
};
