# Inventariar banks de sprites/UI (@general subagent)

- **sessão:** `ses_ef22c9cc7ffe6PUnhI66DfaqmQ`
- **quando:** 2026-10-05 20:48 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 5 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Faça um inventário COMPLETO e barato (não abra imagens, só liste e conte) de todos estes diretórios e devolva um relatório compacto:

1. /home/nixos/models/sprites/refs/ (subpastas: otsp_png, dcss_png, oga_png, fx64_bank, fx64_frames, flux_night, clip_bank_*.pt, saw_ref, descartados?)
2. /tmp/opencode/uipacks/ (kenney, kenney-pixel, kenney-adv, gameicons + zips)
3. /tmp/opencode/uibank/ (icons32, skill_icons.json, montages)
4. /tmp/opencode/uitest/ e /tmp/opencode/otui-merge2/
5. /home/nixos/projects/otclient/data/images/ (subpastas blackfun, ui, topbuttons, etc. — conte PNGs por pasta)
6. /home/nixos/models/*.gguf, *.safetensors, *.ckpt (tamanho + propósito aparente pelo nome)

Para cada local: quantidade de arquivos, tamanho total (du -sh), licença se houver arquivo License.txt ou se souber pela origem (Kenney=CC0, game-icons=CC-BY 3.0, DCSS=CC0, OTSP=verificar, Flux=gerado local), e UMA linha dizendo o propósito (ex: "donors itens", "chrome UI", "ícones skills").

Também liste arquivos .md de handoff em /home/nixos/projects/nixos-ai/docs/ (só nomes).

Devolva: tabela compacta local | arquivos | tamanho | licença | propósito + ao final uma PROPOSTA de reorganização em pastas (o que juntar, o que apagar, o que mover de /tmp para local permanente). Seja terse, sem enrolação. NÃO mova nem apague nada, só inventarie e proponha.

---

## · ?

Inventário barato em curso — contando arquivos sem abrir imagens.

---

## · ?

Levantamento inicial ok — agora detalhando licenças e quebrando subpastas.

---

## · ?

Quase lá — checando licenças e pastas restantes.

---

## · ?

Relatório (só `ls/du/find`, nada aberto):

## 1. `~/models/sprites/refs/` — 61.079 arq, ~1,1G

| local | arq | tam | licença | propósito |
|---|---|---|---|---|
| `dcss/` | 9.606 | 163M | GPL-2+ (`LICENSE`), tiles CC0 | source crawl-ref original |
| `dcss_png/` | 8.440 | 33M | idem | tiles 32px export p/ CLIP/donor |
| `otsp_png/` | 7.675 | 30M | verificar (fan Tibia) | donors itens/outfits OT |
| `oga/`+`oga_png/` | 99+48 | 692K+216K | CC0/CC-BY (readme minerals) | donors minerais/props |
| `fx64/` (`Free/`) | 273 | 66M | verificar Yuriy/Arks | origem FX64 |
| `fx64_bank/` | 3.357 | 15M | gerado local | bank 32px curado p/ treino |
| `fx64_frames/` | 26.856 | 113M | gerado local | frames brutos (90% lixo) |
| `flux_night/` | 4.190 | 127M | gerado local (Flux) | gerações noite |
| `flux_trash/` | 48 | 1,6M | gerado local | rejeitados (=`descartados?`, não há outra pasta) |
| `saw_ref/` | 323 | 15M | gerado+vanilla | ref serras/tools teste SAW |
| `ot-pack/` | 130 | 71M | CC-BY 4.0 (`LICENSE.txt`) | pack comunidade (client/server/rme) |
| `phobos/`+`Phobos.zip`+`phobos_dec.bin` | 23+2 | 190M+78M+127M | verificar (client fechado) | ref Phobos/descompilado |
| `clip_bank_*.pt` (4x) | 4 | 60M | gerado local | embeddings busca donor-match |
| `glaclient.zip`+`gold/tin_*vanilla.png` | 3 | 62M+2K | vanilla | refs vanilla |
| `crawl-ref/source/rltiles/dngn/...` | — | incl. em `dcss/` | — | subpastas listadas no `rtk ls` inicial |

## 2. `/tmp/opencode/uipacks/` — 6.412 arq, ~77M c/ zips

| local | arq | tam | licença | propósito |
|---|---|---|---|---|
| `kenney/` | 1.315 | 5,3M | CC0 (`License.txt`) | chrome UI geral |
| `kenney-pixel/` | 519 | 2,2M | CC0 | chrome UI pixel |
| `kenney-adv/` | 393 | 1,9M | CC0 | chrome UI adventure |
| `gameicons/` | 4.181 | 37M | CC-BY 3.0 (`icons/license.txt`) | glyphs itens/skills |
| `*.zip` (4x) | 4 | ~31M | idem | duplicatas dos extraídos |

## 3. `/tmp/opencode/uibank/` — 178 arq, ~1M

| local | arq | tam | licença | propósito |
|---|---|---|---|---|
| `icons32/` | 174 | 696K | derivado CC-BY 3.0 | ícones skills 32px normal+gold |
| `skill_icons.json` | 1 (87 keys) | 5K | gerado local | mapa skill→ícone |
| `skills_{all,v2,white_32}.png` | 3 | ~300K | gerado local | montages preview |

## 4. `/tmp/opencode/uitest/` + `otui-merge2/` — 22 arq, ~96K

| local | arq | tam | licença | propósito |
|---|---|---|---|---|
| `uitest/` (`images/ui/`+`test_kenney.otui`+`mock_*.png`) | 9 | 40K | gerado local | teste OTUI Kenney |
| `otui-merge2/` (`*.otui`+`_VEREDITO_v2.md`) | 13 | 56K | gerado local | fragmentos merge OTUI |

## 5. `~/projects/otclient/data/images/` — 1.899 arq, 37M

| pasta | arq | tam | propósito |
|---|---|---|---|
| `blackfun/` | 342 | 13M | skin Blackfun ativa |
| `game/` | 1.073 | 18M | sprites jogo (creatures/items) |
| `ui/` | 240 | 2,0M | chrome UI default a substituir |
| `icons/` | 86 | 348K | ícones spells/client |
| `options/` | 38 | 180K | telas options |
| `topbuttons/` | 35 | 152K | botões topo |
| `inventory/` | 27 | 120K | slots inv |
| `bars/` | 22 | 88K | barras/hp |
| `automap/flags/healthmana/optionstab/skin/store` | 6+6+5+6+4+7 | 32K+320K+20K+28K+16K+28K | mapas/flags/vitals/misc |
| raiz `background.png`+`clienticon.png` | 2 | 3,8M | splash+ícone |

Extensões `blackfun+game`: 1.398 png, 14 jpg, 3 psd.

## 6. `~/models/*.gguf/*.safetensors/*.ckpt` — 17 arq, ~103G (dir todo 142G)

| arquivo | tam | propósito aparente |
|---|---|---|
| `Qwen3-4B-Q4_K_M.gguf` | 2,4G | tier fast/router |
| `Qwen3-30B-A3B-Q4_K_M.gguf` | 17,7G | tier strong MoE |
| `Qwen3.6-35B…Q4_K_M.gguf` / `…Q4_K_P.gguf` | 20,2G / 22,3G | **duplicata** uncensored strong (M vs P) |
| `Qwen3.5-4B-MTP…` / `…Uncensored…` | 2,7G / 2,6G | MTP draft / uncensored 4B |
| `DeepSeek-R1-Distill-Qwen-7B…` | 4,5G | reasoning distill |
| `Phi-4-mini…` / `gemma-3-4b…` / `Llama-xLAM-2-8B…` | 2,4G / 2,4G / 4,7G | mini / gemma / function-call |
| `flux1-schnell-Q2_K.gguf`+`flux-vae…`+`t5xxl_fp16/fp8…` | 3,8G+0,16G+9,3G/4,7G | geração imagem |
| `clip_l.safetensors` / `siglip-…safetensors` | 0,23G / 0,78G | vision encoders |
| `pixelart-sd15.ckpt` | 4,1G | gen sprites pixelart |

## 7. `~/projects/nixos-ai/docs/*.md` (só nomes)

`CRITERIOS-AUTO-EVOLUCAO.md`, `HANDOFF-2026-09-25.md`, `HANDOFF-2026-09-26-MANHA.md`, `HANDOFF-2026-09-29.md`, `HANDOFF-2026-10-03.md`, `HANDOFF-2026-10-05.md`, `LESSONS-2026-09-30.md`, `PROMPT-AGENTE-EXTERNO.md`, `README.md`, `REIDRATAR-APOS-COMPACTAR.md`, `ROADMAP-HARNESS.md`, `SECRETS.md`, `SINTESE-NOITE-30-09.md`, `SISTEMA-ESTADO-E-BENCHMARKS.md`, `TIERS-E-PAPEIS.md`, `VERIFIER-BUGS-2026-09-30.md`, `desktop-interaction.md`

## PROPOSTA (nada movido/apagado)

```
~/models/
├── sprites/refs/            # MANTER (fonte). APAGAR: flux_trash/, fx64_frames/ (pós-curadoria, 113M/26k arq),
│                            #   phobos_dec.bin OU Phobos.zip (duplo 205M), glaclient.zip pós-extrair
├── ui-bank/                 # NOVO permanente ← /tmp/opencode/uibank/ (icons32+json+montages)
├── uipacks-src/             # NOVO permanente ← /tmp/opencode/uipacks/*/ (sem zips)
│   ├── kenney-merged/       # JUNTAR kenney+pixel+adv (mesma licença CC0)
│   └── gameicons/           # MANTER separado (CC-BY 3.0 exige atribuição!)
└── *.gguf                   # APAGAR duplicatas: Qwen3.6 Q4_K_M OU Q4_K_P (-20G),
                             #   t5xxl_fp16 (manter fp8, -9,3G)
~/projects/otclient/experimentos-otui/ # NOVO ← /tmp/opencode/uitest + otui-merge2 (100K, tirar do /tmp volátil)
/tmp → esvaziar após mover (tudo acima é volátil, reboot apaga)
otclient/data/images/ → NÃO MEXER (runtime); só `ui/` é alvo de troca pelo Kenney+gameicons
```

Maiores ganhos: `fx64_frames` 113M + zips uipacks 31M + dupes modelos ~30G.

---

