{ config, lib, ... }:
# ═══════════════════════════════════════════════════════════════════════
# LITELLM-CASCADE — cascade/fallback/handover de modelos (porta do legado)
#
# O legado (Manjaro) usava LiteLLM como gateway unificado (config-free-ai.yaml
# + config-smart.yaml): um endpoint OpenAI-compat que ROTEIA entre modelos
# locais e nuvem grátis com fallbacks em cadeia:
#
#   local (llama.cpp) → Groq (grátis) → Gemini (grátis) → OpenRouter (grátis)
#
# Aqui usamos o MÓDULO OFICIAL do nixpkgs (services.litellm, 26.05) — com
# hardening (DynamicUser, PrivateTmp), cache tiktoken seedado e suporte a
# environmentFile. Este módulo fino só injeta a ESTRATÉGIA de cascata nele.
#
# = Estratégia (água: funciona no lab e no host) =
#   1. LOCAL primeiro (lab: Qwen3-4B; host: Qwen3.6-35B MoE) — zero custo,
#      privado, sempre ativo (api_base 127.0.0.1:8080, o llama-cpp)
#   2. Se falhar/lento → nuvem grátis: Groq (14.400 req/dia) → Gemini
#      (1M tok/min) → OpenRouter (30+ modelos :free, sem cartão)
#   3. O JARVIS usa UM endpoint (http://127.0.0.1:4000/v1) e o LiteLLM decide
#      — a cascata fica declarativa, não no código do agente
#
# API keys: NUNCA no repo. Crie manualmente no host (fora do git):
#   sudo tee /etc/litellm.env > /dev/null <<'EOF'
#   LITELLM_MASTER_KEY=sk-...
#   GROQ_API_KEY=gsk_...
#   GEMINI_API_KEY=AIza...
#   OPENROUTER_API_KEY=sk-or-...
#   EOF
#   sudo chmod 600 /etc/litellm.env
# Sem o arquivo o serviço sobe mesmo assim (rota local-only) — não quebra.
# ═══════════════════════════════════════════════════════════════════════
with lib;

let
  cfg = config.services.litellm;
in
{
  # Só ativa quando o serviço upstream estiver ligado
  config = mkIf cfg.enable {
    services.litellm = {
      # Port 4000 — o default (8080) conflita com o llama-cpp-server
      port = 4000;
      host = "127.0.0.1";   # só local (JARVIS roda na mesma máquina)
      environmentFile = "/etc/litellm.env";

      settings = {
        # ── Modelos grátis (estratégia do legado, atualizada 08/2026) ──
        model_list = [
          {
            model_name = "local";
            litellm_params = {
              model = "openai/qwen3";
              api_base = "http://127.0.0.1:8080/v1";
              api_key = "local-not-needed";
            };
          }
          {
            model_name = "groq-free";
            litellm_params = {
              model = "groq/llama-3.3-70b-versatile";
              api_key = "os.environ/GROQ_API_KEY";
              fallbacks = [ "gemini-free" "openrouter-free" "local" ];
            };
          }
          {
            model_name = "gemini-free";
            litellm_params = {
              model = "gemini/gemini-2.5-flash";
              api_key = "os.environ/GEMINI_API_KEY";
              fallbacks = [ "openrouter-free" "local" ];
            };
          }
          {
            model_name = "openrouter-free";
            litellm_params = {
              model = "openrouter/meta-llama/llama-3.3-70b-instruct:free";
              api_key = "os.environ/OPENROUTER_API_KEY";
              fallbacks = [ "local" ];
            };
          }
        ];

        router_settings = {
          routing_strategy = "least-busy";   # rota p/ o modelo disponível mais rápido
          num_retries = 2;
          timeout = 120;
        };

        general_settings = {
          master_key = "os.environ/LITELLM_MASTER_KEY";
        };
      };
    };
  };
}
