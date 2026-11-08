# Estudar tibia-map web viewer (@explore subagent)

- **sessão:** `ses_ee70fb167ffeHo3XlZ7P4SJjVP`
- **quando:** 2026-10-08 00:36 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 4 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Estude o repo em /home/nixos/projects/canary-official/tool/map-editors/tibia-map. Retorne: (1) estrutura e stack (framework, build), (2) como carrega/renderiza o mapa (tiles? canvas? WebGL?), (3) como adicionar camadas/markers, (4) como rodar localmente, (5) insights para refazer nossa página /mundo. Máx 300 palavras.

---

## · ?

## tibia-map — Estudo do repo

**1) Estrutura e stack**
Vanilla JS puro (sem framework), build via **Rollup** (bundle IIFE + terser), PostCSS com autoprefixer/cssnano. Entry: `src/index.js` → `src/_js/map.js` (1268 linhas, IIFE única). HTMLs: `index.html`, `embed.html`, `small.html`, `debug.html`. Assets: `_img/marker-icons/` (19 PNGs), `_json/areas.json`, `_css/layers.png` (sprite). Zero dependências runtime.

**2) Renderização**
**Canvas 2D** (não WebGL). Tiles de 256px do `tibia-map-data` (GitHub Pages) com cache em `Map`, `imageSmoothingEnabled=false` + `image-rendering: pixelated` para visual retrô. Zoom em 5 níveis discretos (`[1,2,7,20,40]`) com interpolação LERP via `requestAnimationFrame`. Pan/zoom com pivot, clamp aos bounds do mapa, suporte a mouse/touch/teclado. Labels de áreas são overlays HTML posicionados sobre o canvas.

**3) Camadas/markers**
Tudo desenhado no `draw()` em ordem fixa: tiles → contornos de áreas (stroke amarelo, hover com dimming `evenodd`) → grid → crosshair/exiva → markers. Markers vêm de `markers.json` (ou `?markers=base64`, `?markersUrl=`, `data-markers` inline). Cada marker tem `{x, y, z, icon, description}`; ícones mapeados para PNGs em `_img/marker-icons/`. Tooltip HTML no hover (hit zone 7px). Toggles: exiva (E), markers (M), áreas (A), grid (G), tipo (P), andar (J/K/L).

**4) Rodar localmente**
```bash
nvm use        # Node 18
npm install
npm run dev    # rollup -w + livereload em http://localhost:10015
```
Build: `npm run build` → `dist/`. Dados de tiles vêm do GitHub Pages remoto (funciona offline só com cache).

**5) Insights para /mundo**
- **Canvas 2D + tiles 256px** é suficiente e mais simples que WebGL para mapa 2D — considere Leaflet/MapLibre se quiser slippy map com pan contínuo.
- **Estado na URL hash** (`#x,y,z:zoom`) é elegante para deep-linking de POIs.
- **Overlays HTML** para labels/tooltips evita hit-testing manual no canvas.
- **Cache de imagens** com `Map` + redraw no `onload` é padrão reutilizável.
- **Culling por viewport** (só desenha tiles visíveis) é essencial para performance.
- **Toggles de camada** com teclas (E/M/A/G) são UX de editor — copiável.
- O código é um IIFE monolítico; para /mundo, considere módulos separados (renderer, state, input, data).

---

