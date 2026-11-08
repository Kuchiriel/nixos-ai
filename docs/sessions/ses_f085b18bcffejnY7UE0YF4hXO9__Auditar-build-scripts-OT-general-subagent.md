# Auditar build scripts OT (@general subagent)

- **sessão:** `ses_f085b18bcffejnY7UE0YF4hXO9`
- **quando:** 2026-10-01 13:26 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 8 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Somente LEITURA, não modifique nada. Compare scripts de build do OTServer lab vs upstream limpo vs oficial atual:

Arquivos (diffs já medidos):
- /home/nixos/projects/OTServer_UPGRADE/canary/recompile.sh vs ../canary-fresh/recompile.sh (203 linhas de diff) vs /home/nixos/projects/canary-official/recompile.sh
- canary/CMakeLists.txt vs canary-fresh (35 linhas) ; canary/src/CMakeLists.txt (22) ; canary/src/protobuf/CMakeLists.txt (107) ; canary/src/server/CMakeLists.txt (8)
- /home/nixos/projects/OTServer_UPGRADE/tools/fix-cmake-for-system-packages.sh (só existe no OT)
- /home/nixos/projects/OTServer_UPGRADE/scripts/dev/build-canary-*.sh, scripts/maintenance/start-server.sh (FAST_START), canary/config.lua se existir
- Checar menções a mold, ccache, unity build, protobuf on/off, vcpkg, MAKEFLAGS/paralelismo

Retorne TABELA compacta: arquivo | o que o OT mudou (1-2 linhas) | já existe no oficial atual? (sim/não/parcial) | veredito PORTAR / ADAPTAR / IGNORAR + motivo em 1 linha. Máx 40 linhas no total. Não modifique nada.

---

## · ?

| arquivo | o que o OT mudou | no oficial atual? | veredito + motivo |
|---|---|---|---|
| `canary/recompile.sh` | Jogou fora vcpkg/preset/progresso; hardcode `/home/kuchiriel/.../build-ninja`, `ninja -j14`, `sudo nice/pkill`, deploy `/var/www/html`, backup `rsync canary-backups` retenção 5 | Não — oficial tem 451 linhas: `--jobs`, `CMAKE_BUILD_PARALLEL_LEVEL` (def. 2), dry-run ninja, SHA256 decide instala, `backups/executables` 7d, `--restart-service` | **IGNORAR** — paths/sudo hardcoded; oficial já cobre jobs+backup melhor |
| `canary/CMakeLists.txt` | Moveu `CMAKE_MODULE_PATH` p/ topo + `find_package(absl REQUIRED CONFIG COMPONENTS stacktrace)` incondicional + `option(BUILD_TESTING)` | Parcial — ccache/sccache herdados, mas oficial tem `CMP0156/0179`, `VCPKG_BUILD_TYPE` cache, `SharedBuildCache`, `CANARY_MSVC_NINJA`, `mbedtls` (não `mpir`) | **IGNORAR** — `find absl` incondicional quebra vcpkg; se precisar system-libs, refazer condicional via Nix, não portar |
| `canary/src/CMakeLists.txt` | `include_directories(third_party/BS_thread_pool, atomic_queue)` + `DEBUG_LOG` global | Não | **IGNORAR** — vendoring local + define global; só via patch Nix se preciso |
| `canary/src/protobuf/CMakeLists.txt` | Reescrita total: `protobuf_lib`, `/usr/bin/protoc` hardcoded, sem `protobuf_generate`, links `absl_log_*` manuais, `UNITY_BUILD OFF`, `GOOGLE_PROTOBUF_NO_RTTI=1` | Não — oficial/fresh usam `protobuf_generate` + `libprotobuf-lite` (oficial só trocou `libprotobuf`→`-lite`) | **IGNORAR** — protoc absoluto + pin absl frágil quebram Nix/vcpkg |
| `canary/src/server/CMakeLists.txt` | +6 `.cpp`: `protocolgame_{send,parse,helper,helpers}`, `protocol_15_20`, `protobuf_helper` | Não | **ADAPTAR c/ código** — não é build, é feature 15.20 proprietária; só se portar o protocolo |
| `tools/fix-cmake-for-system-packages.sh` | Script awk one-shot que injeta `find_package(absl)` condicional + backup sem limpeza | Não (oficial é vcpkg-manifest puro) | **IGNORAR** — mutante, já divergente do CMakeLists atual; Nix faz via overlay |
| `scripts/dev/build-canary-*.sh` | `build-15.20`: GCC14, `SPEED_UP_BUILD_UNITY=OFF`, `make protobuf`+`make -j$(nproc)`, `chown http:http`; `auto-fix`: cria `FindAsio.cmake`, `sed` BaseConfig, lista deps Arch | Não | **IGNORAR** — paths absolutos + `make` vs preset/ninja; Unity OFF era só workaround de conflito namespace |
| `scripts/maintenance/start-server.sh` | `FAST_START=1` prefixo + `fuser/pkill`, rotação log, `nohup setsid`, poll `Canary server online!` | Não — oficial usa `--restart-service` + `canary.service` | **IGNORAR** — `FAST_START` é env var morta (canary não lê); killer+`/var/www` não portável |
| `canary/config.lua` | Rates x3-5/x12/x8/x2, `logLevel=trace`, `jsonconfig=false` (runtime, não build) | Não (`config.lua.dist` oficial intacto) | **IGNORAR p/ build** — dado operacional, não flag de compilação |
| `mold / ccache / unity / protobuf / vcpkg / jobs` | mold: zero nos 3; ccache/sccache: herdado; unity: OT desliga (`-DSPEED_UP_BUILD_UNITY=OFF` + `UNITY OFF` só no protobuf); protobuf: sem toggle, OT força sistema; vcpkg: OT remove do recompile; jobs: OT `-j14`/`nproc` hardcoded | Sim/parcial: ccache/sccache c/ guards MSVC+Ninja + `SharedBuildCache`, preset `SCCACHE=ON`; unity `ON` release/`OFF` debug via `CMakePresets`; jobs `--jobs`+`CMAKE_BUILD_PARALLEL_LEVEL`; vcpkg reforçado | **PORTAR só convenção jobs** (`--jobs`/`CMAKE_BUILD_PARALLEL_LEVEL` do oficial); resto **IGNORAR** — nada de mold/protobuf-toggle a aproveitar |

---

