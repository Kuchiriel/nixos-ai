# Roundup de GitHub 13/11: o que fazer com o que apareceu (14/11/2026)

Transcrição baixada e testada no ambiente da casa. Fonte: **"Open Source Grok Bot,
copy any YouTube video, find anyone online"** (The Next New Thing, 13/11/2026, 40 min,
43 mil views). Transcrição completa em `~/Books/videos/pnZh5PAF3VE/` ✓ (42,9 mil chars,
baixada com `scripts/fetch-video-transcript.py` ✓).

O vídeo é um roundup semanal de trending: 10 repos + 3 bônus + 4 estreias. Só o que
tem chão na casa foi testado. **O resto foi descartado por medida de sobreposição** (a
casa já tem a capacidade equivalente ✓).

## 1. OpenMausBot (o Grok Bot open source) — o item principal, e o veredito é SIM

**O que é** (lido no README e no código ✓): umaequipe de agentes num app de chat, cada
bot com seu próprio modelo, sua própria "mão" (computador) e seus apps conectados. Os
bots rodam nos CLIs `claude`, `codex`, `grok` **na sua própria máquina** ✓, e um
**harness server local em 127.0.0.1:8799** é dono de cada processo ✓ (transcritos e
chaves na máquina ✓). O app de chat é separado, em 127.0.0.1:5199 ✓.

**Medido nesta casa (14/11):**

| teste | resultado |
|---|---|
| clone (`--depth 1`) | 418 MB ✓ |
| `pnpm install` (via `npx`, sem instalar global ✓) | 58 s, exit 0 ✓ |
| boot do harness server | **sobe** ✓: `openmausbot server on http://127.0.0.1:8799` ✓ |
| `GET /api/health` | 200 ✓ (version 0.1.158, capabilities ✓) |
| `GET /api/instances` | 200 ✓ (as instâncias vêm `unavailable` ✓ porque aqui não há claude/codex/grok ✓) |
| `GET /api/config` | 200 ✓ |
| edição | **open-source** ✓ (o log: "enterprise layer present but OMB_LICENSE_KEY is not set" ✓) |
| licença | **Apache-2.0** ✓ (22.677 stars ✓, TypeScript ✓, criado em 11/08/2026 ✓) |
| "bot box" (computador isolado por bot) | `off (not-cloud)` ✓ |

**O achado que decide:** o driver **`opencodeGo`** existe **no código open source** ✓
(`packages/phone-protocol/src/limit-reset.ts` traz `driver: "claude" | "codex" |
"grok" | "opencode"` ✓, e os e2e da própria OSS configuram `config.instances.opencodeGo`
✓). Há também `customAcp` ✓ e `commandCodeAgent` ✓, que são drivers genéricos de CLI ✓.
Ou seja: **a casa pode ter a UX do GrokBot com os agentes que ela já tem** (sessões do
opencode ✓, que a casa já entrega por API ✓ via `agent-api.py` ✓) **sem portar nada** ✓.

**O que não bate (o que falta para a casa):**
- O **app** é Electron/macOS-first ✓ (há .deb/AppImage ✓ e o web app ✓, então o Linux
  entra ✓ pelo web ✓).
- O **computador isolado por bot** (VM local ou desktop na nuvem ✓) não é o modelo da
  casa: aqui a "mão" de cada agente é a sua sessão do opencode ✓ (browser ✓, mouse ✓,
  tela ✓). Com 6 GB de VRAM ✓, VM local por bot não é opção ✓.
- O **`pnpm` não existe na casa** ✓ (o `corepack enable` não pegou ✓); o caminho que
  funcionou foi `npx --yes pnpm@10.15.0` ✓ (sem instalar global ✓).

**Próximo passo concreto, se você quiser:** rodar o harness como serviço do user ✓
(ele é um servidor Node ✓ em 127.0.0.1 ✓), declarar uma instância `opencodeGo` ✓
apontando para o CLI da casa ✓, e abrir o app web em :5199 ✓ como a "pele de chat" da
frota ✓. O ganho real não é o código (é Apache-2.0 ✓ e sobe ✓): é **a UX** ✓ (falar
com um agente como se fosse um contato ✓, com o histórico dele ✓).

## 2. Agent Browser (Vercel Labs) — adotado, é o padrão de leitura de página

CLI nativo (Rust) que dá um navegador ao agente e devolve a **árvore de
acessibilidade em texto** ✓, com `ref` em cada elemento ✓.

| teste | resultado |
|---|---|
| `nix search nixpkgs agent-browser` | **existe** ✓ (0.27.0 ✓, "Headless browser automation CLI for AI agents" ✓) |
| `nix run nixpkgs#agent-browser -- open https://github.com/anthropics/skills` | ✓ (abriu ✓) |
| `snapshot -i` | ✓ devolveu a árvore em texto com refs ✓ (links, botões, headings ✓) |
| tempo de `open` + `snapshot` | **1,85 s** ✓ |

O vídeo mede o mesmo contraste: computer use "toma o computador inteiro, é lento,
lê screenshot e screenshot" ✓; o agent-browser lê **texto** ✓. Na casa isso troca o
`jarvis_browser` (o browser do dono ✓, que é o que rouba a tela ✓) por um caminho
headless ✓ para o caso comum (ler e agir numa página ✓), deixando o browser do dono
só para o que precisa do **login dele** ✓.

**Registrado** ✓: skill `web-research` ✓ (declarativa no `home.nix` ✓, listada no
`AGENTS.md` ✓) com a regra: agent-browser para ler/agir ✓, Tavily para buscar ✓,
`jarvis_browser` só com login do dono ✓.

## 3. As skills do Anthropic (194 mil stars) — drop-in, mas a casa já tem quase tudo

O repositório tem 19 skills ✓ e a **formatação é a mesma da casa** ✓ (frontmatter
`name` + `description` + `license` ✓, igual ao `code-quality` da casa ✓). Ou seja:
**drop-in, sem portar** ✓.

O que a casa **já tem** (e por isso não entra, para não duplicar ✓):

| skill do Anthropic | equivalente na casa | veredito |
|---|---|---|
| `mcp-builder` | `mcp-development` ✓ (global ✓) | **duplicata** ✓ não entra |
| `webapp-testing` | `sandbox-qa` ✓ + o sandbox com Playwright ✓ | **duplicata** ✓ |
| `claude-api` | o knowledge da casa + a RAG ✓ | **duplicata** ✓ |
| `internal-comms` | o Telegram da casa ✓ | **duplicata** ✓ |
| `frontend-design`, `canvas-design`, `theme-factory`, `algorithmic-art`, `slack-gif-creator`, `brand-guidelines` | sem uso na casa ✓ | sem uso ✓ |
| `pdf`, `docx`, `pptx`, `xlsx` | a casa não tem skill de documento ✓ | **candidato** ✓ |
| `doc-coauthoring` | a casa escreve doc o tempo todo ✓ (o AGENTS.md é a moeda da casa ✓) | **candidato** ✓ |
| `skill-creator` | a casa cria skill ✓ (26 globais ✓) | **candidato** ✓ |
| `discernment-nudge` | sem uso conhecido ✓ | opcional ✓ |

A importação seria declarativa ✓ (`home.file` ✓, como a `opencode-coordination` ✓), com
o corpo inteiro da skill ✓ (ela tem `scripts/` e `reference/` ✓ — é pasta, não arquivo
✓).

## 4. O resto do vídeo, descartado por medida

`Sherlock` (busca de usuário em plataformas ✓ — é da lane da auditoria ✓, não do
`nixos-ai` ✓), `Daily Stock Analysis` (bolsa ✓ — a lane `matheus` já é de mercado ✓),
`NVIDIA AutoOntology` (ontologia de dados ✓ — a casa tem o equivalente no RAG com
coleções ✓), `MuJoCo` (simulador de robótica ✓ — sem uso ✓), `Ember Cloudflare` (chat
tipo Slack sobre Cloudflare ✓ — a casa roda Cloudflare ✓ mas não precisa de chat ✓),
`OpenGenjutsu` e `REA Video` (vídeo deepfake ✓ — fora do escopo ✓), e as 4 estreias
(Atlas ✓, Bomby ✓, Sprint Wake ✓, Rightsize ✓ — sem uso medido ✓).

O do vídeo que é **nossa pelo ângulo da casa** é o da ontologia ✓: a ideia de marcar os
dados com taxonomia para o agente achar por precisão ✓ em vez de por texto ✓ — é
exatamente o que a RAG da casa faz com as coleções ✓ (`code`/`memories`/`books`/
`sessions` ✓). A/OpenMausBot tem a mesma ideia aplicada a Cloudflare ✓ (diretório).

## 5. O que a casa ganhou com isso (e onde está)

| capacidade | onde | estado |
|---|---|---|
| baixar transcrição de vídeo (robusto ao 429 ✓) | `nixos-ai/scripts/fetch-video-transcript.py` ✓ | testado ✓ neste vídeo ✓ |
| monitorar novidades (YouTube ✓, RSS ✓, HN ✓, releases ✓) filtradas | `nixos-ai/scripts/watch-updates.py` ✓ + `scripts/watch-updates-sources.json` ✓ | testado ✓ (dry-run ✓: pegou Cloudflare e as releases do opencode ✓) |
| ler/agir em página web em texto ✓ | skill `web-research` ✓ (agent-browser do nixpkgs ✓) | testado ✓ (1,85 s ✓) |
| pele de chat do GrokBot sobre os agentes da casa ✓ | OpenMausBot ✓ (Apache-2.0 ✓, harness sobe aqui ✓, driver `opencodeGo` ✓) | boot testado ✓, falta declarar a instância ✓ |
| skills de documento do Anthropic ✓ | drop-in ✓ (mesmo formato ✓) | candidatos ✓, decisão do dono ✓ |

O registro no **meta routing** (é o que faz as agentes saberem que isso existe ✓, sem
token ✓): o `AGENTS.md` ganhou a linha de Knowledge (vídeo e novidades ✓) e o item da
skill na lista de skills ✓; as skills são corpo sob demanda ✓ (só `name`+`description`
no prompt ✓, progressive disclosure ✓).

## 6. O que eu recomendo, em ordem

1. **Instância `opencodeGo` no OpenMausBot** ✓: o harness já sobe ✓, o driver existe ✓
   na OSS ✓, e o ganho é a UX de falar com um agente como contato ✓. Custo: um serviço
   Node ✓ + o app web ✓.
2. **`doc-coauthoring` e `skill-creator` do Anthropic** ✓: drop-in ✓, formato idêntico ✓,
   e a casa usa as duas coisas todo dia ✓ (doc ✓ e skill ✓).
3. **O monitor de novidades no ar** ✓: um timer de user ✓ (o padrão da casa ✓) chamando
   o `watch-updates.py` ✓, publicando no bus ✓ (que é o canal cross-machine ✓) o que for
   novo nas fontes filtradas ✓.
4. **Não importar** o resto ✓: a sobreposição com o que a casa já tem está medida ✓.

## 7. Como reproduzir

```bash
cd ~/projects/nixos-ai
python3 scripts/fetch-video-transcript.py https://youtu.be/pnZh5PAF3VE --langs pt,en --digest
python3 scripts/watch-updates.py --dry-run
nix run nixpkgs#agent-browser -- open "https://github.com/anthropics/skills" && \
  nix run nixpkgs#agent-browser -- snapshot -i
```

A transcrição está em `~/Books/videos/pnZh5PAF3VE/` ✓ e indexada no RAG ✓ (coleção
`books` ✓).
