# Estudar tibia-map-data (@explore subagent)

- **sessão:** `ses_ee70fbe6bffes90iflu0hcB3N7`
- **quando:** 2026-10-08 00:36 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 5 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Estude o repo em /home/nixos/projects/canary-official/tool/map-editors/tibia-map-data. Retorne: (1) estrutura de pastas e arquivos principais, (2) formato dos dados (OTBM? JSON? PNG?), (3) como baixar/atualizar o mapa global, (4) scripts de conversão disponíveis, (5) insights úteis para nosso gerador de mapas procedural em Python. Seja conciso, máx 300 palavras.

---

## · ?

## Estudo: tibia-map-data

**1. Estrutura**
- `data/` — 16 floors (00–15), cada um com `floor-XX-map.png` (visual) + `floor-XX-path.png` (pathfinding), mais `bounds.json` e `markers.json`
- `extra/` — packs de marcadores temáticos (POI, achievements, rapid-respawn, etc.)
- `overlays/` + `data-with-overlays/` — overlays visuais (ex: "challenging")
- `scripts/` — build, overlays, marker packs

**2. Formato dos dados**
- **PNG** para mapa visual e pathfinding (não OTBM, não JSON para tiles)
- **JSON** para bounds (`xMin/xMax/yMin/yMax/zMin/zMax/width/height`) e markers (`{x, y, z, icon, description}`)
- Pathfinding: PNG onde cores codificam walkability (usado por `tibia-count-walkable-tiles`)
- Coordenadas: mundo 32x32 tiles por floor, range total ~2560x2048

**3. Como baixar/atualizar**
- O repo é upstream `tibiamaps/tibia-map-data` (referência, não editar)
- Atualização via cliente Tibia → `minimap/*` → converter com `tibia-maps --from-minimap=./minimap --output-dir=./data`
- GitHub Pages serve os PNGs estaticamente (hotlink direto)

**4. Scripts de conversão**
- `tibia-maps` (npm, bidirecional): minimap ↔ data (PNG+JSON)
- `tibia-count-walkable-tiles`: conta tiles walkable dos path PNGs
- `scripts/build.sh`: gera dist otimizado (imagemin, jsesc, zips)
- `scripts/apply-overlay.sh`: aplica overlays com ImageMagick
- `scripts/enable-pack.sh`: merge de packs sazonais

**5. Insights para gerador procedural em Python**
- **Pathfinding como imagem**: usar PNG com paleta fixa para walkability é mais eficiente que grid numérico — PIL/OpenCV leem direto
- **Bounds JSON**: formato simples para normalizar coordenadas (subtrair xMin/yMin)
- **Markers JSON**: schema direto para spawn points, POIs, teleports — reutilizável
- **Floor separation**: 16 floors independentes permitem geração paralelamente
- **Grid overlay**: `--overlay-grid` gera tiles 32x32 — útil para validar alinhamento procedural
- **Walkable count**: métrica de validação (comparar com `walkable-tiles.json` do build)

---

