# models.nix = fonte única — refactor 03/11/2026

Missão do dono: "**models.nix = fonte única**" (units / routerDefault /
directUnits / groupUnits; consumo em Nix, Python, timers e gaming; remover o
`defaultModel = "bonsai"` do host).

## O que mudou (Nix — `modules/ai/models.nix`)

### 1. Blocos derivados (novos, no fim do arquivo)

| bloco | o que é | quem consome |
|---|---|---|
| `routerDefault` | id lógico do default do APP (= `routing.default`) | Nix, scripts |
| `routerDefaultEndpoint` | porta do server que serve o default (8092) | Nix, scripts |
| `groupUnits` | unit+porta+binário de cada grupo do router (prism/upstream/ik) | `llama-cpp.nix`, scripts |
| `directUnits` | unit+porta+binário+alias de cada server direto (9) | `llama-uncensored.nix`, scripts |
| `units` | catálogo único (grupo + diretos) | timers/scripts |

As portas dos grupos estão definidas **uma vez** (`serviceEndpoints` no `let`) e
alimentam tanto `routing.endpoints` quanto `groupUnits` — sem porta duplicada
no arquivo.

### 2. Campos novos no `routing` (vão para o registry JSON)

- `bootModel = { host = "bonsai"; vm = "jarvis-fast"; }` — **qual grupo sobe no
  boot**, por ambiente.
- `servicePorts = { embeddings = 8081; rerank = 8082; }` — portas dos serviços
  auxiliares (o Python lia 8081/8082 literais).
- `units` — mapa unit→{port,binary,...} (chaves: prism/upstream/ik + os 9
  servers diretos).
- `models.<id>.unit` — a unit systemd que serve cada model id (6 ids).

### 3. `bootModel` × `default` (a separação que faltava)

`default` = o **default do APP** (4B-MTP+LoRA, :8092, server direto, fora do
router). `bootModel` = o **grupo do router que sobe no boot** (host: bonsai →
grupo prism :8080; vm: jarvis-fast → grupo upstream :8083).

Antes these dois conceitos eram o mesmo campo (`defaultModel`), e o override do
host (`"bonsai"`) reintroduzia o bonsai como default do APP — exatamente o que
o dono pediu para tirar (26/10). Agora:
- trocar o default **não** derruba mais o router do boot;
- `hosts/nitro-v15/configuration.nix` **não tem mais override de defaultModel**
  (fonte única = `models.nix`).

### 4. Drifts corrigidos (verdade do server, não a intenção)

| lugar | antes | agora | por quê |
|---|---|---|---|
| `routing.models.jarvis-fast.ctx` | 49152 | **16384** | o server :8083 serve `qwen-fast.ctxSize = 16384`; 49152 fazia o runtime mandar 30k tokens e tomar erro de contexto |
| `routing.models.jarvis-strong.ctx` | 32768 | **8192** | o grupo ik serve `chat.ctxSize = 8192` (validado 03/10: "não subir!"); 32768 era o ctx do server **direto** :8084, não o do grupo |
| `directServers.gemma-4b.opencode.context` | 32768 | **8192** | o server serve `ctxSize = 8192`; o catálogo opencode podia mandar 4x mais que o server aceita |
| `home.nix` `local_small_model.bonsai.limit.context` | 8192 | **49152** (`routing.models.bonsai.ctx`) | o MESMO server (:8080) tinha dois contextos no mesmo arquivo (8192 e 49152) — o preset serve c=49152 |
| `home.nix` `local-fast`/`local` baseURL+context | literais | derivados de `routing.models.*` | idem |

### 5. Consumers migrados

**Nix**
- `modules/services/llama-cpp.nix`: `port` default ← `routing.endpoints.prism`;
  `defaultModel` default ← `routing.default`; `bootId` ← `routing.bootModel.${env}`;
  `embeddings.port`/`rerank.port` ← `routing.servicePorts.*`.
- `hosts/nitro-v15/configuration.nix`: override de `defaultModel` **removido**.
- `home-manager/home.nix`: baseURLs, contexts e o `model`/`small_model` default
  derivados de `pkgs.aiModels`.

**Python** (fonte: o mesmo registry JSON → zero hardcode novo)
- `core/model_registry.py`: novos campos `endpoints`/`service_ports`/`units` +
  métodos `port_for`, `base_url_for`, `service_port`, `router_port`, `unit_for`;
  o fallback do `endpoint` saiu do literal espalhado para `endpoints.prism`.
- `core/config.py`: `llm_base_url`, `llm_model`, `embed_base_url`,
  `rerank_base_url` derivados do registry (env ainda tem precedência).
- `core/provider_registry.py`: `LOCAL_BONSAI.base_url` derivada.
- `providers/reranker.py`: porta do rerank derivada.
- `cli/main.py` (`status`) e `core/doctor.py` (`sockets`): portas do stack
  derivadas.

**Shell/timers** (novo helper `scripts/jarvis-registry.sh`)
- `benchmarks/model-tiers/night-qwen.sh`, `benchmarks/model-tiers/swap-probe.sh`
  e `scripts/voice-up.sh`: default, porta, unit e porta do router vêm do
  registry (antes: `jarvis-mtp-lora`, `:8092`, `llama-uncensored-4b`, `:8080`
  literais).
- O helper tem **shim de compat** (registry vivo ainda é da generation anterior,
  sem `unit`/`units`/`servicePorts`) → os timers das 04:00/05:00 não quebram
  antes do rebuild. **Remover o shim depois do rebuild.**

## Comportamento preservado (o que NÃO mudou)

- Grupo que sobe no boot: prism (:8080) no host, upstream (:8083) na VM.
- Warmup do router: continua PULADO no host (o default é o server direto, não
  um preset do router) — o incidente VRAM 04/03 (bonsai 2.4G + 4B 4.4G > 6.1G)
  segue protegido.
- `small_model`/`model` do opencode: `local-uncensored-4b/jarvis-mtp-lora` (mesmo
  valor, agora derivado).
- `CANONICAL_CONTEXT = 32768` (Python) **não** foi tocado: é o "modelo de
  referência" do budget de contexto e tem teste que fiscaliza o uso
  (`test_context_drift.py`). **Divergência conhecida**: o registry diz que o
  bonsai serve 49152. Decisão do dono (mudar = budget +50%).

## Achado novo (não corrigido — precisa de decisão)

**Colisão de porta**: `directServers.deepseek-7b` e `directServers.duplex-35b`
usam **as duas a porta 8085**. Nunca bitou porque ambas são `wanted = false`
(uma por vez, manual), mas subir as duas = conflito de porta. Por isso a
unit→modelo é **explícita** (`models.<id>.unit`) e não deduzida por porta.

## Validação

- `nix flake check` → all checks passed (nixos-lab + nitro-v15 avaliam).
- `nix eval` dos blocos derivados → valores conferidos (units, bootModel,
  servicePorts, modelUnits, ctx fixes).
- Python: 58/58 no subset (chain/drift/routing/sampling/context_budget) e suíte
  completa (log em /tmp/opencode/pytest-full.log).
- Shell: `bash -n`/`sh -n` + helper testado contra o registry VIVO (valores
  corretos via shim).

## Pendente

1. **Rebuild** (o dono autoriza) → o registry em /etc passa a ter `units`,
   `servicePorts`, `bootModel` e `models.<id>.unit`; aí o shim do helper pode
   sair.
2. `CANONICAL_CONTEXT` (32768 vs 49152) — decisão do dono.
3. Porta 8085 duplicada (deepseek-7b × duplex-35b) — decidir a porta ou
   documentar o "um por vez".
4. Python ainda com literais: `core/metacognition.py`, `core/health_monitor.py`,
   `core/voice.py`, `core/model_lifecycle.py`, `core/hwprofile.py`,
   `providers/llm_llama_cpp.py`, `providers/llm_prismml.py` — o helper
   `base_url_for()` já existe, falta adoption.
5. `scripts/loop-runner.sh`, `scripts/pipeline.py`, `scripts/jarvis-cli.sh`
   (ladder de portas) — migrar para o helper.
6. "Gaming": nenhum módulo de gaming referencia modelo/porta de LLM (verificado
   no inventário) — nada a migrar.
