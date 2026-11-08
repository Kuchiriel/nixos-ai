# HD STORAGE sweep (@explore subagent)

- **sessão:** `ses_f30930ce1ffe86wqCqhV9dlQrN`
- **quando:** 2026-09-23 18:00 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 30 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Inventário focado em /run/media/nixos/YUMI/STORAGE/ (HD externo, read-only, NÃO mover/criar/deletar nada):
1. Liste 1 nível de cada subpasta (Arquivos Compactados, Documentos, Empresas, Imagens, Pessoal, Projetos, Scripts, Tools, Users, Vídeos) + tamanho de cada uma (du -sh, uma pasta por vez para não travar o USB).
2. Em STORAGE/Projetos, STORAGE/Tools, STORAGE/Scripts, STORAGE/Empresas desça 2 níveis: o que é código (linguagem? README?) vs instaladores vs docs.
3. Procure nomes de arquivo com: servicenow, credential, vault, otserver, canary, tibia, wurm, bot, resolver (Glob por padrão de nome, NÃO conteúdo).
REGRAS: só nomes e tamanhos, NUNCA conteúdo (segredos/NDA). Pule MÍDIA/BACKUPS. Volte relatório compacto: o que há de aproveitável (código/produtos) por path, e tamanhos.

---

## · ?

Inventário HD externo `YUMI` — somente nomes+tamanhos, sem abrir conteúdo. Read-only, nada movido/criado.

### 0. Correção de path

* Pedido: `/run/media/nixos/YUMI/STORAGE/` → **vazio, 128K, 0 entries** (`du -sh` ok).
* Dado real está na raiz `/run/media/nixos/YUMI/` (exFAT 931G, `sda1`). Nomes com case diferente do pedido: `DOCUMENTOS` (=Documentos), `PROJETOS` (=Projetos). Abaixo é raiz.

### 1. Nível 1 + `du -sh` (uma pasta por vez)

| Pasta disco | `du -sh` | Nível 1 (resumo) |
|---|---|---|
| `Arquivos Compactados/` | **4,2G** | 3 arqs: `Kuchiriel Crypter.zip`, `NotUnique.rar`, `Técnico.7z` |
| `DOCUMENTOS/` | **11G** | 54 entries: `AI Mode/`, `Alexandre/`, `AllCare/`, `Aspirador/`, `clone/`, `contratos/`, `CURRICULOS/`, `DADOS/`, `DarackGov Telegram Bot/`, `DiscordChatExporter*`, `Dungeons and Dragons Online/`, `EVE/`, `FINANCEIRO/`, `GodsOnline/`, `JURIDICO/`, `LEGADO/`, `LLM/`, `MEDICO/`, `OpenSCAD/`, `PAWL/`, `PESSOAL/`, `Porto Seguro/`, `Rufus/`, `Vortex/`, `Wurm Ultimate - Copia/` + `.iso/.pptx/.scad/.stl/.xlsm/.md` soltos |
| `Empresas/` | **13G** | 12 dirs: `Ailos/`, `Aoop/`, `BancoBV/`, `Brick Abode/`, `Cielo/`, `Fazenda da Mata/`, `Sonda/`, `SpotDev/`, `Stefanini/`, `Vivo/`, `Zion/`, `µTech/` |
| `Imagens/` | **8,2G** | 51 entries — MÍDIA, detalhe pulado por regra. Inclui `AllCare/`, `GodsOnline/`, `Lucas Fotos/`, `RPG/`, `wurm.png` etc. |
| `Pessoal/` | **TIMEOUT >280s** (árvore gigante, não trava mais) | 23 entries: `CAD-STL/`, `DATABASES/`, `Documentos/`, `Games/`, `Gunsmithing/`, `Impressora 3D/`, `Inteligencia/`, `PDFs/`, `Planilhas/`, `TXTs/`, `Vídeos/` + `kaggle.json`, `SIEM.p7b/.pem`, `seed for svelte project.sh`, zips WhatsApp |
| `PROJETOS/` | **TIMEOUT >60s** (85 dirs topo) | ver §2. Sub-medidos: `PESQUISA/OTServer_UPGRADE 12G`, `PRODUTOS/guia_renamer 1,7G`, `PRODUTOS/MuDreamNotifier 199M`, `PRODUTOS/Wurm Ultimate 5,9M`, `Bot 5,7M` |
| `Scripts/` | **19M** | 8: `audit.ps1`, `Compact-WSL.ps1`, `optimize-gaming-hyperv.ps1`, `post-install.cmd`, `Reverter.ps1`, `MSMG-TOOLKIT-GUIA-DEFINITIVO.md`, `EEGPUPV/`, `IEGPUPV/` |
| `Tools/` | **25G** | 6: `Toolkit_v13.7/`, `VDOT/`, `winiso-5.3/`, `config.yaml`, `rufus.ini`, `unblock_notifications.reg` |
| `Users/` | **46M** | 3: `Default/`, `Kuchiriel/` (perfil Win: `NTUSER.DAT*`, `AppData/`), `desktop.ini` |
| `Vídeos/` | **100M** | 1 arq: `Heads Up.mp4` — MÍDIA, sem descer |

Pulados por regra: `BACKUPS/` (enorme, `MANJARO_EXTRACTED/`), `MÍDIA/`, `LIXO/`, `$RECYCLE.BIN`, `System Volume Information/`, `ventoy/`, `YUMI/`.

### 2. Nível 2 — `PROJETOS` / `Tools` / `Scripts` / `Empresas`: código vs instalador vs docs

**`Empresas/` (código aproveitável):**
* `Ailos/` (5): `nbkp.js`, `restuser.ps1`, `send_snow.sh`, `send_snow_mid.sh`, `json.json` — **código ServiceNow MID**.
* `Aoop/` (25, **4,6G**): `AoopJAMFUtils.js`, `compare groups.js`, `nb.js` + `CredentialResolver/` (Gradle Java: `.gradle/`, `app/`, `settings.gradle.kts`, `generate_jar.sh`, `SenhaSeguraBig.jar`, `CredentialResolver_20-09-2022.rar`) + `ServiceNow/` (docs: `CSA/`, `Senha Segura.pdf`) + `50 - Clientes/0102 - Suzano/.../Credencial/discovery_credentials_*.xml` (8 arqs) — **código+docs, com segredo nominal, não aberto**.
* `BancoBV/` (1): `JamfUtils.js` — código.
* `Cielo/` (**3,9M**, 18): `CertTest.ps1`, `NetWorkTestMidTovCenter*.ps1`, `discovery_range_item.csv`, `*.txt` (EVO/HML/PROD/vCenter/VMWARE), `Network Test Cielo/` — código+infra docs.
* `Sonda/` (7): `botbkp01.inventario`, `Técnico/`, `Desktop/` — docs/inventário.
* `SpotDev/` (11): `crawler.sh`, `STL/`, `lixo/` + `*.txt` — código.
* `Stefanini/` (**1,5G**, 19): `PoweredOffDate.ps1`, `docker-stuff/`, `docker-stuff.rar`, `alexanderzobnin-grafana-zabbix-2219691/`, `ONTAP-MIB/` + `*.txt/.conf` (`COFRE.txt`, `DMZ.txt`, `ESX.txt`, `VM-HOSTESX*.txt`) — código+infra.
* `Vivo/` (3): `CredentialResolver/` (Gradle Java completo: `app/`, `gradle/`, `gradlew*`, `settings.gradle.kts`, `resources/`, `debug.ps1`) + `CredentialResolver.rar` + `SenhaSegura2.bpm` — **código produto**.
* `Zion/` (1): `Contratos/` — só docs. `Brick Abode/` (1 txt entrevista), `Fazenda da Mata/` (`Artes/`, `Engenharia/`, `Ovos/`), `µTech/` (`Games/`, `Imagens/`, `Produtos/`, `Serviços/`) — sem código.

**`Scripts/` (19M, código Win/Hyper-V):**
* `EEGPUPV/` (13, `.git/` + `README.md`): `Add-VMGpuPartitionAdapterFiles.psm1`, `CopyFilesToVM.ps1`, `PreChecks.ps1`, `Update-VMGpuPartitionDriver.ps1`, `VMScripts/`, `User/`, `autounattend*.xml` — código GPU-PV.
* `IEGPUPV/` (6, `.git/` + `README.md`): `GPUP-management.ps1`, `VMScripts/`, `misc/` — código.
* Soltos: `*.ps1`, `post-install.cmd`, `*.md` — código/docs.

**`Tools/` (25G, quase tudo instalador):**
* `Toolkit_v13.7/` (19): `Bin/`, `Drivers/`, `DVD/`, `ISO/`, `Packs/`, `Updates/`, `WHD/`, `Toolkit.cmd`, `Start.cmd` — **instalador MSMG, não código**.
* `VDOT/` (8, `README.md`): `Windows_VDOT.ps1`, `VDOT_WhatIf.ps1` — **código MS**.
* `winiso-5.3/` (2): `winiso53.exe` — instalador.

**`PROJETOS/` (85 topos, seleção produto/código):**
* `PRODUTOS/guia_renamer/` (**1,7G**): `main.py`, `pyproject.toml`, `requirements.txt`, `core/`, `ui/`, `supabase/`, `setup_supabase.sql`, `tests/`, `docs/`, `BUILD.md`, `README.md`, `GuiaRenamerPro.spec`, `build/`, `dist/`, `landing/` — **produto Python ativo**.
* `PRODUTOS/Wurm Ultimate/` (**5,9M**): `main.py`, `pyproject.toml`, `requirements.txt`, `core/`, `detection/`, `gui/`, `macros/`, `utils/`, `wurm_config.json` + 2 PDFs guia — **produto Python**.
* `PRODUTOS/MuDreamNotifier/` (**199M**): `mudream_notifier.py`, `license_generator.py`, `pyproject.toml`, `MuDreamNotifier.spec`, `README.md`, `CLAUDE.md`, `build/`, `dist/`, `dist_obf/` — **produto Python**.
* `PESQUISA/OTServer_UPGRADE/` (**12G**): `canary/`, `canary-fresh/`, `canary-backups/`, `otclient-mehah*/` (`mods/game_bot/bot.lua`, `data/images/*`), `tibia-captures/`, `tibia-15.13-analysis/`, `tibia-15.20-analysis/`, `tibia-reverse-eng-tools/` (`*.sh`, `*.py`), `TibiaAPI/`, `docs/`, `*.md` (`CLAUDE.md`, `MASTER_PROTOCOL_STATE.md`), `*.bin`, `*.log` — **código C++/Lua/Python pesquisa Tibia/Canary**.
* `Bot/` (**5,7M**): `package.json`, `svelte.config.js`, `vite.config.js`, `src/`, `tests/` + `README.md` — **código SvelteKit**.
* `PESQUISA/AI_SYSTEM/`, `PESQUISA/LLM/`, `CONSULTORIA/` (espelho de `Empresas/`), `TOOLS/` (`*.ps1`, `*.py`), `Docker/` (`Asterisk/`, `Game Servers/`), `Python/` — código.
* Instaladores/docs puros: `VR/rookie_*.portable/`, `TOOLS/Tools/Toolkit_v13.7/DVD/`, `Godot_v4.8-dev2_mono_win64/` (em DOCUMENTOS), `BombCrypto/bot-bomb-multiaccount.zip`, `Samaritan.zip`.

### 3. Busca por nome (Glob, sem conteúdo) — fora `BACKUPS/MÍDIA`

* `servicenow`: `Empresas/Aoop/ServiceNow/**`, `Empresas/Aoop/50 - Clientes/0100 - BV/.../GCP_servicenow-prd-*.json`, `.../0102 - Suzano/.../servicenow-subscription-unit-overview.pdf`, `Empresas/Ailos/send_snow*.sh`, espelhos em `PROJETOS/CONSULTORIA/Aoop/...`
* `credential`: `Empresas/Aoop/50 - Clientes/0102 - Suzano/.../Credencial/discovery_credentials_*.xml` (8x), `PROJETOS/CONSULTORIA/Aoop/...` (espelho), `PROJETOS/TOOLS/.../credential-manager-*.man` (só manifest Toolkit)
* `vault`: **nada** fora BACKUPS/Toolkit (`Toolkit_v13.7/.../vault-replacement.man` só manifest)
* `otserver`: `PROJETOS/PESQUISA/OTServer_UPGRADE/jarvis-otserver.log`, `.../tibia-reverse-eng-tools/sh/tibia-auto-login-otserver`, `.../scripts/archive_historical/jarvis-otserver.bak`, `PROJETOS/PESQUISA/AI_SYSTEM/jarvis/plugins/otserver.sh`
* `canary`: `PROJETOS/PESQUISA/OTServer_UPGRADE/canary/` + `canary-fresh/` + `canary-backups/` (todo resto `*canary*` está em `BACKUPS/`, ignorado)
* `tibia`: `PROJETOS/PESQUISA/OTServer_UPGRADE/tibia-*/**`, `DOCUMENTOS/GodsOnline/Client/13.10.12892/bin/tibia+127.0.0.1_8080.exe` (resto em BACKUPS, ignorado)
* `wurm`: `PROJETOS/Wurm Ultimate/wurm_config.json`, `PROJETOS/PRODUTOS/Wurm Ultimate/wurm_config.json`, `DOCUMENTOS/Wurm Ultimate - Copia/wurm_config.json`, `DOCUMENTOS/Aspirador/Old/wurm_*.json`, `Imagens/wurm.png`
* `bot`: `PROJETOS/Bot/bootstrapbot.sh`, `PROJETOS/fuckyousenspark/BombCrypto/**/bot.py|bot.ts|telegram_bot.py`, `PROJETOS/BombCrypto/bot-bomb-multiaccount.zip`, `PROJETOS/PESQUISA/OTServer_UPGRADE/otclient-mehah*/mods/game_bot/bot.lua`, `PROJETOS/KIA All/**/botEngine.js|bot.js`, `PROJETOS/termux-assistant/*bot.sh`, `PROJETOS/CONSULTORIA/Sonda/botbkp01.inventario`
* `resolver`: `Empresas/Aoop/CredentialResolver/**`, `Empresas/Vivo/CredentialResolver/**`, `Empresas/Stefanini/Servidores/sambaresolver.txt`, `.../resolver incidente bkp-snap.txt`, `PROJETOS/Docker/Asterisk/.../resolver_unbound.conf.sample`

### 4. Aproveitável (código/produtos) — compacto

* `PROJETOS/PRODUTOS/guia_renamer` 1,7G — Python+Supabase, `README/BUILD.md`, `tests/` — **top produto**.
* `PROJETOS/PRODUTOS/Wurm Ultimate` 5,9M + `PROJETOS/Wurm Ultimate` — Python macros — **produto**.
* `PROJETOS/PRODUTOS/MuDreamNotifier` 199M — Python+licenças — **produto**.
* `PROJETOS/PESQUISA/OTServer_UPGRADE` 12G (`canary/`, `otclient-mehah*/`, `tibia-reverse-eng-tools/`) — C++/Lua/Python Tibia — **pesquisa valiosa, pesada**.
* `PROJETOS/Bot` 5,7M — SvelteKit — código.
* `Empresas/Aoop/CredentialResolver` + `Empresas/Vivo/CredentialResolver` — Java/Gradle + `.jar` — **produto credencial (não abrir, NDA/segredo)**.
* `Empresas/Ailos/send_snow*.sh`, `Empresas/Cielo/*.ps1`, `Empresas/Stefanini/*.ps1`, `Scripts/EEGPUPV|IEGPUPV/*.ps1`, `Tools/VDOT/*.ps1` — automação Win/ServiceNow/Hyper-V — código.
* `DOCUMENTOS/GodsOnline/Client/.../tibia+*.exe`, `DOCUMENTOS/Aspirador/` — clientes/jogos, sem código novo.

Nada foi aberto/lido por dentro; `Pessoal/` e `PROJETOS/` totais não couberam em `du` no USB — medir subpastas isoladas se precisar.

---

