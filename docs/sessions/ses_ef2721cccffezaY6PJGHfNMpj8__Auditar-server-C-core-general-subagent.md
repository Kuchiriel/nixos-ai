# Auditar server C++ core (@general subagent)

- **sessão:** `ses_ef2721cccffezaY6PJGHfNMpj8`
- **quando:** 2026-10-05 19:32 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 88 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Analise o core C++ do servidor em `/home/nixos/projects/canary-official/src/` (fork TFS 13.x / OpenTibiaBR Canary, protocolo 1525). Foque em achar bugs e riscos REAIS com evidencia de codigo.

PASSOS OBRIGATORIOS:
1. Escreva PRIMEIRO um arquivo stub em `/home/nixos/projects/plans/audit-05-10/01-server-cpp.md` contendo a palavra `EM_ANDAMENTO`. Assim eu confirmo que voce consegue escrever no disco.
2. Investigue (com grep/rg e leitura): `src/server/network/connection/connection.cpp` e `.hpp`, `src/server/network/protocol/protocolgame.cpp`, `src/server/server.cpp` e `.hpp`, `src/game/game.cpp`, `src/io/iologindata.cpp`, `src/canary_server.cpp`.
3. Reescreva o arquivo do passo 1 com o relatorio completo.

ACHOS QUE VALEM (cite sempre `arquivo:linha`):
- Threading: quantas vezes `io_service.run()` pode ser chamado; races entre io_service e Dispatcher; shared_ptr/use-after-free.
- Parsing de packet: `getU8/getU16/getU32/getString` checam bound contra o tamanho real do buffer? O que acontece com packet malformado? `getString()` sem limite = DoS de alocacao?
- SQL: onde monta query MySQL? Concatenacao de string (injection) ou prepared statement? Seja rigoroso, cite linhas. Isto e o ponto mais critico.
- `catch` vazio engolindo erro, `exit()` em caminho de erro, `assert` em producao.
- Divergencia do upstream: `git log --oneline -40` e ache hacks/fixes locais.

REGRAS:
- NAO modifique nada no repositorio. Somente leitura/grep. NAO compile. NAO rode pkill. NAO toque em docker.
- CONFIRME cada achado relendo o contexto. Se nao tem certeza, marque "HIPOTESE" e diga o que falta confirmar. Nao reporte speculation como achado.
- 10 achados solidos valem mais que 40 speculosos.

FORMATO DO RELATORIO (PT-BR, markdown):
- SEVERIDADE: tabela com contagem CRITICO/ALTO/MEDIO/BAIXO.
- ACHADOS: numerados, cada um com severidade, `arquivo:linha`, o que e, impacto concreto (crash? exploit? deadlock? perda de dado?), correcao sugerida. Ordenado por severidade.
- OPORTUNIDADES: refactor com ganho claro (nao cosmetico).
- VERIFICADO-OK: o que checou e esta bom (evita retrabalho futuro).
- LIMITACOES.

Na sua mensagem final: resumo de 15 linhas com contagem por severidade e os 5 achados mais graves.

---

## · ?

I'll start by writing the stub file to confirm disk write access.

---

## · ?

Stub confirmed. Now investigating.

---

## · ?

Found initial leads. Reading server/core files.

---

## · ?

Investigation complete. Writing the report.

---

## · ?

Relatório final em `/home/nixos/projects/plans/audit-05-10/01-server-cpp.md` (504 linhas). Repositório não modificado — só leitura.

## Resumo

**16 achados:3 CRÍTICO · 5 ALTO · 5 MÉDIO · 3 BAIXO**

**Os 5 mais graves:**

1. **CRÍTICO — retry infinito no banco** (`database/database.cpp:273-282`). `storeQuery` usa `goto retry` **sem contador**, e `isRecoverableError` (linha 220) inclui `CR_CONNECTION_ERROR`. Com `MYSQL_OPT_RECONNECT=1` (linha 63), um MySQL inalcançável prende a thread num `for(;;)` **segurando o mutex global** → `savePlayer` no logout trava e o `createDatabaseBackup` do shutdown trava → **shutdown impossível, só `SIGKILL`**.

2. **CRÍTICO — perda silenciosa de salvamento de jogador** (`database.cpp:63` + `224-240` + `iologindata.cpp:195-211`). `savePlayer` grava ~15 tabelas em transação; se a conexão cai no meio, `retryQuery` reexecuta sobre a sessão nova onde **a transação não existe**, e `commit()` retorna sucesso. Jogador marcado como salvo com estado parcial. Sem erro no log.

3. **CRÍTICO — 10 s de congelamento global** (`database.cpp:224-240, 251`). `retryQuery(query, 10)` com `sleep(1s)` **sob o `scoped_lock` global**. Rotacionar a senha do MySQL derruba o servidor (auth failure também cai em `CR_CONNECTION_ERROR`).

4. **ALTO — shutdown pendurado para sempre** (`game.cpp:1009`, `signals.cpp:69-83`). `Game::shutdown()` é o **único** que chama `serviceManager->stop()`, e chega lá por `addEvent` com **retorno descartado** — o mesmo dos 5 handlers de sinal. Sob saturação: SIGTERM ignorado, e `io_service.run()` nunca retorna.

5. **ALTO — leak com ciclo eterno** (`connection.cpp:154-158` + `outputmessage.cpp:39-41`). Quando o Dispatcher está `ShuttingDown` (não `Saturated`), `dispatchProtocolRelease` retorna **sem liberar o protocolo** → o `removeProtocolFromAutosend` nunca roda → e `sendAll()` **se re-agenda para sempre** enquanto o vector não esvaziar.

**Achados que surprise- good news:** `io_service.run()` é chamado **exatamente 1×**, 1 objeto, thread principal (`server.hpp:107`, `server.cpp:38`) — sem race io/Dispatcher por construção. E **`getString()` NÃO é DoS**: `canRead` ancora em `readEndPosition` ≤ 4096 (`INPUTMESSAGE_MAXSIZE`), então toda alocação é limitada a ~4 KB/packet. Verifiquei também o invariante `position == length + 8` que torna `OutputMessage::append` seguro (margem de 16 bytes) — correto, mas silenciosamente.14 itens em **VERIFICADO-OK**.

**Ressalva de rigor:** o achado 7 (`static std::unordered_set` sem lock em `protocolgame.cpp:793`) está marcado **HIPÓTESE** no alcance — o defeito é certo, falta instrumentar `isBarrierParallel()` para fechar a cadeia.

---

