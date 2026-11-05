# IMP-015 — Catálogo Free de LLMs no OpenCode (auditoria 2026-10-08)

Missão: descobrir, integrar, testar e filtrar provedores gratuitos de LLM na
config declarativa do opencode (`home-manager/home.nix`, módulo
`programs.opencode`, package `pkgs.kilo` = opencode 1.18.29).

## Estado final

| Provedor | Chave | Catálogo real (API) | Aprovados (teste "OK" via `opencode run`) | Estado |
|---|---|---|---|---|
| opencode (Zen) | auth.json | 84 modelos | — (reteste pendente) | **COTA_ESGOTADA hoje** — dono confirmou que funciona (estourou a cota diária dele por uso). Mantido HABILITADO no filtro; reteste amanhã ou quando a cota renova. |
| google (Gemini) | GEMINI_API_KEY (env) — **corrigida 08/10** (estava API_KEY_INVALID; substituída pela chave válida do auth.json) | 45 modelos | gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3.5-flash, gemma-4-31b-it | ✅ 4/4 |
| cloudflare | CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID (novas 08/10) | 322 (texto ~69) | @cf/openai/gpt-oss-120b, @cf/google/gemma-4-26b-a4b-it, @cf/qwen/qwen3.8-27b, @cf/mistralai/mistral-small-3.1-24b-instruct | ✅ 4 testados; @cf/meta/llama-3.3-70b precisa `limit` (24000 ctx) — corrigido no Nix; kimi-k2.7-code e deepseek-v4-flash-0731 = **Workers Paid only** (Forbidden) |
| cohere | COHERE_API_KEY (nova 08/10) | 35 modelos | command-r7b-12-2024, command-a-03-2025, command-a-reasoning-08-2025, north-mini-code-1-0 | ✅ 4/4 (reasoning precisa timeout maior: ~2k tokens de reasoning) |
| nvidia (NIM) | NVIDIA_API_KEY (env) | 80 modelos | nemotron-3-super-120b-a12b, gemma-4-31b-it | ⚠️ deepseek-v4.1-flash: streaming timeout no NIM (HTTP 000 em 90s, mesmo via curl) = **INDISPONIVEL_TEMPORARIO** |
| openrouter | OPENROUTER_API_KEY (env) | 468 (16 :free) | thinkingmachines/inkling:free | ⚠️ demais :free = **free-models-per-day esgotado** (402 c/ msg "Add 10 credits") = COTA_ESGOTADA diária |
| groq | GROQ_API_KEY (env) | 11 modelos | — (via opencode) | ⚠️ ITPM/TPM 7000-8000 < system prompt do agente (~10-12k tokens) = **ERRO_CONFIGURACAO conhecido** (nota no Nix); via curl mínimo responde OK |
| huggingface | HF_TOKEN (env) | 136 modelos | — | ❌ créditos esgotados = COTA_ESGOTADA (Inference Providers agora pago) |
| cerebras | CEREBRAS_API_KEY (env) | 2 modelos | — | ❌ HTTP 402 Payment Required (conta sem crédito) = AGUARDANDO_ACAO_USUARIO |
| sambanova | SAMBANOVA_API_KEY (nova 08/10) | 6 modelos | — | ❌ HTTP 402 PAYMENT_METHOD_REQUIRED (free tier pós-2026 exige cartão) = AGUARDANDO_ACAO_USUARIO |
| together | TOGETHER_API_KEY | — | — | ❌ 401 (recusado 16/09, sem mudança) |

Total: **16 aprovados** (14 cloud + locais fora do escopo), 9 providers
pesquisados a fundo + 3 novos integrados (cloudflare/cohere/sambanova).

## Correções aplicadas (08/10)

1. **GEMINI_API_KEY podre** no `/etc/litellm.env` (API_KEY_INVALID) →
   substituída pela chave válida do `auth.json` google (backup:
   `/etc/litellm.env.bak-20261008`). Testado: HTTP 200 no catálogo + 4
   inferências OK.
2. **OPENCODE_CONFIG corrompido** no env (chave colada no lugar de um path;
   fazia o opencode carregar config errada via env) → linha comentada.
3. **`lib.format` inexistente** em `modules/services/vision-moondream.nix:170`
   (avaliação do host quebrada pré-existente) → `builtins.toJSON`. Era o
   bloqueio do rebuild.
4. **IDs mortos removidos**: groq/qwen3.6-27b (saiu do catálogo),
   openrouter/z-ai/glm-5.2:free (fora do catálogo :free atual),
   nvidia/deepseek-v4-flash-0731 → v4.1-flash.
5. **Providers adicionados ao `home.nix`**: cloudflare (7 modelos),
   sambanova (4), cohere (5), + novos IDs google/nvidia/cerebras/groq/openrouter.
6. **Filtro**: `enabled_providers` no settings (Zen oculto do seletor).
   Nota: `whitelist`/`blacklist` por provider existem no schema mas não são
   aplicados pelo seletor da CLI 1.18.29 — testado e documentado.
7. **Chaves novas no env** (fonte da verdade do auth-sync): CLOUDFLARE_*,
   SAMBANOVA_API_KEY, COHERE_API_KEY.

## Diagnóstico MCP (pedido do dono)

Suspeita de que o MCP jarvis travava chamadas de API. Verificado:
- Handshake MCP OK (initialize + tools/list respondem JSON-RPC válido).
- A/B com config idêntica ± MCP: `cohere/command-r7b-12-2024` e
  `command-a-03-2025` retornam OK com e sem MCP.
- Conclusão: **MCP não quebra chamadas**. Os hangs vistos eram de providers:
  Zen (retry silencioso em rate limit → timeout 124s) e NIM
  deepseek-v4.1-flash (streaming que não devolve bytes).

## Pendências (ações humanas)

1. **SambaNova**: adicionar cartão em cloud.sambanova.ai/plans/billing se
   quiser usar o free tier atual (exige payment method).
2. **Cerebras**: billing na conta p/ destravar 402 (ou criar conta nova free).
3. **OpenRouter**: 10 créditos destravam 1000 req/dia nos :free; sem isso, 1
   modelo free por vez respeita cota diária (inkling passou hoje).
4. **Zen**: cota diária esgotada em 08/10 (uso legítimo do dono); já está
   habilitado no filtro. Retestar "OK" quando a cota renova (meia-noite UTC).
5. **Kernel**: `nvidia-kernel-modules-595.71.05-7.2.9` não compila com GCC 15
   (strncpy implícito) — rebuild do host falha (não é desta missão, mas é o
   que impede `./rebuild-host.sh` completo; HM pôde ser ativado direto).
6. **NVIDIA NIM**: deepseek-v4.1-flash segue dando timeout — retestar depois.

## Procedimento de reteste

```bash
# 1. Recarregar env (chaves)
eval "$(sudo cat /etc/litellm.env | grep '^export ')"

# 2. Listagem (deve refletir o enabled_providers do home.nix)
opencode models | sed -E 's|/.*||' | sort | uniq -c

# 3. Teste de inferência individual (usar config sem MCP p/ isolar provider)
python3 -c "import json;c=json.load(open('$HOME/.config/opencode/opencode.json'));c.pop('mcp',None);json.dump(c,open('/tmp/oc-test.json','w'))"
OPENCODE_CONFIG=/tmp/oc-test.json timeout 90 opencode run --model PROVIDER/MODEL "Responda somente com a palavra OK."

# 4. Se aprovou: nada a fazer (já está no filtro). Se Zen passou:
#    re-add "opencode" ao enabled_providers em home-manager/home.nix
# 5. Aplicar: nix build ~/projects/nixos-ai#nixosConfigurations.nitro-v15.config.home-manager.users.nixos.home.activationPackage
#    e rodar o ./result/activate (ou ./rebuild-host.sh quando o kernel compilar)
```

## Fontes oficiais consultadas

- Catálogos reais via API: GET /v1/models de cada provider (08/10, com as
  chaves do env; ver log da sessão).
- opencode schema: https://opencode.ai/config.json ($defs.Config:
  enabled_providers, disabled_providers; $defs.ProviderConfig: whitelist,
  blacklist) + docs https://opencode.ai/docs/config/
- SambaNova free tier: docs.sambanova.ai/docs/en/models/rate-limits +
  community.sambanova.ai/t/is-free-tier-going-away/847
- Cerebras rate limits: inference-docs.cerebras.ai/support/rate-limits
- ZenMux kimi-k3-free: zenmux.ai/moonshotai/kimi-k3-free (promo "limited
  time", não permanente — não integrado como free permanente)
- OpenRouter free limits: openrouter.ai/docs (free-models-per-day)

## Arquivos modificados

- `home-manager/home.nix` — providers, IDs corrigidos, filtro, notas de estado
- `modules/services/vision-moondream.nix` — fix lib.format (bloqueio de eval)
- `/etc/litellm.env` — GEMINI corrigida, OPENCODE_CONFIG neutralizado,
  CLOUDFLARE/SAMBANOVA/COHERE adicionadas (fora do git, root-only)
