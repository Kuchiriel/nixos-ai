# Pesquisar skins UI otclient (@general subagent)

- **sessão:** `ses_ef7607692ffezr3dsuv1tVEEHP`
- **quando:** 2026-10-04 20:33 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 11 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Research task (no code changes): the user plays Tibia via OTClient (repo at /home/nixos/projects/otclient, game client 15.25) and wants a "reskin do client" = change the LOOK of the game client interface (windows, buttons, health bars, skins/themes), NOT the game sprites.

Investigate:
1. Does this OTClient support UI skins/themes? Look at /home/nixos/projects/otclient for: modules/ with skin/theme/style files, data/styles/, *.otui files, config for styles. Check how styles work (otui syntax?) and whether alternative styles exist in-repo.
2. Search the web (2026) for ready-made OTClient UI skins/themes (e.g., "otclient skin", "otclient theme", tibia interface skins, Medivia/custom client UIs) that could be dropped in.
3. Also check: can health bars, battle window, minimap styling be changed via Lua/modules? Note file paths.

Return: concise findings with exact paths/URLs, what exists in-repo vs what must be downloaded, and a recommended quickest win for changing the client face. Do NOT modify any files.

---

## · ?

Reskin research — mapping built-in themes and hunting ready skins.

---

## · ?

Found the theme engine location — now checking how windows, bars, and panels are skinned.

---

## · ?

Core styling confirmed — now hunting downloadable themes and alternative layouts.

---

## · ?

## OTClient reskin — findings (no files changed)

### 1. In-repo: yes to theming system, no to ready alternative skins

**No skin switcher, no second theme in this repo.** There is exactly one style set, auto-loaded at startup:

* `modules/client_styles/styles.lua:9-16` — `importResources("styles","otui")` = loads **every** `data/styles/*.otui` via `g_ui.importStyle`. No `layouts/` dir (checked — `**/layouts/**` = 0 hits). Old-fork guides mentioning `layouts/retro/styles/` do not apply here.
* `mods/` has no skins — only `client_mods/ client_profiles/ client_textedit/ game_bot/ game_buttons/ game_itemselector/ game_tasks/`.

**How styles work (OTUI = CSS-like):**

* `data/styles/README.md` — `&var` / `$var` palette aliases + classic `&luaField` widget fields.
* Syntax: `StyleName < BaseWidget` + props (`image-source`, `image-border` = 9-slice, `image-clip` = sprite-sheet rect, `image-color`, `font`, `color`, `background-color`, `padding/margin/anchors`) + pseudo-states `$hover $pressed $on $checked $disabled $active`.
* Example: `data/styles/10-windows.otui:1-16` (`Window` → `/images/ui/window`, border 6/top 27), `data/styles/10-buttons.otui:1-31` (`Button` → `/images/ui/buttons` + clip rects per state).
* Full property reference: `StylesOverview.md` (mirror: `git.someserver.de/gesche/tibia-client/.../doc/StylesOverview.md`); module-authoring guide: `sorky96.github.io/OtClientModules_documentation/`.
* Live inspector: `modules/dev_otui/` (`dev_otui.otui`, gallery + picker) — use it to preview widget styles in-client.

**The full reskin surface (interface only, not sprites):**

| What | Files |
|---|---|
| Windows/panels/buttons/scrollbars/tabs (the 80% of the "face") | `data/styles/` (~32 files): `10-windows.otui`, `10-buttons.otui`, `10-panels.otui`, `10-progressbars.otui`, `10-creaturebuttons.otui`, `20-topmenu.otui`, `20-tabbars.otui`, `30-miniwindow.otui`, `30-minimap.otui`, `30-statsbar.otui`, `40-gamebuttons.otui`, `40-outfitwindow.otui` |
| Window/button/panel PNGs (9-slice frames) | `data/images/ui/` (~170 PNGs): `window.png`, `window_new.png`, `window_headless.png`, `popupwindow.png`, `buttons.png`, `button*.png`, `miniwindow*.png`, `panel_*.png`, `tabbutton_*.png`, `progressbar.png`, `progress-green.png` |
| Top HP/mana panel | `modules/game_healthinfo/healthinfo.otui` + `.lua` ← PNGs `data/images/healthmana/` (`hitpoints_bar_filled.png`, `mana_bar_filled.png`, `hitpoints_manapoints_bar_border.png`) and `data/images/bars/` (health/mana/manashield/exp bars + markers) |
| Top stats bar variants (large/parallel/compact, top/bottom) | `data/styles/30-statsbar.otui` (`TopStatsBarLargeOnTop`, `...ParallelOnTop`, `StatsBarUp`, `UIStatsBar`) |
| Battle window + per-creature HP bars | `modules/game_battle/battle.otui` (MiniWindow `battleWindow`, filter icons `/images/game/battle/icon-battlelist-*`) + `modules/game_battle/battlebutton.otui`; row HP bar = `LifeProgressBar` in `data/styles/10-creaturebuttons.otui:72-79` (`CreatureButton < UICreatureButton`) |
| Minimap frame/buttons/rose/compass | `data/styles/30-minimap.otui` + `modules/game_minimap/minimap.otui` (`mainmappanel`, `minimapBorder` → `/images/ui/1pixel_down_frame`) + PNGs `data/images/automap/` + `data/images/game/minimap/` |
| In-world HP circles/rings | `modules/game_healthcircle/game_healthcircle.otui` + `.lua`, `statusiconbar.otui`, `images/bar_top.png bar_box.png bar_bottom.png` |
| Options/dialogs per module | `modules/<name>/*.otui` + `styles/*.otui` (e.g. `game_interface/styles/countwindow.otui`, `client_options/styles/...`, `game_actionbar/otui/*.otui`) — each module calls `g_ui.importStyle(...)` in its `.lua` |

Key insight: **a "reskin" = swap PNGs in `data/images/` + tweak the ~32 `data/styles/*.otui` + per-module `battle/minimap/healthinfo` OTUIs.** Lua is only needed for layout/behavior, not for look.

### 2. Ready-made skins (all external, nothing to download in-repo)

1. **Tibia Theme v1.2 by Zews** (the only theme credited in `opentibiabr/otclient` README) — classic-Tibia look. Thread + `.rar`: `https://otland.net/threads/otc-tibia-theme-v1-2.230988/` — **from 2015, almost certainly stale** for a 15.25 client (no wheel/cyclopedia/proficiency/monk widgets).
2. **StoneDrake UI** — best-looking community face, two forms:
   * Original pack (**images only**, you write the OTUI): `https://otland.net/threads/dragon-face-otc-stonedrake-ui-by-shiva-free-release.273990/` (`StoneDrakeClientUI.rar`, ~10 MB).
   * Implemented fork (**drop-in ready**: full `data/images` + merged OTUIs): `https://otland.net/threads/otclient-mehah-3-0-2-stonedrake-ui.287726/` → `https://github.com/manuelmaldonado1/OTClient-Blackfun-3.0.2` — per thread comments the recipe is: *replace `data/images`, merge `data/styles/*.otui` + per-module `*.otui`*. Newer color-theme variant work noted May 2026 in same thread ("6 color themes, switcher in start menu").
3. **OTUI visual editors** (avoid hand-editing): original alpha `https://github.com/Oen44/OTUIEditor` (via `https://otland.net/threads/tool-otui-editor.266030/`); 2025 Python/PySide6 rewrite (tibiadevs topic "Otui Editor & Creator - By Lehnox"); "OTUI Editor PRO" Qt6/C++ (tibiaking topic 115316).
4. **How-to reference**: `https://otland.net/threads/change-of-the-otc-login-window.290326/` — shows exactly the `10-buttons.otui` + `data/images/ui/button.png` override pattern.

⚠️ **Compat caveat:** all downloadable themes target old edubart/mehah-era clients (OTC 1.x–3.x, Tibia ~10–13). This repo is canary-line for **15.x** with new modules old themes never styled (`game_wheel`, `game_cyclopedia`, `game_proficiency`, monk stats in `30-statsbar.otui`, `game_store`, etc.). A blind overwrite **will** leave new windows unstyled/broken — plan on **merge, not replace**.

### 3. Can X be changed via Lua/modules? (paths)

* Health bars (top + battle rows): yes — `data/styles/30-statsbar.otui`, `data/styles/10-creaturebuttons.otui`, `modules/game_healthinfo/{healthinfo.otui,healthinfo.lua}`, `modules/game_battle/battle.otui`.
* Battle window: yes — `modules/game_battle/battle.otui` + `battlebutton.otui` + `battle.lua:1453` (`importStyle('battlebutton')`).
* Minimap chrome (frame, buttons, rose): yes — `data/styles/30-minimap.otui` + `modules/game_minimap/minimap.otui`. Map *contents* (tiles/colors) are engine-drawn, not skinnable via OTUI.

### Recommended quickest win

**PNG-swap reskin in a disposable copy** (zero code, biggest visual change per minute):

1. Copy the repo (or at least `data/images` + `data/styles`) as backup.
2. Drop in the **Blackfun/StoneDrake `data/images`** folder, then **merge (not overwrite)** its `data/styles/*.otui` + the 3 high-impact module OTUIs (`game_battle/battle.otui`, `game_healthinfo/healthinfo.otui`, `game_minimap/minimap.otui`) — keep this repo's versions for `game_wheel/cyclopedia/proficiency`-era widgets.
3. If that fights the 15.25 modules: fallback = keep stock OTUIs, only swap the five highest-leverage PNGs (`ui/window.png`, `ui/popupwindow.png`, `ui/buttons.png`, `ui/miniwindow*.png`, `healthmana/*_filled.png` + `bars/*`) and tint via `image-color`/`background-color` in `10-windows.otui` / `10-buttons.otui` / `30-statsbar.otui`.

Want me next to diff Blackfun's style/image tree against this repo's to produce an exact merge file list?

---

