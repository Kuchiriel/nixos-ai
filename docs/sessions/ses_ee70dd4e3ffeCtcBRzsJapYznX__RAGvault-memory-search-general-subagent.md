# RAG/vault memory search (@general subagent)

- **sessão:** `ses_ee70dd4e3ffeCtcBRzsJapYznX`
- **quando:** 2026-10-08 00:38 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 3 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Use jarvis_rag_search e jarvis_vault_search_obsidian e jarvis_recall para buscar tudo sobre: map generation, OTBM, borders, sprites, mountains, snow, sand, preview /mundo, gerar_mapa, RME border_types. Retorne todos os fatos relevantes encontrados com fonte (rag/vault/memory). Máx 400 palavras.

---

## · ?

**Fatos consolidados por fonte:**

**RAG (código — `canary-official/dataset/maps/`):**
- `gerar_otbm.py` — escreve `.otbm` válido (canary 15.25) a partir do JSON do `gerar_mapa.py`. MAP_DATA não emite byte de fechamento. Posição do tile é **relativa ao TILE_AREA pai** (1 byte/eixo); RME agrupa tudo num TILE_AREA 256×256. TILE_FLAGS bit `0x0E` = PREFERED — gerador marca tiles de fronteira para o servidor não spawnar.
- `sprites_rme.json` — catálogo nome/lookid/tiles/n_variantes: "white gravel" (104), "frozen mud" (7062–7066, 5 variantes), "ugly cobblestone" (8424), "grassy cobblestone" (791), "ice stone floor" (6967).

**Vault (Obsidian):** vazio — nenhum resultado.

**Memory (recall):**
- **Bordas (gabarito in-game 07/10):** 4531 = borda horizontal do topo (norte ✓); 4532 na vertical direita está **invertido** (material grama).
- **Bug "tudo sem borda":** causa raiz = loop de plantio tinha `if v["t"] != "terra": continue` — tile d'água no `gerar_mapa.py` é `"mar"`, não `"terra"`.
- **Worldgen v2:** bug crítico — `centerz` do spawn XML é z absoluto (`spawn_monster.cpp:51`); 120 animais nasciam no subsolo (z=0).
- **Auditoria do mundo (03/10):** 1.175.983 áreas / 13.357.073 tiles / 7,66M terra + 5,08M água / 2.403 grounds / 21.082 doodad tipos.
- **Sprites client 15.25:** `catalog-content.json` = 4927 sheets `sprites-<hash>.bmp.lzma` (tipo 0=32×32, 3=64×64; maioria 4488 tipo-3). `appearances.dat` = protobuf cru (header LZMA `70 0A FA 80 24` é dos sprite sheets).
- **Primeiro mapa gerado carregado (06/10):** `gerar_mapa.py` seed 42, 256×256, 5 biomas, 29.916 tiles, 5.588 doodads.
- **RME:** fork opentibiabr 09/22 com `client_assets.cpp`; verificado 07/10. Areia = 7.6% do mapa.

---

