# Auditoria 15/11/2026 — snapshot da casa (somente leitura)

Autor: auditor (paperplay `auditor.md`). Nada foi aplicado: sem fix, sem
restart, sem tocar no duplex. Cada achado traz evidência (comando + saída)
e o preparo do próximo passo.

## Achado 1 — CRÍTICO — o cérebro do duplex está morto (:8092)

Evidência:

```
$ bash scripts/llama-swap.sh --list
  NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB, 5758 MiB, 96 MiB
  pid=4034182 446MiB  porta=8081  modelo=nomic-embed-text-v2-moe
  pid=4066742 934MiB  porta=8097  modelo=ggml-large-v3-turbo-q5_0
  pid=765325 4356MiB porta=57639 modelo=?            <- router :8080, bonsai
  :8080 responde | :8092 NAO responde
$ systemctl is-active llama-uncensored-4b.service -> inactive
$ curl -s -X POST http://127.0.0.1:8092/v1/chat/completions ... -> sem resposta (porta fechada)
$ curl -s -X POST http://127.0.0.1:8090/api/chat -> 500 (ConnectionRefused no backend)
```

O router segura 4.356 GiB com o **bonsai** (EN, sem PT), sobram 96 MiB, e o
**4B-MTP com o LoRA v9** (3.874 GiB) fica fora. O duplex aponta para
`:8092` por default (`scripts/duplex-voice.py:2763-2764`,
`base = http://{host}:{port}`), então hoje ele não tem nem o classificador de
turno nem o cérebro de resposta. Efeito para o dono: "não responde / inútil".

Regra da casa que já existe (AGENTS.md, 14/11): bonsai não pode ser default;
o router deve servir o 4B MTP; um único residente por vez; bonsai sob demanda
e sempre em inglês. A exclusividade por VRAM foi implementada
(`scripts/llama-swap.sh`, commit 919c74d9/8f92c844), mas o estado atual é
"bonsai residente + duplex apontando para um servidor que não existe".

Preparo (para `dev`, não aplicado): `bash scripts/llama-swap.sh --free`
(larga a VRAM; o script já aponta para o LoRA v9) seguido de
`bash scripts/llama-swap.sh --start-mtp` (sobe :8092 com o LoRA v9). O
`--start-mtp code` existe para o outro perfil (coding, porta 8096, sem LoRA) —
é a exclusividade dos dois perfis do MTP descrita no commit 919c74d9.

## Achado 2 — ALTO — webui API (8090) exposto na tailnet sem autenticação

Evidência:

```
$ curl -s -o /dev/null -w "%{http_code}" http://100.121.100.103:8090/api/state  -> 200
$ curl -s http://100.121.100.103:8090/api/keys
{"providers":{"openrouter":true,"groq":true,"cerebras":true,"together":true,"gemini":true,"hf":true},...}
$ curl -s -X POST -d '{"provider":"groq","key":"x"}' http://100.121.100.103:8090/api/keys -> 500
   (o serviço nao consegue escrever /etc/litellm.env -> OSError -> 500; nao ha exploit de escrita)
$ curl -s -X POST -d '{"message":"..."}' http://100.121.100.103:8090/api/chat -> 500 (achado 1)
```

O backend do webui escuta so em 127.0.0.1 (`ss -ltnp` mostra
`127.0.0.1:8090`), mas existe um forward tailnet-v4
(`home-manager/modules/agent-hub.nix:72`, `tailnet-v4-8090.service`) que abre
`100.121.100.103:8090` para a tailnet. O house diz, no mesmo arquivo, que o
servico NixOS "so escuta em 127.0.0.1 por design (nao expor chaves de API na
LAN)" — o forward desfaz esse design: qualquer dispositivo da tailnet
enxerga `/api/state`, `/api/keys` (nomes dos providers com chave) e `/api/chat`
(chamada de LLM local, sem limite).

Preparo: fechar o forward, ou exigir o mesmo token do hub
(`x-agent-hub-token`, ja implementado no `scripts/agent-hub.mjs:50`) nas
rotas do webui, ou_bind no loopback e acesso pelo hub (que ja tem token).

## Achado 3 — MÉDIO — `/api/agents` do hub nao exige token

Evidência: `curl http://127.0.0.1:8091/api/agents` -> 200 sem token;
`POST /api/wake` -> 401 sem token (a parte sensivel esta fechada).
O bind e `::` por decisao do dono (celular pela tailnet), e o token file
existe com 0600 (`~/.config/opencode/agent-hub.token`). O que vaza sem token:
nomes dos agentes, lanes, IDs de sessao e busy. Nao expoe transcript nem wake.

Preparo: decidir se roster e dado publico (deixar) ou fechar com o mesmo gate
das rotas sensiveis.

## Achado 4 — MÉDIO — as regras de firewall das portas LAN/tailnet sao voláteis

Evidência: o proprio digest da noite registra "porta LAN/tailnet sao regras
iptables VOLAIS (somem no reboot)". As portas 5173/8090/8091 estão abertas
por iptables e nao por declaracao NixOS, entao o comportamento muda a cada
reboot e nao ha fonte unica (a config em `configuration.nix` e o que documenta).

Preparo: mover para firewall declarativo (nftables/iptables em NixOS) ou
registrar no AGENTS.md que a exposicao precisa ser refeita a cada boot.

## Achado 5 — BAIXO — cobertura de teste offline no pacote jarvis

Evidência: `modules/ai/package.nix` (checkPhase) deseleciona 7 testes
`offline*` (commit 2e689bbb) porque `data/offline/corpus.db` (24 MB) nao
entra no pacote (cleanSource embala so `./jarvis`). O rebuild volta a passar,
mas 7 testes validos ficam sem cobertura no sandbox; o TODO
`sweep-2026-11` continua aberto.

Preparo: copiar o corpus para dentro do pacote (ou usar `substituteInPlace`
com o corpus como input) e reativar os 7 testes.

## Achado 6 — BAIXO — arvore suja com arquivos que o rebuild_stageia sozinho

Evidência: `git status --short` mostra `M flake.nix` (pygame),
`M modules/ai/jarvis/src/nightwatch/dungeon.py`,
`M modules/ai/jarvis/src/jarvis/webui/frontend/vite.config.ts` e 5 arquivos
novos nao versionados (`scripts/dungeon-checker.py`,
`dungeon-checker-jogo.py`, `dungeon-lab.sh`, `dungeon-lab-zero.sh`,
`host-proxy.mjs`). O `rebuild-host.sh` faz `git add -A` no indice
compartilhado: esses arquivos entram no indice de todo mundo e podem ser
commitados por outra lane sem ninguem revisar. O `host-proxy.mjs` (proxy que
reescreve o Host para o vite preview) escuta so em 127.0.0.1 — seguro, mas
nao versionado.

Preparo: versionar (ou revisar antes do proximo rebuild) e limpar o indice.

## Informativo — o que esta bom e medido

- Gate LoRA **v9 em producao** (commit 46a68f52): heldout1 **47/52** (v8 44/52,
  BARGE 7/7), heldout2 **23/24** (v8 22/24). Kernel Kaggle
  `kuchiriel/duplex-gate-lora-v9` completo; GPU quota 26.8h livres.
- Hub 8091 com token nas rotas sensiveis (transcript/wake/dungeon-ab/bus) —
  401 sem token, verificado.
- `duplex-voice.service` (user unit) ativo com `Restart=always` e espera
  por :8092 e :8097 antes de subir — quando o :8092 voltar, ele sobe sozinho.
- Consolida e memoria da sessao 14/11 gravados; v9 documentado no diario.

## Ordem sugerida para o `dev`

1. Achado 1 (cerebro morto) — destrava a voz inteira; o preparo ja existe
   (`llama-swap.sh --free` + `--start-mtp`), e o AGENTS.md diz que a troca
   permanente e config de host (rebuild do dono).
2. Achado 2 (webui 8090 sem auth na tailnet) — exposição real, ainda que
   não haja leitura dos valores das chaves.
3. Achados 3 e 4 (roster aberto + firewall volatil) — decisao do dono + declarativo.
4. Achados 5 e 6 (cobertura + arvore suja) — higiene, sem urgencia.
