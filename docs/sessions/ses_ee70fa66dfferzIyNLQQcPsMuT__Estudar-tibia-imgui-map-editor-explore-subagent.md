# Estudar tibia-imgui-map-editor (@explore subagent)

- **sessão:** `ses_ee70fa66dfferzIyNLQQcPsMuT`
- **quando:** 2026-10-08 00:36 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 4 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Estude o repo em /home/nixos/projects/canary-official/tool/map-editors/tibia-imgui-map-editor. Retorne: (1) stack e dependências, (2) formato de mapa que lê/escreve (OTBM? OTB?), (3) como renderiza tiles/sprites, (4) features de edição (brush, border, autofill), (5) insights para nosso gerador OTBM. Máx 300 palavras.

---

## · ?

## Estudo: tibia-imgui-map-editor

**1. Stack e dependências**
C++20, CMake 3.25+, OpenGL 3.3+ (GLFW/GLAD/GLM), Dear ImGui (docking), vcpkg/Conan. Utilitários: spdlog, nlohmann_json, pugixml, fmt, LZ4, Boost (IOStreams/Filesystem/CircularBuffer), zlib, stb_image, FontAwesome 6, ImGuiNotify, nativefiledialog-extended.

**2. Formato de mapa**
**OTBM** (Open Tibia Binary Map) — leitura completa, escrita parcial (básico; alguns atributos não serializados). Também lê **OTB** (item types), **DAT/SPR** (client data, versões 7.10–10.10+), **SEC**, e XMLs (brushes, creatures, tilesets, houses, spawns, palettes). Não usa OTB como formato de mapa.

**3. Renderização de tiles/sprites**
Pipeline OpenGL multi-pass: `TileRenderer` com `SpriteBatch` (batching por atlas page), `SpriteAtlas` (páginas 2048x2048), `RingBuffer` para uploads GPU. Chunks 32x32 tiles com VBO cacheado e culling por chunk. Sprites carregam async em background threads, upload via PBO (2 PBOs alternados + fence sync). Overlays: grid, selection, preview, tooltip, spawn labels, waypoints, light. Ghost floor com parallax diagonal (`floor_offset = (7-z)*32*zoom`).

**4. Features de edição**
- **Brushes funcionais**: RawBrush, EraserBrush, CreatureBrush, SpawnBrush, FlagBrush, WaypointBrush, HouseBrush
- **NÃO implementados**: auto-bordering (GroundBrush), auto-alignment (WallBrush), DoodadBrush, CarpetBrush, TableBrush — classes não existem
- **Lookup services** existem (BorderLookupService, WallLookupService, CarpetLookupService, TableLookupService) mas não estão wired aos brushes
- Undo/redo com LZ4 compression, copy/paste/cut/delete, selection, search async, map merge, cleanup

**5. Insights para gerador OTBM**
- **ChunkedMap** (32x32 tiles/chunk, 16 floors) é a estrutura de dados ideal — O(1) access, memory-efficient para mapas esparsos
- **OTBM writer é o ponto fraco** — se nosso gerador escrever OTBM, precisamos cobrir os atributos que o OtbmWriter não serializa
- **Brush lookup services** (border/wall/carpet/table) são a lógica mais complexa do RME — reutilizar o design desses serviços para nosso gerador
- **Coordenadas**: z=0 é superfície, z=7 é ground level, z=8-15 underground — convenção Tibia
- **Parallax de floors**: offset diagonal `(7-z)*32*zoom` para floors acima do chão
- **Formato OTBM**: o repo tem `IO/Otbm/OtbmReader` e `OtbmWriter` — estudar esses arquivos para entender o binário exato que nosso gerador deve produzir

---

