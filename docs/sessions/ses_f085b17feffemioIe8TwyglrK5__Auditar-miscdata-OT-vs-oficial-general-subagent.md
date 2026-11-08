# Auditar misc+data OT vs oficial (@general subagent)

- **sessão:** `ses_f085b17feffemioIe8TwyglrK5`
- **quando:** 2026-10-01 13:26 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 8 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Somente LEITURA, não modifique nada. Audite mudanças MISC + DATA do lab OTServer:

Base: /home/nixos/projects/OTServer_UPGRADE/canary/ vs ../canary-fresh/. Oficial: /home/nixos/projects/canary-official/.

1. Diffs pequenos (`diff canary-fresh/<f> canary/<f>`): src/database/database.cpp (7 linhas — o famoso fix singleton DI? comparar com database.cpp do oficial atual), src/utils/tools.cpp (12), src/utils/const.hpp (4), src/lib/logging/log_with_spd_log.cpp (4), src/pch.hpp (16), src/creatures/combat/condition.cpp.20251216-091948.truncated (leftover?)
2. Grep singleton/DI: `grep -rn "getInstance\|boost::di\|soft_singleton\|KVSQL\|kv store" canary/src --include=*.cpp --include=*.hpp | head -20` e comparar se o oficial atual tem o mesmo padrão (ex.: src/database/, src/kv/). Dizer ONDE está o fix de verdade, se é que existe.
3. Data: `diff -rq canary-fresh/data canary/data` (appearances.dat difere? data/scripts/custom_monetization só no lab? data-otservbr-global/world/otservbr.otbm? catalog-content.json? map *.dat?). Dizer se é útil (sprites/mapa p/ mundo sandbox) ou lixo.
4. Dirs novos no lab: src/forensics/, src/enums_generated/, src/utils/atomic_queue, src/protobuf/src/, tests/unit/server/network/protocol/ — útil ou entulho?

Retorne TABELA compacta: item | achado (1 linha) | veredito PORTAR/ADAPTAR/IGNORAR + motivo. Máx 40 linhas. Não modifique nada.

---

## · ?

Somente leitura — nada modificado. Lab=`OTServer_UPGRADE/canary`, fresh=`canary-fresh`, oficial=`canary-official`.

| item | achado (1 linha) | veredito + motivo |
|---|---|---|
| database.cpp (7L) | Não é fix DI; só `fmt::localtime(now_c)`→`*std::localtime(&now_c)` (shim fmt antigo); oficial atual está à frente (helper `appendInsertBaseQuery`, `metrics::lock_latency`, `DBInsert` length fix) | IGNORAR — oficial já é superior |
| database.hpp | Lab tem `executeWithinTransaction`+`mutable recursive_mutex`; oficial tem versão equivalente/mais nova | IGNORAR — já coberto no oficial |
| tools.cpp (3 hunks) | Mesmo shim `fmt::localtime`→`*std::localtime` em `formatDate/formatDateTime/formatTime` | IGNORAR — compat toolchain, não fix |
| const.hpp | `INPUTMESSAGE_MAXSIZE` 4096→49152 (12x); oficial/fresh=4096 | IGNORAR — hack que mascara bug de protocolo, não ampliar hardcode |
| log_with_spd_log.cpp | default `info`→`trace` | IGNORAR — ruído/perf, reverter |
| pch.hpp (+16L) | Shim `asio::io_service=io_context`, `timer_expires_from_now→expires_after`, protobuf antes de magic_enum; oficial não tem | ADAPTAR c/ `#ifdef` só se build Nix/ASIO-1.10+ quebrar, senão IGNORAR |
| condition.cpp.truncated | Leftover 53KB ao lado do real 75KB (backup de edição 2025-12-16) | IGNORAR (lixo — remover quando houver modo escrita) |
| singleton/DI | `getInstance` ubicuo nos 3; `boost::di`+`lib/di/soft_singleton` idênticos nos 3; único `getInstance` novo é `forensics::Protocol1520` (experimento, não fix); `KVSQL(Database&,Logger&)` igual | IGNORAR mito — não existe "fix singleton DI" no lab; oficial é a referência |
| appearances.dat | `data/items/appearances.dat` difere: lab 4.81MB vs fresh 4.51MB (+300KB) | ADAPTAR c/ cautela — só se versão bater c/ cliente-alvo, senão IGNORAR |
| data/*.dat+`catalog-content.json` | `appearances-<hash>.dat` 4.7MB + `map-<hash>.dat` 182KB + `catalog-content.json` 975KB na raiz `data/` = cache de asset de cliente 15.x | IGNORAR — lixo regenerável, não dado de servidor |
| `custom_monetization/` | 3 lua (`vip_teleport`, `loyalty_rewards`, `daily_login_reward.disabled`) — exemplo toy c/ storage 100002 | IGNORAR — exemplo, não produção |
| `otservbr.otbm` 183MB | Só existe no lab (`data-otservbr-global/world/`); fresh não tem | PORTAR — único dado útil (mundo sandbox); validar versão/map + houses/monsters xml junto |
| `src/forensics/` | `milestone_protocol_15_20` (360+79L, singleton `Protocol1520` + helpers protobuf) — experimento 15.20 não integrado | IGNORAR no port / ADAPTAR só como referência p/ trabalho protobuf |
| `src/enums_generated/` | `TibiaOpcodes.hpp` 864L "auto-generated" mas conteúdo degenerado (`1=45,2=48…`) sem nomes reais | IGNORAR — entulho |
| `src/utils/atomic_queue` + `src/protobuf/src/` (8.9MB `tibia15_20.pb.cc/h`) | Deps vendored/commit de artefato gerado; CMake do lab aponta p/ `third_party/` | IGNORAR vendor — resolver via vcpkg/nix e regenerar c/ protoc |
| `tests/.../protocol/loginmessage_test.cpp` | 96L, mock Connection/ProtocolGame p/ `parseProtobufMessage` — único teste novo | PORTAR — único item novo c/ valor claro |

---

