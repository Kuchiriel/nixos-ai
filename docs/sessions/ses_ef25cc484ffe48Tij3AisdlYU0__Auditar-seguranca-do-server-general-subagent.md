# Auditar seguranca do server (@general subagent)

- **sessão:** `ses_ef25cc484ffe48Tij3AisdlYU0`
- **quando:** 2026-10-05 19:56 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 122 (exportadas: 4)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Audite a SEGURANCA do servidor em `/home/nixos/projects/canary-official/` (fork TFS 13.x, protocolo cliente 1525).

PASSO 1 OBRIGATORIO: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/02-seguranca.md`.
PASSO 2: investigue. PASSO 3: reescreva o arquivo com o relatorio.

FOCAS (cite `arquivo:linha` sempre):

1. **SQL injection** — o mais critico. Ache TODOS os pontos onde query MySQL e montada. `src/database/database.cpp`, `src/game/`, `src/io/`, `src/creatures/players/player.cpp`, `src/houses/`. Differencie prepared statement (seguro) de concatenacao (vulneravel). Para cada concatenacao, identifique a origem do dado: vem de packet do cliente? Se sim, e' EXPLOIT REMOTO. Scan automatizado: procure padroes como `"SELECT ... " + ` , `+ var +`, `sprintf`/stream `<<` dentro de string de query, e funcoes tipo `executeQuery("... " + x)`.

2. **Validacao de entrada de packet** — `src/server/network/protocol/protocolgame.cpp`, `protocolgameteleport.cpp`, `connection/connection.cpp`. Valores vindos do cliente que vao direto pra logica sem clamp: posicao (x,y,z), lookType, skillId, itemId, vocacaoId, outfitId, amount, targetId. C Overflow/underflow em aritmetica com `uint8_t`? C valor absurdamente grande virando `new[]`? (nota: `getString` ja e' limitado a 4096 por `readEndPosition`, entao foque em outros campos)

3. **Lua sandbox escape** — o server expoe C++ pro Lua. `src/lua/`, `src/script/`. O que o Lua pode chamar? Existe `os.execute`, `io.open`, `loadstring`, acesso a `package`, `dofile` fora de area restrita? Um jogador consegue executar codigo no servidor? Procure por funcoes expostas que abrem arquivo ou spawn de processo.

4. **Autenticacao e sessao** — `src/creatures/players/login.cpp`, `player.cpp`. Login: C check de senha em texto plano ou hash? C rate limiting de tentativa? C validacao de account name? Session hijacking: token previsivel?

5. **Exposicao de rede / configuracao** — `config.lua` (raiz e `docker/config.lua`), `docker/docker-compose*.yml`. Porta 7172 exposta na internet? SQL/Redis com senha default? Segredo em texto puro no repo?

6. **DoS** — flood de packet, pacote gigante, `OUTPUTMESSAGE_MAXSIZE` estourado, recursion sem limite (Lua stack overflow via `setfenv` recursivo, `protocolgame` recursivo).

REGRAS:
- NAO modifique o repo. So leitura/grep. NAO compile. NAO rode pkill/docker.
- CONFIRME relendo contexto. Marque "HIPOTESE" se nao tiver certeza do exploit. Diferencie "CONFIRMADO EXPLOITAVEL" de "MAIS OU MENOS".
- Nao inflacione. 8 achados solidos > 40 speculosos.
- Se um achado for exploitable remotamente por jogador sem autenticacao, marque como TAL e diga o vetor em uma frase.

FORMATO (PT-BR, markdown):
- VEREDITO: tabela CRITICO/ALTO/MEDIO/BAIXO.
- ACHADOS: numero, severidade, `arquivo:linha`, vetor de ataque concreto, impacto, correcao.
- SUPERFICIE DE ATAQUE: resumo do que um atacante remoto achieve sem conta.
- VERIFICADO-OK.
- LIMITACOES.

Mensagem final: 15 linhas, contagem por severidade + os 5 piores.

---

## · ?

I'll start the audit. Let me first write the marker file, then investigate.

---

## · ?

Now I have enough evidence. Writing the report.

---

## · ?

Relatório pronto em `/home/nixos/projects/plans/audit-05-10/02-seguranca.md` (340 linhas). As modificações em `data-sandbox/` são pré-existentes (não toquei no repo).

```
CRÍTICO  2 | ALTO  3 | MÉDIO  3 | BAIXO  2 | total 10
```

**Os 5 piores:**

1. **CRÍTICO — chave RSA de login privada é pública** (`key.pem:1` commitado + `src/security/rsa.cpp:30-31` hardcoded). Verifiquei computacionalmente: o módulo do `key.pem` **é** `p*q` do `rsa.cpp` — mesma chave RSA-1024. Captura passiva do 1º pacote em 7172 → descriptografa conta + senha/session key + chave XTEA (`protocolgame.cpp:1276-1312`). Apagar o `key.pem` não resolve: o fallback recria a chave idêntica.
2. **CRÍTICO — stack docker/admin em0.0.0.0 com senha default**: `docker-compose.yml:99` publica MyAAC em `8080` com `MYAAC_ADMIN_PASSWORD=admin123` (`docker/.env.dist:41`) e `CANARY_DB_ROOT_PASSWORD=root`; binário escuta `INADDR_ANY` (`server.cpp:161`). Host exposto ⇒ leitura da tabela `accounts` + criação de conta GOD.
3. **ALTO — zero rate-limit de login**: o único freio é throttle de *conexão* por IP (`ban.cpp:30-47`, 6/5s). Brute force de senha com CPU do servidor como oráculo.
4. **ALTO — DoS de disco + vazamento de credencial sem autenticação**: `config.lua:16 logLevel="debug"` + `protocolgame.cpp:1317` loga `sessionKey[0..24]` (conta + começo da senha) e `connection.cpp:217,254` loga por conexão, tudo em `logs/` via `start.sh:24` **sem rotação nem limite de tamanho**.
5. **ALTO — RCE via Lua**: `luaL_openlibs` sem sandbox (`lua_functions_loader.cpp:38`) + `pcall(load("return " .. value))` sobre digitação do jogador em `/setkv`, gating só por `player->getAccountType() != ACCOUNT_TYPE_GOD` (`talkaction.cpp:67`).

**Achado estrutural importante:** varredura completa dos 138 pontos de query não achou **nenhuma** SQL injection — `escapeString`/`escapeBlob` envolve em aspas e aplica `mysql_real_escape_string`, aplicado consistentemente; todo identificador interpolado é numérico/enum; `CLIENT_MULTI_STATATESMENTS` não está ligado (`database.cpp:78`), então stacked queries são impossíveis. O que existe é dívida: **zero prepared statements** no C++ e37 call sites de `db.query` em Lua aceitando SQL arbitrário.

Rede/DoS de packet também está sólido: buffer é `std::array` fixo (sem `new[]` por tamanho), `INPUTMESSAGE_MAXSIZE=4096` rejeitado antes do read, `Item::items[id]` sempre bounds-checked, `lookHead/Body/Legs/Feet` clampados, rate limit de25 pkt/s fecha conexão.

---

