# Pesquisar bancos sprites livres (@general subagent)

- **sessão:** `ses_ef7607681ffeOAVZitecPK60zS`
- **quando:** 2026-10-04 20:33 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 5 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Research task (no code changes, no downloads): the user reskins Tibia 15.x game sprites (32x32 pixel art items). We already use OTSP (OpenTibia Sprite Pack, CC-BY, 7675 sprites extracted). Find ADDITIONAL free/open sprite banks usable as donors:

1. Search the web for other open Tibia sprite packs (e.g., Loop sprites, TibiaFans resource packs, OTLand sprite releases, Kenney.nl pixel packs with compatible license, 16x16/32x32 RPG item packs CC0/CC-BY on itch.io, opengameart.org pixel item packs).
2. For each: name, URL, license, approximate size/count, format (PNG sheets? .spr/.dat? individual PNGs?), and whether Tibia-style (32x32 top-down-ish items) or generic RPG.
3. Prioritize: (a) Tibia-compatible style+size, (b) permissive license (CC0/CC-BY/MIT), (c) direct download (no login walls).
4. Also note any packs with bigger sprites (64x64) for future creature/outfit work.

Return a ranked shortlist (max 8) with URLs + license + why each fits. Do NOT download anything.

---

## · ?

Reskin donor hunt — mapping open 32×32 banks that pair with OTSP.

---

## · ?

First sweep mapped the big hubs — now digging for Tibia-specific and 64×64 creature options.

---

## · ?

Shortlist is taking shape — now verifying licenses on the top candidates.

---

## · ?

Research only — nothing downloaded. Ranked for: (a) Tibia 32x32 fit first, (b) CC0/CC-BY/MIT first, (c) no-login direct download first.

## Ranked shortlist (max 8)

### 1. Dungeon Crawl Stone Soup tiles / RLtiles — best overall donor
- URLs: https://github.com/crawl/tiles · mirror https://opengameart.org/content/dungeon-crawl-32x32-tiles
- License: **CC0** (maintainers split out only tiles with artist sign-off; repo keeps a `not eligible` list — check it before bulk use)
- Size: **3000+ tiles, 32x32px native**
- Format: individual **PNGs** + sheets, git clone / zip, no login
- Style: **Tibia-adjacent** — top-down roguelike weapons, armor, potions, scrolls, monsters, dungeon walls/floors. Same readability constraints as Tibia items.
- Why #1: only bank that is simultaneously true-32x32, thousands of items, CC0, and top-down dungeon aesthetic. Use as primary donor alongside OTSP.

### 2. Liberated Pixel Cup (LPC) collection — biggest coherent 32x32 set
- URLs: https://github.com/OpenGameArt/LiberatedPixelCup · curated mirror https://github.com/Lenore-Code/LPC-Asset-Collection · browser https://lpc.opengameart.org/
- License: **CC-BY-SA 3.0 + GPL-3.0 dual** — permissive but **copyleft**
- Size: **thousands** (characters, clothes, weapons, furniture, terrain, buildings), **32x32px native**
- Format: PNG spritesheets/tilesets, git clone / zip, no login
- Style: generic top-down JRPG, brighter/cleaner palette than Tibia, but proportions match.
- Why #2: best coverage for grounds/furniture/outfit parts. Caveat: ShareAlike means reskins derived from it should stay share-alike — fine for open reskin, bad if you ever want proprietary distribution.

### 3. 32rogues by Seth — closest readability philosophy
- URL: https://sethbb.itch.io/32rogues
- License: **custom permissive, NOT CC** — commercial + non-commercial OK, modify OK, credit appreciated; **no redistribution/resale, no NFT/blockchain, no AI/ML use**
- Size: **~130+ and growing**: 50+ humanoids/monsters, 80+ animals, plus tiles/items/palette-swapped weapons (v0.5.0, 72 kB)
- Format: **32x32 PNG** + TMX sample, itch "name your own price $0", no account needed
- Style: **Tibia-like**: deliberately simple/high-readability top-down roguelike sprites.
- Why #3: style + size match is excellent, but no-redistribution clause makes it a **visual donor / repaint reference**, not something to repack verbatim.

### 4. Kenney Roguelike/RPG + Tiny Dungeon + Caves & Dungeons — safest legal bet
- URLs: https://kenney.nl/assets/roguelike-rpg-pack (1700 files) · https://kenney.nl/assets/tiny-dungeon (130+ sprites) · https://kenney.nl/assets/roguelike-caves-dungeons (520 files)
- License: **CC0**
- Size/format: individual PNGs + sheets + Tiled samples, direct zip from kenney.nl or itch mirror (e.g. https://kenney-assets.itch.io/tiny-dungeon), no login
- Style: generic RPG, clean flat shading. **Caveat: 16x16 native** — needs 2x nearest-neighbor upscale to 32x32 + outline/shade pass to sit next to Tibia sprites.
- Why #4: zero legal risk, huge prop/furniture/item variety. Best for crates, chests, doors, dungeon props rather than weapons.

### 5. Super Epic Weapons Fantasy Pack (babysamurai) — weapon donor pool
- URL: https://opengameart.org/content/super-epic-weapons-fantasy-pack-free
- License: **CC0** (author explicitly removed a no-resale stipulation in comments to make it pure CC0)
- Size: **50 weapons, 32x32px**
- Format: single PNG sheet, direct download (OGA download works without account for files)
- Style: generic fantasy with glow variant; more saturated than Tibia but silhouettes transfer well to swords/axes.
- Why #5: small, focused, zero-friction sword/axe/club donor set.

### 6. CC0 Shield Icons aggregator (AntumDeluge) — shield donor pool
- URL: https://opengameart.org/content/cc0-shield-icons
- License: **CC0** (aggregates DCSS, OpenClipart, Cethiel, LordNeo, knik1985, ScratchIO sources; per-set zips)
- Size: **dozens of shields, 32x32 base + 48x48/64x64 variants** in some subsets
- Format: multiple PNG zips, direct download
- Style: mixed, mostly top-down/front icons — good enough for Tibia shield silhouettes.
- Why #6: solves one Tibia slot (shields) in one page. Pair with #5 for equipment coverage.

### 7. itch.io free 32x32 item pool (Nikoichu + SODA et al.) — bulk generic items
- URLs: https://nikoichu.itch.io/ (Crafting Materials FREE 32x32: 25 free / 100+ premium; Tutti Frutti fruits/veg; 1-bit icons) · discovery via `itch.io/game-assets/tag-32x32` and `tag-items`
- License: **mixed per-page** — typically "free for commercial + credit, no redistribute/resell, no AI" (read each page; NOT uniformly CC0/CC-BY)
- Size: 25–250 icons per pack depending on pack
- Format: individual **32x32 PNGs**, itch $0 download, usually no login
- Style: generic RPG, ¾ top-down in several packs (e.g. Wish drinks pack uses Endesga32, same family as Tibia shading).
- Why #7: best volume for food/potion/crafting-material reskins. Treat as **per-pack license check required**.

### 8. Future 64x64 creature/outfit work — Kiovenn + itch 64x64 hub
- URLs: https://opengameart.org/content/64x64-creature-sprites (Kiovenn, 10 creatures, **CC-BY 4.0**, PNG zip, direct) · hub https://itch.io/game-assets/tag-64x64/tag-monsters (e.g. "84 Free RPG Beings and Monsters" 64px by CodeSpree, FREE Monster Pack 64x64 animated by miks — check per-page license)
- License: Kiovenn is clean CC-BY 4.0; itch 64x64 packs are mixed free-commercial, verify each.
- Size: 10–84 creatures per pack, **64x64 (or 48x48)**, PNG sheets, several animated
- Style: generic fantasy monsters, front/side views — right scale for Tibia 2x2-tilename creatures and outfit studies.
- Why #8: only entry at 2x scale; do not downscale into 32x32 item work, reserve for creatures/outfits.

## Explicitly NOT usable as open donors

Found but excluded on licensing grounds:

- `github.com/muriloricci/tibia-sprites` (7.0/7.1 grids), `github.com/JoanaBLate/tibia-sprite-extractor` + `sprites.tar.gz`, most OTLand `.spr/.dat` releases, TibiaFans downloads: **CipSoft-copyrighted rips**. Free download ≠ open license. Useful only as style reference / ID mapping, not as republicable donors.
- `tibiafanart.com/sprites`, `/players-sprites`: states **all rights belong to authors**, use prohibited.
- No open pack named "Loop sprites" found. If you mean an OTLand user named Loop, their releases are CipSoft derivatives — same exclusion. If you have a URL I can vet that specific page.

## Practical take

For 32x32 Tibia items: pull bulk from **#1 (DCSS) + #2 (LPC)**, weapons/shields from **#5 + #6**, props from **#4 (upscale 2x)**, fills from **#7**, with **#3** as readability reference. Reserve **#8** for the 64x64 creature phase.

---

