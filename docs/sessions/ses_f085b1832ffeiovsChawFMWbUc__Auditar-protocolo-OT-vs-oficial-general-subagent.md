# Auditar protocolo OT vs oficial (@general subagent)

- **sessão:** `ses_f085b1832ffeiovsChawFMWbUc`
- **quando:** 2026-10-01 13:26 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 13 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Somente LEITURA, não modifique nada. Audite as mudanças de PROTOCOLO/REDE do lab OTServer vs upstream:

Base: /home/nixos/projects/OTServer_UPGRADE/canary/ (lab, CLIENT_VERSION 1520) vs /home/nixos/projects/OTServer_UPGRADE/canary-fresh/ (limpo #3765). Oficial atual: /home/nixos/projects/canary-official/ (@04b83b5, CLIENT_VERSION 1525, modelo TransportProfile/ProtocolProfile em src/server/network/protocol/protocol_profile.hpp, docs/systems/multiprotocol.md + client-15-25-compatibility-update.md).

Arquivos (use `diff canary-fresh/<f> canary/<f>`):
- src/server/network/connection/connection.cpp (506 linhas diff!) + connection.hpp (53)
- src/server/network/message/networkmessage.cpp/hpp + outputmessage.hpp
- src/server/network/protocol/protocol.hpp (72), protocolgame.hpp (56), protocollogin.cpp/hpp, protocolstatus.hpp
- src/server/server.cpp (91)/server.hpp/signals.hpp, src/game/game.cpp (16, dual-port 7171/7172), src/creatures/players/player.hpp (8), src/core.hpp (4)
- Arquivos NOVOS no lab: protocolgame_parse.cpp, protocolgame_send.cpp, protocolgame_helper(s).cpp/hpp, protocolgame_types.hpp, protocolwebsocket.hpp, websocket_protocol.cpp.disabled, tibia_working.proto, tests/unit/server/network/protocol/

Para cada: o que mudou (1-2 linhas), se o oficial atual JÁ cobre (multiprofile? taskboard? login modern #4115?) ou se é exclusivo do lab, veredito PORTAR / ADAPTAR (como profile/flag) / IGNORAR + risco em 1 linha. Foque no que é ÚTIL de verdade (framing 6B, XTEA off 159, bundle 0x00, dual-port, singletons DI) vs gambiarra. Máx 60 linhas. Não modifique nada.

---

## · ?

Auditoria PROTOCOLO/REDE — lab `canary` (1520) vs `canary-fresh` #3765 vs oficial `canary-official` @04b83b5 (1525, `protocol_profile.hpp` + `multiprotocol.md` + `client-15-25-compat`):

| Arquivo | O que mudou no lab | Oficial já cobre? | Veredito + risco |
|---|---|---|---|
| `connection.cpp` (506) | Troca proxy-ident/checksum-routing por sniff `async_read_some` ("Canary\n", skip-zeros, header 6B `len*8`), challenge hardcoded porta 7172, `extraData`, logs `info` p/ pacote | Sim: `TransportCodec`+`TransportProfile`+`InitialConnectionBehavior/ChallengeProfile`, sem sniff/log | **IGNORAR** sniff/challenge/logs; **ADAPTAR** framing 6B como `TransportProfile`. Risco: sniff quebra proxy/flood-limit e `extraData` tem race/over-read |
| `connection.hpp` (53) | Flags `is1520Client/handshakeComplete/extraData/headerSize(6)/sendRaw/getConnectionCount` | Sim, via estado do codec + profile, sem bool espalhado | **ADAPTAR** só estado-profile; **IGNORAR** resto. Risco: `if(is1520)` espalhado vira dívida `if-version` |
| `networkmessage.cpp/hpp` | `+addVarint/getVarint/peekByte`; `INITIAL_BUFFER_POSITION 7→16` | Parcial: varint é necessidade protobuf real; 16 não (oficial segue 7) | **PORTAR** varint/peek como helper do codec; **IGNORAR** 16. Risco: 16 desloca `decodeHeader`/body e quebra legado |
| `outputmessage.hpp` (4) | Só whitespace (`private:` move) | N/A | **IGNORAR**. Risco: zero |
| `protocol.hpp` (72) | `is1520/firstPacket/isWebSocket/seq/packetCount`, `map<void*,uint8> perProtocolMessageCounts`, `RSA_decrypt(v)`, XTEA movido | Sim: `ProtocolFeature` flags + seq/checksum no `TransportProfile` | **ADAPTAR** seq/feature como profile; **IGNORAR** `map<void*>` + singleton. Risco: mapa keyed por ponteiro = leak/UB |
| `protocolgame.hpp` (56) | Includes `protocol_15_20/types/proto`, `TextMessage` removido, `+getProtocolIdentifier/sendProtobufMessage/parseProtobufLogin/AddBasicData/loginBuffer`, `friend Protocol1520` | Sim: payload versionado por profile; não tem friend-singleton | **ADAPTAR** identifier/layout-hooks; **IGNORAR** friend. Risco: acoplamento circular Game↔1520 |
| `protocollogin.cpp/hpp`, `protocolstatus.hpp` | Branch `if(conn->is1520) Protocol1520::handleFirstMessage`; `+getProtocolIdentifier` | Sim: `resolveByClientVersion` + `Account/GameLoginLayout` + hints (login moderno #4115, taskboard em `data/modules`) | **ADAPTAR** identifier; **IGNORAR** branch singleton. Risco: bypassa layout moderno e quebra taskboard/login |
| `server.cpp (91)/hpp/signals.hpp` | `asio::post/expires_after` (bom), logs verbosos, `make_protocol` com routing-sniff 15.20, check same-port comentado, `+getPort()` | Sim: multiporta (`modernGamePort`+legacy 1100/860+`LOGIN_PORT`) + `protocol_port_utils.hpp` | **PORTAR** `getPort` + fixes asio; **ADAPTAR** routing como profile; **IGNORAR** logs + check comentado. Risco: sem check, conflito Login/Game na mesma porta é silencioso |
| `game.cpp` (16) | Dual-port hardcoded 7171/7172 + `#include <boost/di.hpp>` | Sim e melhor: portas via config, oficial já tem dual/multi | **IGNORAR** hardcode; se faltar porta usar config. Risco: hardcode ignora `STATUS_PORT`/`config.lua` |
| `player.hpp` (8) | `friend Protocol1520` | Não (e nem deve) | **IGNORAR** (usar accessor se preciso). Risco: fura encapsulamento |
| `core.hpp` (4) | `CLIENT_VERSION 1412→1520` | Sim, oficial 1525 | **IGNORAR**. Risco: version-check obsoleto |
| NOVOS `protocolgame_parse.cpp` (1769) / `_send.cpp` (6960) / `helper(s)` / `types.hpp` | Split parse/send (bom), mas acoplado ao singleton | Oficial separa transport/payload/profile; split em si é boa direção | **ADAPTAR** split como módulos sem singleton. Risco: portar junto carrega dependência `Protocol1520` |
| NOVOS `protocol_15_20.*` + `fragment` + `*.bak/*.broken/*.regressed` | Singleton `getInstance()`, bundle `0x00`, XTEA custom, framing 6B, `getAndResetMessageCount` | Conceitos sim (`TransportCodec`, bundle/compressão, seq), singleton não | **ADAPTAR** framing/bundle/XTEA-off como `TransportProfile`; **IGNORAR** singleton + litter `*.bak/*.broken`. Risco: lixo versionado + lógica forense com `snprintf` hex polui hot-path |
| NOVOS `protocolwebsocket.hpp`, `websocket_protocol.cpp.disabled`, `tibia_working.proto` | Websocket esqueleto desabilitado; proto fora de `protobuf/` | Oficial tem `protobuf/` próprio + sem WS no core | **IGNORAR** (WS e proto duplicado). Risco: proto divergente gera opcodes fantasmas |
| NOVOS `tests/.../loginmessage_test.cpp` | Teste protobuf c/ `MockConnection` + `tibia15_20.pb.h` | Oficial tem fixtures/captures por profile | **PORTAR** ideia (fixture + mock) adaptando ao path `protobuf/` oficial. Risco: baixo, é o artefato mais aproveitável |

Resumo útil vs gambiarra: aproveitar **framing 6B (`len*8`), bundle `0x00`/count, varint/peek, `getPort`, split parse/send, fixtures de teste** — tudo **como `TransportProfile`/`ProtocolProfile`/flag**, nunca como `is1520/singleton/sniff/logs`. Nada a modificar (só leitura feita).

---

