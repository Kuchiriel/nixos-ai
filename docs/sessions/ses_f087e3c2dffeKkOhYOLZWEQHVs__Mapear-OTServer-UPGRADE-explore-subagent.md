# Mapear OTServer_UPGRADE (@explore subagent)

- **sessão:** `ses_f087e3c2dffeKkOhYOLZWEQHVs`
- **quando:** 2026-10-01 12:47 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 8 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No modo PLAN (somente leitura, NÃO edite nada, NÃO rode git pull/push, NÃO crie arquivos), faça inventário completo de /home/nixos/projects/OTServer_UPGRADE.

Retorne:
1. Para cada subdiretório de primeiro nível (canary/, canary-fresh/, canary-backups/, archive/, docs/, scripts/, tools/, www/, protocol/, tibia-*-analysis/, tibia-reverse-eng-tools/, otclient-mehah/, otclient-mehah-clean/, TibiaAPI/, open-tibia-server-deployment-configs/, forensics/, ipc/, tests/, cmake/, Tibia/, Tibia-15.13-Launcher/, etc): o que é, tamanho aproximado (ls/ du -sh), quantos arquivos, e se parece lixo, backup duplicado, ou tesouro aproveitável.
2. Liste arquivos .md raiz mais importantes (CLAUDE.md, AGENTS.md, RECOVERY_ANCHOR.md, MASTER_PROTOCOL_STATE.md, JARVIS_INTEGRATION.md, IPC_GUIDE.md, AI_CONSOLIDATION_PLAN.md, etc) com resumo de 1 linha cada.
3. Procure especificamente: dicas build, singleton, integração com web (www/, AAC?), certificados (key.pem, certs, RSA patch_rsa.py, login_*.bin), descobertas rev eng (protocol/, tibia-captures/, login_payload, forensics/, MASTER_PROTOCOL_STATE.md).
4. Liste repos de client modificados (otclient-mehah, otclient-mehah-clean, Tibia/, client.patched.work, launch_patched_client.sh) — qual upstream provável (edubart/otclient, mehah/otclient,otland?) e que customizações parecem existir.
5. Liste repos canary duplicados dentro (canary/ vs canary-fresh/ vs canary-backups/) — são clones outdated? qual commit/versão aproximada vs oficial?
6. Liste scripts/ferramentas consolidáveis (scripts/, tools/, consolidate_gemini.sh, etc).

Seja conciso mas completo. Não modifique nada.

---

## · ?

Inventário PLAN (somente-leitura, nada modificado/criado, nenhum `git pull/push`):

Total: `3,2G` em `/home/nixos/projects/OTServer_UPGRADE/` — 68 entradas raiz.

### 1. Subdiretórios 1º nível: o que é / tamanho / arquivos / veredito

| Dir | `du -sh` / `find|wc -l` | O que é | Lixo / Backup / Tesouro |
|---|---|---|---|
| `/home/nixos/projects/OTServer_UPGRADE/canary/` | `1,1G`, 6955 arqs | Workdir Canary ativo + `build/`, `canary` binário, `recompile.sh`, `config.lua`, `data-canary/`, `data-otservbr-global/`, `key.pem`, `server_output.log` + dezenas `server_*.log`, `forensics_knowledge/` | **Tesouro ativo, inchado**: fonte + artefatos build/logs. Manter, limpar `*.log*`, `build/` |
| `/home/nixos/projects/OTServer_UPGRADE/canary-fresh/` | `131M`, 6004 arqs | Clone limpo `opentibiabr/canary` + `apply.patch`, `recompile.sh`, `start.sh`, `key.pem` | **Tesouro-referência**: diff-base para `canary/`. Manter |
| `/home/nixos/projects/OTServer_UPGRADE/canary-backups/` | `550M`, 11916 arqs | ~30 snapshots: `milestone-*`, `20260114_*`, `20260115_*`, `20260122_*AUTO_SUCCESS`, `MARCO_31_*`, `*.bak` (`connection.cpp/hpp`, `CMakeLists.txt`, `protocol_15_20.cpp`) | **Backup duplicado**: útil rollback, mas 550M. Manter 2-3 últimos, resto p/ storage externo |
| `/home/nixos/projects/OTServer_UPGRADE/archive/` | `30M`, 223 arqs | `docs_v1/` (15 docs 2025-12), `pre-organization-backup-20251222/`, `historical/*.sh`, `code_backups/protocolgame_backup.cpp`, `forensics/*.py` (~50 `brute_*`, `decrypt_*`, `analyze_*`) + `forensics/data/` | **Backup histórico + tesouro forense**: não apagar, não usar no build |
| `/home/nixos/projects/OTServer_UPGRADE/docs/` | `16K`, 4 arqs | `guides/SYSTEM_GUIDE.md`, `guides/AI_ORCHESTRATION.md`, `protocol/MASTER_PROTOCOL.md`, `roadmaps/PROJECT_STATE.md` | **Tesouro**: docs canônicos novos, minúsculos |
| `/home/nixos/projects/OTServer_UPGRADE/scripts/` | `388K`, 48 arqs | `core/{ipc-v2.sh,ai-orchestrator-api.py,packet_decoder.py,context-limit-handler.sh}`, `dev/{build-canary-*.sh,deploy-canary.sh,forensic-diff.sh,...}`, `maintenance/{start-server.sh,system-state.sh,...}`, `prd/start-server-prd.sh`, `archive_historical/` (12 `.bak` + 5 `*-auto-responder*.sh`), `verify_protocol_milestones.sh`, `check_key*.py` | **Tesouro consolidável**: lógica OTServer real, mas duplicada. Ver §6 |
| `/home/nixos/projects/OTServer_UPGRADE/tools/` | `16K`, 4 arqs | Só `fix-cmake-for-system-packages.sh` + resto vazio | **Quase-lixo**: manter 1 script, fundir em `scripts/` |
| `/home/nixos/projects/OTServer_UPGRADE/www/` | `8K`, 2 arqs | `loginservice_final.php` (stub login JSON → MySQL `canary.players`, `externaladdress 127.0.0.1:7172`), `accountcreationclientservices.php` | **Tesouro web**: AAC mínima p/ client oficial, sem MyAAC/Gesior full |
| `/home/nixos/projects/OTServer_UPGRADE/protocol/` | `8K`, 1 arq + subdir | `dissectors/tibia_dissector.lua` (5,6K Wireshark) | **Tesouro**: único dissecador |
| `/home/nixos/projects/OTServer_UPGRADE/tibia-15.13-analysis/` | `266M`, 15090 arqs | Lab 15.13: `frida/`, `reversing/`, `protocol/`, `patches/`, `assets/`, `logs/`, `*.pcap`, `extract_xtea*`, `decrypt_*`, `TROUBLESHOOT-XTEA.md`, ~20 `.md` status | **Tesouro inchado**: achados XTEA/opcode + muito log/pcap intermediário. Podar `logs/`, `assets/` |
| `/home/nixos/projects/OTServer_UPGRADE/tibia-15.20-analysis/` | `352K`, 26 arqs | Lab 15.20 atual: `protobuf/`, `opcodes/`, `captures/`, `patches/`, `server/`, `tibia-wss-bridge.js`, `CERTIFICADO-PRONTO2.md`, `SSL_BYPASS_ATTEMPTS.md`, `IMPLEMENTATION_*` | **Tesouro**: pequeno e denso, manter |
| `/home/nixos/projects/OTServer_UPGRADE/tibia-reverse-eng-tools/` | `560K`, 79 arqs | `py/` (~33: `extract-xtea*`, `analyze_protobuf.py`, `patch-tibia-rsa.py`, ...), `sh/` (~46: `capture-*.sh`, `build-and-test-canary*.sh`, `setup-mitmproxy.sh`, `tibia-ssl-bypass.sh`, ...) | **Tesouro consolidável**: toolkit real, nomes duplicados (`test_all_keys` x2, `build-and-test_old`) |
| `/home/nixos/projects/OTServer_UPGRADE/otclient-mehah/` | `69M`, 2775 arqs | Clone OTClient + `recompile.sh`, `data/`, `modules/`, `src/` | **Tesouro-cliente**: workdir modificado. Ver §4 |
| `/home/nixos/projects/OTServer_UPGRADE/otclient-mehah-clean/` | `64M`, 2538 arqs | Mesmo + `config.ini`, sem alguns assets | **Backup-diff**: base p/ `diff -rq`. Manter como referência |
| `/home/nixos/projects/OTServer_UPGRADE/TibiaAPI/` | `152M`, 712 arqs | `TibiaAPI.sln`, `TibiaAPI/`, `ClientData/`, `Apps/`, `items/monsters/npcs.txt` — lib C# TibiaAPI (parse dat/spr/packets) | **Tesouro externo**: não é Canary, é lib rev-eng .NET |
| `/home/nixos/projects/OTServer_UPGRADE/open-tibia-server-deployment-configs/` | `140K`, 22 arqs | `docker-compose.yml`, `Dockerfile.{canary,web}`, `docker/{Dockerfile.*,config.sh,data/01-02-test_account*.sql}`, `nginx-myaac.conf`, `myaac-shop-setup.sql`, `metrics/prometheus/` | **Tesouro deploy**: MyAAC + nginx + docker canary. Única integração web full |
| `/home/nixos/projects/OTServer_UPGRADE/forensics/` | `132K`, 34 arqs | `xtea*.py`, `packet*.py`, `pcap_reader.py`, `bundling_*.py`, `opcode_mapper.py`, `cpp/{protocol.cpp,protocolgame.cpp,parseHeader.cpp}` | **Tesouro**: parsers atuais, distintos de `archive/forensics/` (brute-force velho) |
| `/home/nixos/projects/OTServer_UPGRADE/ipc/` | `80M`, 20501 arqs | Spool multi-agente: `archive/` 79M (~20k `*.msg`), `*_inbox/_outbox`, `agent_registry/state.json`, `URGENT_*.txt` | **Lixo quente**: 99% `archive/` histórico. Código real está em `scripts/core/ipc-v2.sh`, não aqui |
| `/home/nixos/projects/OTServer_UPGRADE/tests/` | `28K`, 7 arqs | `robust-test.sh`, `test-protobuf-handshake.sh`, `automation/{game-login-test.sh,auto-login-test.sh}` | **Tesouro**: harness login/world |
| `/home/nixos/projects/OTServer_UPGRADE/cmake/` | `4K`, 1 arq | `vcpkg-toolchain.cmake` | **Lixo/quase**: 1 shim, fundir |
| `/home/nixos/projects/OTServer_UPGRADE/Tibia/` | `71M`, 47 arqs | Client oficial desempacotado: `Tibia` bin, `lib/`, `plugins/`, `qt.conf` | **Tesouro-binário**: alvo do patch RSA, não fonte |
| `/home/nixos/projects/OTServer_UPGRADE/Tibia-15.13-Launcher/` | `141M`, 98 arqs | Launcher oficial: `Launcher.sh`, `Launcher-improved.sh` (+`.bak`), `lib/libQt6*.so` 68M, `plugins/`, `package.json` | **Backup binário**: só `Launcher-improved.sh` (3,3K, aponta p/ MyAAC `login.php`) é tesouro-legível |
| Extras raiz não-dir | — | `logs/` 8,4M/1986 arqs (client-*.log), `tibia-captures/` 498M/139 arqs, `client.patched.work` 41M ELF, `tibia.x64.tar.gz` 28M, `vcproj/` 48K (Windows `canary.vcxproj`), `temp_disabled_protobuf_helpers/` 28K | `tibia-captures/`=tesouro pcap (ver §3); `logs/`=lixo rotativo; `vcproj/`=lixo salvo se precisar VS |

### 2. `.md` raiz (1 linha cada)

* `AGENTS.md` → symlink → `CLAUDE.md` (fonte única, 177 linhas).
* `CLAUDE.md` / `GEMINI.md` (301 linhas) — protocolo operacional absoluto + verdade 15.20 (framing 6B, XTEA off 159, RSA bypass, `mold/unity/FAST_START=1`, IPC).
* `RECOVERY_ANCHOR.md` — save-game: deletar `headerSize=32` em `canary/.../connection.cpp`, rebuild `recompile.sh dev` + `robust-test.sh`.
* `MASTER_PROTOCOL_STATE.md` — stage 3 bundles, marcos ok + gargalo “client não transita p/ world” (PlayerDataBasic/namespace/item ID).
* `JARVIS_INTEGRATION.md` — voz Whisper + vision Gemini + roteamento Groq/Mistral/Ollama via `ai-orchestrator`.
* `IPC_GUIDE.md` — referência `scripts/core/ipc-v2.sh send/read/state` + resumo framing/bundling.
* `AI_CONSOLIDATION_PLAN.md` / `REORGANIZATION_PROPOSAL.md` — plano tirar IA de `OTServer_UPGRADE/` → `AI_SYSTEM/` + `scripts/otserver/` só-build.
* `GEMINI_REMEMBER.md` — anti-padrões (não criar .md solto, arquivar antes de deletar, checar IPC).
* `GEMINI_TOOLS.md` — use `tibia-re` + `compiler_expert.py`, não adivinhe protocolo.
* `CLAUDE_INVESTIGATION_REPORT.md` — achado crítico: falta wrapper `GameserverMessage` em `tibia_working.proto` (2080 linhas) + namespace misto + map 0x64 embrulhado errado.
* `JOURNAL.md` — log marcos v107.1→world-entry GOD logado.
* `STABILITY_TRACKER.md` — tabela do-não-mude (handshake 14B, header 6B, XTEA pad 2B, compressão OFF).
* `docs/{guides/SYSTEM_GUIDE,guides/AI_ORCHESTRATION,protocol/MASTER_PROTOCOL,roadmaps/PROJECT_STATE}.md` — guias canônicos novos.

### 3. Achados específicos

* **Build:** `cd canary && bash recompile.sh [dev|prd] --start` (`mold`+`ccache`+unity, sem protobuf); `FAST_START=1 bash scripts/maintenance/start-server.sh dev`; validar `./scripts/verify_protocol_milestones.sh`; deploy ref `/var/www/html/canary` via `scripts/dev/deploy-canary.sh` (sincroniza `key.pem`); `tools/fix-cmake-for-system-packages.sh`.
* **Singleton:** `docs/guides/SYSTEM_GUIDE.md:7` + `archive/.../STATUS_UPDATE.md:8` — `boost::di` criava `Database` desconectado em `KVSQL`, fix = bypass DI e usar `Database::getInstance()`; `vcproj/canary.vcxproj` lista `soft_singleton.{hpp,cpp}`.
* **Web/AAC:** `www/loginservice_final.php` + `accountcreationclientservices.php` (stub JSON, sem Gesior/MyAAC full); `Tibia-15.13-Launcher/Launcher-improved.sh:72` aponta p/ MyAAC `login.php`; full MyAAC só em `open-tibia-server-deployment-configs/` (`Dockerfile.web` baixa MyAAC, `nginx-myaac.conf`, `myaac-shop-setup.sql`, `docker-compose.yml:79` nginx+PHP-FPM).
* **Certs/RSA:** `canary/key.pem` + `canary-fresh/key.pem` (RSA OT `9B64...B5FF`); `patch_rsa.py` troca modulus CipSoft `BC27...B1949` → OT no binário; `login_request.bin` 262B / `login_request_stripped.bin` 255B / `login_payload.bin` 255B / `server_response.bin` 127B na raiz; `tibia-15.20-analysis/CERTIFICADO-PRONTO2.md` + `tibia-15.13-analysis/SETUP-ATUAL.txt` (CA `ca-cert/key.pem`, `server-cert/key.pem`, `/etc/nginx/ssl/tibia.crt`); `SSL_BYPASS_ATTEMPTS.md`, `test-letsencrypt-approach.sh`, `setup-mitmproxy.sh`.
* **Rev-eng:** `MASTER_PROTOCOL_STATE.md` + `docs/protocol/MASTER_PROTOCOL.md`; `protocol/dissectors/tibia_dissector.lua`; `tibia-captures/` 498M (`official_15.20/` 427M: 4 pcaps 5–353M + 2 `*_FORENSIC.md`, `v15.20/` 60M logs canary, `v15.13/` 12M pcaps 23/24-11-2025); `forensics/` + `archive/forensics/` + `tibia-*/analysis/`, `OPCODE_MAPPING_INITIAL.md`, `PROTOCOL_MAPPING.md`.

### 4. Clients modificados

* `otclient-mehah/` vs `otclient-mehah-clean/` — ambos `origin https://github.com/mehah/otclient.git` (fork de `edubart/otclient`, linha `otland`-compatível). `mehah` em `5bbc87d cleanup attachedEffect`, `clean` em `e8008af fix #1596 drawInformation`. `diff -rq` = só assets/UI (`cursors`, `spell-icons`, `panel_*.png`, `checkbox/scrollbar/buttons.otui`, `CMakeLists.txt`, `keyboard_preview`) + `clean:config.ini` extra. Nenhum patch protocolo 15.20 visível no diff superficial — customização parece skin/UX, não `protocolgame` 15.20.
* `Tibia/` 71M — CipSoft oficial intacto (alvo).
* `client.patched.work` 41M ELF x86-64 stripped — binário com RSA trocado via `patch_rsa.py` (path hardcoded `/home/kuchiriel/...`).
* `launch_patched_client.sh` — lança `~/.local/share/CipSoft.../bin/client.patched` sem `strace` (evita anti-debugger), loga em `logs/client-*.log` com filtro anti-`AAAA...`.
* `Tibia-15.13-Launcher/` + `tibia.x64.tar.gz` 28M — launcher Qt6 oficial, só `Launcher-improved.sh` customiza endpoint MyAAC.

### 5. Canarys duplicados

* `canary/` `origin opentibiabr/canary` em `5bdb3799b fix: loot highlight (#3761)` — workdir sujo (1,1G com `build/`, bins, logs).
* `canary-fresh/` mesmo remote em `8f5e949 ignore removed creatures (#3765)` — **4 PRs à frente** do `canary/`, limpo (131M). É a base correta p/ rebase/diff.
* `canary-backups/` 550M — não é clone, é pilha de snapshots manuais (`milestone-v106/v152`, `MARCO_31`, `20260114/15/22_*`). Outdated por definição, valor só como arqueologia/rollback pontual.
* Oficial: ambos desatualizados vs `opentibiabr/canary` atual por dias (3761 vs 3765), não meses. Recomendação: congelar `fresh` como base, `diff -r fresh canary` = patch real 15.20, arquivar `backups/` fora do repo.

### 6. Scripts/ferramentas consolidáveis

Núcleo a manter: `scripts/core/ipc-v2.sh`, `scripts/dev/{build-canary-15.20.sh,build-canary-auto-fix.sh,deploy-canary.sh,apply-phase2-protobuf.sh,forensic-diff.sh,validate-changes.sh}`, `scripts/maintenance/start-server*.sh`, `scripts/{verify_protocol_milestones.sh,run_expert.sh}`, `tests/robust-test.sh`, `tools/fix-cmake-for-system-packages.sh`, `tibia-reverse-eng-tools/py+sh` (captura/patch/opcode/XTEA), `protocol/dissectors/tibia_dissector.lua`, `consolidate_gemini.sh` (só-arquiva, aponta p/ `AI_SYSTEM/`).
Lixo/duplicata: `scripts/archive_historical/` (12 `.bak` + 3 `claude-auto-responder*` + `smart-auto-responder.sh`), `build-canary-auto-fix` vs `build-canary-15.20` vs `canary/recompile.sh`, `test_all_keys` vs `test-all-keys`, `build-and-test-canary` vs `..._old`, `capture-*` ×6, `tibia-15.13-analysis/scripts+tools/` (full_build/auto_build/deploy/backup duplicam `scripts/dev/`). Seguir `REORGANIZATION_PROPOSAL.md`: `scripts/otserver/` (só build/deploy/test) + resto → `AI_SYSTEM/` ou `tibia-reverse-eng-tools/`.

---

