# Estudar yatme (@explore subagent)

- **sessão:** `ses_ee70f9a1affeFgOJVDLVKABK74`
- **quando:** 2026-10-08 00:36 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 6 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Estude o repo em /home/nixos/projects/canary-official/tool/map-editors/yatme. Retorne: (1) o que é, stack, (2) formato de mapa (OTBM? OTB? JSON?), (3) como renderiza tiles/sprites, (4) features de edição/conversão, (5) insights para scripts de conversão e camadas intermediárias. Máx 300 palavras.

---

## · ?

## YATME — Análise

**(1) O que é / Stack**
Editor de mapas OpenTibia para o cliente Tibia 15.00+ (formato protobuf), inspirado no Remere's Map Editor. Stack: **React 19 + PixiJS 8 + TypeScript + Vite + Tailwind 4**, com servidor Express para self-hosting (Docker). Testes via Vitest. Protobufs gerados via `namely/protoc-all`.

**(2) Formato de mapa**
**OTBM** (binary tree: nós `0xFE`/`0xFF`, escape `0xFD`). Parser/serializer próprio em `src/lib/otbm.ts` (1138 linhas). Estrutura: header → tile areas 256x256 → tiles com items e atributos (actionId, uniqueId, teleport, houseId, etc.). Suporta OTBM v3+ (towns, zones, waypoints). Sidecars XML: `*-house.xml`, `*-monster.xml`, `*-npc.xml`, `*-zones.xml`. **Não usa OTB** — no v15.00+ Server ID = Client ID, eliminando camada de mapeamento.

**(3) Renderização**
Pipeline: `appearances.dat` (protobuf) → `catalog-content.json` (manifest) → sprite sheets `.bmp.lzma` → PNGs (conversão via `scripts/convert-sprites.ts` usando `lzma-native` + `sharp`). Sheets de 384px, sprites 32x32/64x64. `ChunkManager` agrupa tiles espacialmente; `TileRenderer` resolve sprites via `SpriteResolver`/`TextureManager`. Renderização multi-floor com offset diagonal (estilo RME). Z-axis: Z=0 céu, Z=7 chão, Z=8-15 subterrâneo.

**(4) Features**
Brushes XML (ground/wall/carpet/doodad com auto-tiling), undo/redo, copy/paste, fill, replace, door tool, light engine, minimap, house overlay, spawn editor (criaturas/NPCs), waypoints, grid overlay, seleção multi-floor.

**(5) Insights para scripts de conversão**
- OTBM é o formato canônico — usar como camada intermediária direta.
- `otbm.ts` é parser/serializer completo e testado — reutilizar como base.
- Conversão de sprites: header CIP de 32 bytes + LZMA1 raw (props lc/lp/pb + dict size).
- Ordenação de items: RME desenha em ordem forward (último = topo); OTClient inverte — traduzir na exportação.
- `vendor-parsers.md` documenta parsers C++ de referência (OTClient/RME) para validação cruzada.
- Arquitetura modular (MapRenderer/MapMutator/ChunkManager) facilita extração de componentes reutilizáveis.

---

