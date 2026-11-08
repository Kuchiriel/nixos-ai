# Estudar tibia-maps-script (@explore subagent)

- **sessão:** `ses_ee70f921fffeAprHRiC8ceV2HX`
- **quando:** 2026-10-08 00:36 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 5 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Estude o repo em /home/nixos/projects/canary-official/tool/map-editors/tibia-maps-script. Retorne: (1) o que faz, stack, (2) formato de entrada/saída, (3) scripts de conversão disponíveis (OTBM->PNG? minimap?), (4) como rodar, (5) insights para nosso pipeline de render/preview. Máx 300 palavras.

---

## · ?

## tibia-maps-script — Análise

**1. O que faz / Stack**
CLI Node.js (>=26, ESM) que converte mapas binários do Tibia (minimap) para formato legível (PNG + JSON) e vice-versa. Dependências-chave: `node-canvas` (composição de tiles), `tibia-minimap-png` (wrap/unwrap de buffers), `argh` (CLI), `glob`.

**2. Formato entrada/saída**
- `--from-minimap`: lê `minimap/Minimap_Color_X_Y_Z.png`, `Minimap_WaypointCost_X_Y_Z.png` e `minimapmarkers.bin` → grava `data/floor-XX-map.png`, `data/floor-XX-path.png`, `data/markers.json`, `data/bounds.json`.
- `--from-data`: lê os PNGs/JSON de `data/` → reconstrói `minimap-new/Minimap_*.png` + `minimapmarkers.bin` prontos para o client.

**3. Scripts de conversão**
- `--from-minimap` → data (PNG por floor + markers)
- `--from-data` → minimap (reconstrói binário)
- `--sort-markers` (ordena/deduplica markers.json in-place)
- Flags úteis: `--markers-only`, `--union` (merge incremental de markers), `--no-markers`, `--overlay-grid` (grid visual nos tiles), `--extra=dir1,dir2` (sobrepõe tiles custom ex: achievements).

**4. Como rodar**
```sh
npm install -g tibia-maps
tibia-maps --from-minimap=./minimap --output-dir=./data
tibia-maps --from-data=./data --output-dir=--minimap-new
tibia-maps --sort-markers=./data/markers.json
```

**5. Insights para pipeline render/preview**
- **Composição por floor**: monta canvas 256×N por floor inteiro — ideal para preview full-map.
- **Batching com BATCH_SIZE=50** para limitar memória — padrão útil se formos renderizar mapas grandes.
- **Separação map vs path**: permite gerar preview só do visual (Color) sem processar waypoint cost.
- **`bounds.json` gerado automaticamente** — elimina config manual de coordenadas.
- **`--overlay-grid`** dá feedback visual de tile boundaries — bom para debug de alinhamento.
- **`--union`** permite incrementar markers sem reprocessar PNGs — otimiza iteração.
- **Extra directories** possibilitam camadas custom (eventos, achievements) sobre o mapa base — extensível para overlays de POI/quest.

---

