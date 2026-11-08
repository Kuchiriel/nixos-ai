# Auditar infra e build (@general subagent)

- **sessão:** `ses_ef1ffe249ffegW7dM3lOVi3rGU`
- **quando:** 2026-10-05 21:37 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 53 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Audite INFRAESTRUTURA, BUILD e CONFIG dos dois repos: `/home/nixos/projects/canary-official/` e `/home/nixos/projects/otclient/`.

PASSO 1 OBRIGATORIO: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/05-infra.md`.
PASSO 2: investigue. PASSO 3: reescreva com o relatorio.

REGRA: **NAO BUILDAR, NAO COMPILAR, NAO SUBIR/DESCER CONTAINER, NAO REINICIAR NADA, NAO RODE `nixos-rebuild`.** Apenas leitura, grep, e comandos seguros de leitura como `docker inspect`/`docker compose config` que NAO mudem estado (se nao tiver certeza se um comando muda estado, nao rode).

FOCAS:

1. **Docker.** `canary-official/docker/`: `Dockerfile.alpine`, `docker-compose.yml`, `docker-compose.sandbox.yml`, `.env.dist`, `run-sandbox.sh`, `build-alpine.sh`.
   - Mitos e duplicacao entre os 2 compose. O que cada um sobrescreve? Tem servico orfao?
   - `ports:` — o que publica em `0.0.0.0`? Isso e' aceitavel numa maquina de desenvolvimento? Liste porta->servico->risco.
   - Volume mounts: algum monta o repo inteiro dentro do container? Isso explica bug de `git add`?
   - `build-alpine.sh`: `NPROC` tem teto real? Roda `apt`/`apk` de rede em build (reproducibilidade)? Usa `--no-cache`? Limpa artefato?
   - Healthcheck existe? `depends_on` com condition? Restart policy?

2. **Segredos e config.** Procure segredo committed: chave/TOKEN/password em arquivo versionado. Especifique: `docker/.env.dist`, `config.lua` (raiz e docker), `data/libs/functions`, `/etc/litellm.env` (nao versionado). Diferencie valor REAL de placeholder (`changeme`, `root`, `canary/canary`).
   - `config.lua` da raiz e o de `docker/` divergem? Liste as diferencas (ja sabemos que a raiz tinha `#` em vez de `--` num Lua, e IP de MySQL fixo `172.21.0.3` hardcoded). O IP hardcoded quebra se o compose mudar a rede? Como resolver?
   - `.gitignore` cobre `logs/`, `result`, `build/`? rode `git check-ignore -v` para confirmar.

3. **Build do server.** `CMakeLists.txt`, `cmake/`, `vcpkg.json`. Compila com que standard? Sanitizers habilitados? `-O` em release? Warnings como erro? Tem alvo de teste (`ctest`)? Existe teste C++ rodando em algum lugar (CI)?
   - Ache o workflow de CI: `.github/workflows/`. O que roda? Cobre o server, o client, o Lua? Compare com o que existe eShows que nao e' coberto.

4. **Ferramentas proprias.** `canary-official/tools/`: `guard_servidor.sh`, `sbx`, `sandbox-codegen/gerar_skills_cpp.py`, `check_lua_api_*.py`, `i18n/`, `canary_audit/`, `link-audit/`. Qual tem teste? Qual esta abandonado (data de ultima mod)? O `guard_servidor.sh` funciona mesmo (ele tem `--self-teste`: 6 ramos)? Leia e diga se a logica esta certa.

5. **Recursos e operacao.** `docker run-sandbox.sh`, scripts de start. Algum script faz `pkill` ou `killall` com pattern amplo? Isso ja causou acidente antes (matou o container). Ache TODOS os `pkill`/`killall`/`systemctl stop` nos dois repos e diga o risco de cada um. Este e um ponto de operacao importante.

6. **Client build.** `otclient/` tem `CMakeLists.txt`, `run.sh`, `result/` (symlink Nix). O `run.sh` compila? Como o dono roda (launcher rofi)? Ache o launcher rofi no sistema (`~/.config/rofi/`, `hyprland/`, `nixos-ai/`) e documente o caminho exato do binario que ele usa.

REGRAS:
- NAO modifique nada. NAO build. NAO container. NAO rebuild NixOS.
- Cite `arquivo:linha`.
- Numeros, nao adjetivos.
- Se um `pkill` for perigoso, isso e' ALTO e vao no topo.

FORMATO (PT-BR, markdown):
- VEREDITO: tabela de severidade.
- ACHADOS (ordenado, com `arquivo:linha`).
- SUPERFICIE DE REDE: tabela porta -> servico -> exposto? -> risco.
- SEGREDOS: tabela arquivo -> tipo -> valor real ou placeholder -> vaza? -> rotacao necessaria.
- PICKAIS OPERACIONAIS: lista de todo `pkill`/`kill` perigoso com o risco.
- VERIFICADO-OK.
- LIMITACOES.

Mensagem final: 15 linhas, contagem por severidade + os 5 piores.

---

## · ?

I'll start by writing the EM_ANDAMENTO marker, then investigate.

---

## · ?

Marker written. Now investigating.

---

## · ?

Investigation complete. Writing the report.

---

## · ?

Relatório em `/home/nixos/projects/plans/audit-05-10/05-infra.md`.41 achados: **4 CRÍTICO · 9 ALTO · 17 MÉDIO · 11 BAIXO**.

**Os 5 piores:**
1. **`docker-compose.sandbox.yml:139`** — override de `ports` do MyAAC *concatena*, não substitui. `docker inspect` mostra 8080 (colide com llama-server) + 8081 (colide com embeddings). `otbr-myaac-1` com **Restarts=854**, ativo agora.
2. **`docker-compose.yml:127`** — gRPC do login-server em `0.0.0.0:9090`, sem TLS nem token. Com 8088 e 7171-7175, 8 portas em todas as interfaces.
3. **`.gitignore` incompleto** (18 linhas, zero artefato) — `docker/.env`, `config.lua`, `canary-musl`, `otclient/result` (symlink p/ `/nix/store`) fora do ignore com 182 arquivos soltos no tree. Nenhum segredo de valor commitado; o risco é o próximo `git add -A`.
4. **`config.lua:447`** — `mysqlHost = "172.21.0.3"` hardcoded (DHCP de bridge) + 8 divergências com `docker/config.lua` (inclui `mysqlPass="root"` versionado).
5. **`guard_servidor.sh`** — A2 (bloqueia o caminho container-only por config do nativo), A6 (`:194` `for p in PORTAS` não usa `$p` → falso negativo), A3 (senha root na cmdline), UNTRACKED mas `run-sandbox.sh:27` depende dele.

Verificações que mudam o diagnóstico: os 6 ramos do `--self-teste` estão **logicamente corretos** (matriz conferida); ASan existe mas 0 workflows o invocam; `data-sandbox/**` (362 MB, 182 arquivos) tem **0** cobertura de CI; e **nenhum** `pkill` nos2 repos casa com container — o único regex ampla é `bench_sequencial.sh:41`, cujo comentário "nunca os do systemd" é falso para `PORT=8080`.

Launcher: rofi drun → `.desktop` órfão (não gerenciado pelo Nix) → `run.sh` → `/nix/store/ksmniwflbzjyyw6cicjr8xkwsv6bn9m7-otclient-1.0.0-unstable-2026-10-01/bin/otclient` (confirmado com o parser 0xA1).

---

