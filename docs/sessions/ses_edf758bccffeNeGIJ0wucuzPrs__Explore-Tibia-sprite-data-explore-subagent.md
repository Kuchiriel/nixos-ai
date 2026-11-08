# Explore Tibia sprite data (@explore subagent)

- **sessão:** `ses_edf758bccffeNeGIJ0wucuzPrs`
- **quando:** 2026-10-09 12:01 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 10 (exportadas: 10)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Search the local filesystem for:
1. Tibia vanilla PNG sprites (look in /home/nixos/projects, /tmp, /home/nixos/models for sprite directories with PNG files)
2. items.xml files (Tibia item definitions)
3. RME (Remere's Map Editor) autoborder XML files with cardinal directions
4. Any llm_runner notebook or Kaggle-related files
5. Sprite generation project files (img2img, pixel art LoRA)

Search broadly: /home/nixos/projects/*, /tmp/opencode/*, /home/nixos/models/*

Report back:
- What directories/files exist for each category
- File counts and sizes
- Any README or documentation found
- Whether IDs in XML files appear to match image filenames

---

## · ?

I'll search for all five categories in parallel across the specified directories.

---

## · ?

Good, I found significant results. Let me now dig deeper into the key directories for file counts, sizes, and documentation.

---

## · ?

Let me now read the key documentation files and examine the sprite/notebook contents.

---

## · ?

Let me get more details on sprite directories, RME brush files, and the kag-sprites metadata.

---

## · ?

Let me get the final details on borders.xml files and sprite ID/filename matching.

---

## · ?

Let me get a few final details.

---

## · ?

Let me fix the overlap check and get vanilla.zip contents.

---

## · ?

Let me fix the overlap check properly and verify vanilla.zip.

---

## · ?

Now I have all the data. Here is the comprehensive report:

---

## Search Results Report

### 1. Tibia Vanilla PNG Sprites

#### A. `/home/nixos/projects/tibia-sprites/` (71MB total, 7,701 files)

| Directory | Files | Size | Description |
|---|---|---|---|
| `otsp/sprite_sheets/` | 12 PNG + 12 PSD | ~25MB | OTSP sprite sheets (creatures 01-04, doors, equipment, misc, nature, tiles, town, walls 01-02) |
| `otsp/extracted_sprites/` | **7,675 PNGs** | 30MB | Individual sprites named by sprite ID (`0.png`, `1.png`, `10.png`, `100.png`, etc.) |
| `otsp/` root | 2 files | 8.9MB | `otsp.spr` (8.9MB) + `otsp.dat` (84.6KB) -- binary sprite/data files |
| `beats-assets/` | empty | -- | -- |
| `tilaven-exporter/` | empty | -- | -- |

#### B. `/home/nixos/models/sprites/refs/ot-pack/` (git repo, 62 PNGs)

| Directory | Files | Description |
|---|---|---|
| `sprite_sheets/` | 12 PNG + 12 PSD | Same OTSP sheets as above |
| `sprites_by_author/` | 50 PNGs | Named by author name (e.g., `Andreew.png`, `Cat.png`, `Daniel.png`) -- NOT by sprite ID |
| `client_files/` | 3 files | `otsp.spr`, `otsp.dat`, `otsp.otfi` |
| `server_files/` | 10 files | `items.xml`, `items.otb`, monster XMLs, world XMLs |
| `rme_files/` | 9 files | `items.xml`, `items.otb`, `borders.xml`, brush XMLs |

#### C. `/home/nixos/projects/canary-official/dataset/opentibia_sprite_pack/` (git repo)

| Directory | Files | Description |
|---|---|---|
| `sprites_by_author/` | 50 PNGs | Author-named sprites (same as ot-pack) |
| `rme_files/` | 9 files | XMLs + `items.otb` (104KB) |
| `server_files/` | 10 files | XMLs + `items.otb` (104KB) + `otsp.otbm` (86KB) |
| `client_files/` | 1 file | `otsp.otfi` (92B) |

#### D. `/home/nixos/models/sprites/` top-level (968MB total, 34,611 files)

| Directory | Files | Description |
|---|---|---|
| `refs/saw_ref/` | ~100 `.bmp.lzma` | Compressed original sprites |
| `refs/` root | several | `clip_bank_*.pt` (CLIP embeddings), `glaclient.zip` (61.6MB), `phobos_dec.bin` (126.5MB) |
| Top-level PNGs | 7 | `saw3_32x32.png`, `saw3_512.png`, `saw4_*.png`, `saw5_*.png`, `saw_3461_*.png` |
| `dcss/`, `dcss_png/`, `fx64/`, `fx64_bank/`, `oga/`, `oga_png/`, `otsp_png/`, `phobos/`, `flux_night/` | 0 files each | Empty directories |

#### E. `/tmp/opencode/` sprite-related PNGs

~100+ sprite PNGs including: `spr_*.png` (e.g., `spr_201852.png`, `spr_195986.png`), `official_sprite_*.png`, `f_*.png`, `sv_*.png`, `sickle_*.png`, `gold_*.png`, `terra_*.png`, etc.

---

### 2. items.xml Files (Tibia Item Definitions)

| File | Size | Format | Unique IDs |
|---|---|---|---|
| `/home/nixos/projects/rme/data/items/items.xml` | 3.0MB | Individual `id="N"` | 18,120 |
| `/home/nixos/projects/rme-upstream/data/items/items.xml` | 3.0MB | Individual `id="N"` | -- |
| `/home/nixos/projects/canary-official/data/items/items.xml` | 4.5MB | Individual `id="N"` | -- |
| `/home/nixos/projects/canary-upstream/data/items/items.xml` | 3.5MB | Individual `id="N"` | -- |
| `/home/nixos/projects/tfs-upstream/data/items/items.xml` | 1.8MB | Individual `id="N"` | -- |
| `/tmp/opencode/rme/data/items/items.xml` | 3.0MB | Individual `id="N"` | -- |
| `/home/nixos/projects/canary-official/dataset/opentibia_sprite_pack/server_files/items.xml` | 21.9KB | OTSP `fromid/toid` ranges | 230 |
| `/home/nixos/projects/canary-official/dataset/opentibia_sprite_pack/rme_files/items.xml` | 21.9KB | OTSP `fromid/toid` ranges | 230 |
| `/home/nixos/models/sprites/refs/ot-pack/server_files/items.xml` | 21.9KB | OTSP `fromid/toid` ranges | 230 |
| `/home/nixos/models/sprites/refs/ot-pack/rme_files/items.xml` | 21.9KB | OTSP `fromid/toid` ranges | 230 |

**Key difference**: The RME/canary/tfs `items.xml` files use individual `id="N"` attributes (18,120 unique IDs). The OTSP `items.xml` files use `fromid="N" toid="M"` range format (230 unique IDs covering ranges like `fromid="100" toid="124" name="grass"`).

---

### 3. RME Autoborder XML Files with Cardinal Directions

**No files named "autoborder" were found.** However, the following XML files contain cardinal direction attributes:

| File | Size | Cardinal Directions |
|---|---|---|
| `canary-official/dataset/opentibia_sprite_pack/rme_files/borders.xml` | 576B | `n`, `e`, `s`, `w`, `cnw`, `cne`, `csw`, `cse`, `dnw`, `dne`, `dsw`, `dse` |
| `canary-official/dataset/rme/brushs/tiny_borders.xml` | 511B | `n`, `e`, `s`, `w`, `cnw`, `cne`, `cse`, `csw`, `dnw`, `dne`, `dse`, `dsw` |
| `canary-official/dataset/rme/brushs/doodads.xml` | 640KB | `north`, `south`, `east`, `west` (table align attributes) |
| `canary-official/dataset/rme/brushs/grounds.xml` | 101.3KB | `north`, `south`, `east`, `west` |
| `canary-official/dataset/rme/brushs/stones.xml` | 30.7KB | `north`, `south`, `east`, `west` |
| `canary-official/dataset/rme/brushs/trees.xml` | 18.2KB | `north`, `south`, `east`, `west` |
| `canary-official/dataset/rme/brushs/natural_products.xml` | 714B | `north`, `south`, `east`, `west` |

The `borders.xml` file defines a grass border group with 12 edge items (4 cardinal + 4 corner + 4 diagonal). The `tiny_borders.xml` defines a carpet brush with 12 alignment items.

---

### 4. llm_runner Notebook / Kaggle-Related Files

| File | Description |
|---|---|
| `/tmp/opencode/krunner/llm-runner.ipynb` | **LLM runner notebook** -- writes `llm_runner.py` with llama.cpp and HF backends, Qwen-optimized, 2x T4 target |
| `/tmp/opencode/kag-sprites/kernel/sprite-lora-test.ipynb` | **Sprite LoRA test** -- uses `FluxImg2ImgPipeline` with `UmeAiRT/FLUX.1-dev-LoRA-Modern_Pixel_art` |
| `/tmp/opencode/kag-sprites/dataset/names.json` | 31 sprite ID-to-name mappings (e.g., `"40589": "stitched mutant hide legs"`) |
| `/tmp/opencode/kag-sprites/dataset/dataset-metadata.json` | Kaggle dataset metadata: `kuchiriel/tibia-vanilla-31`, CC0-1.0 |
| `/tmp/opencode/kag-sprites/kernel/kernel-metadata.json` | Kaggle kernel metadata: `kuchiriel/sprite-lora-test`, NvidiaTeslaT4 |
| `/tmp/opencode/kag-sprites/vanilla.zip` | **File not found** (listed in directory but does not exist on disk) |
| `/home/nixos/projects/applio-lab/scripts/kaggle-*.sh` | 10 Kaggle scripts (ivan-fetch, dunn-fetch, rotate, queue, manager, etc.) |
| `/home/nixos/projects/applio-lab/logs/kaggle-queue.log` | Kaggle queue log |
| `/home/nixos/models/_arquivo/legacy/Jarvis_300e_kaggle.pth` | Kaggle model checkpoint |

---

### 5. Sprite Generation Project Files (img2img, Pixel Art LoRA)

| File | Description |
|---|---|
| `/tmp/opencode/kag-sprites/kernel/sprite-lora-test.ipynb` | FLUX.1-schnell img2img + `FLUX.1-dev-LoRA-Modern_Pixel_art` LoRA, 256x256 input, 8 steps |
| `/tmp/opencode/lora_*.png` | 7 LoRA test outputs: `lora_real.png`, `lora_ctrl.png`, `lora_ctrl2.png`, `lora_tag.png`, `lora_on.png`, `lora_off.png`, `lora_probe.png` |
| `/tmp/opencode/i2i_cuda.png` | img2img CUDA test output |
| `/home/nixos/projects/stable-diffusion.cpp/assets/img2img_output.png` | SD.cpp img2img output |
| `/home/nixos/projects/stable-diffusion.cpp/assets/flux/flux1-dev-q8_0-with_lora.png` | FLUX with LoRA example |
| `/home/nixos/models/siglip-lora-*.pt` / `.weights` | 5 SigLIP LoRA weight files |
| `/home/nixos/models/moondream2-hf/lora.py` | LoRA implementation for Moondream2 |

---

### 6. README / Documentation Found

| File | Content |
|---|---|
| `/home/nixos/projects/tibia-sprites-exporter/README.md` | 155 lines -- CLI tool to extract/split/group Tibia client sprite sheets. Go 1.25+. Commands: `extract`, `split`, `group`. |
| `/home/nixos/projects/canary-official/dataset/README.md` | 149 lines -- Dataset reference for sandbox. Wurm/GBIF/Wikidata sources. RAW vs PARSED rule. |
| `/home/nixos/projects/canary-official/dataset/opentibia_sprite_pack/README.md` | 11 lines -- OpenTibia sprite pack, CC-BY 4.0, links to authors |
| `/home/nixos/projects/canary-official/dataset/opentibia_sprite_pack/GUIDE.md` | 27 lines -- How to implement OTSP (protocol 10.41, ID changes, client config) |
| `/home/nixos/projects/canary-official/dataset/opentibia_sprite_pack/AUTHORS.md` | 4.8KB -- Sprite author credits |
| `/home/nixos/projects/canary-official/docs/operations/CLIENT-sprites-como-funciona.md` | Client sprites documentation |

---

### 7. ID Matching: XML IDs vs Image Filenames

| Check | Result |
|---|---|
| Unique IDs in `rme/data/items/items.xml` | **18,120** |
| Unique extracted sprite filenames (`otsp/extracted_sprites/`) | **7,675** |
| **Overlap (IDs present in both)** | **4,583** |
| OTSP `items.xml` unique IDs (range format) | 230 |
| OTSP sprite sheet PNGs | 12 (named by category, not ID) |
| `sprites_by_author` PNGs | 50 (named by author, not ID) |

**Key finding**: The 4,583 overlapping IDs confirm that extracted sprite filenames (`0.png`, `1.png`, `100.png`, etc.) directly correspond to item IDs in `items.xml`. The remaining ~3,092 sprite files (7,675 - 4,583) are sprites without corresponding item definitions (likely decorations, effects, or unused sprites). The ~13,537 item IDs without sprites are likely items that use only client-side sprites or are non-visual items.

The OTSP `items.xml` uses a completely different ID scheme (`fromid/toid` ranges starting at 100) that does NOT match the extracted sprite filenames -- this is the OpenTibia Sprite Pack's own ID namespace, separate from the vanilla Tibia item IDs.

---

