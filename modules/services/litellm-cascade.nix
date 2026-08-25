{
  config,
  lib,
  ...
}:
# ═══════════════════════════════════════════════════════════════════════
# LITELLM-CASCADE — cascade/fallback/handover de modelos
#
# Estratégia:
#   1. LOCAL primeiro (llama-cpp) — zero custo, privado
#   2. Se falhar → nuvem grátis: Groq → Gemini → OpenRouter
#   3. JARVIS usa UM endpoint (http://127.0.0.1:4000/v1)
#
# API keys: /etc/litellm.env (chmod 600, fora do repo)
# ═══════════════════════════════════════════════════════════════════════
with lib; let
  cfg = config.services.litellm;
in {
  config = mkIf (config.services.jarvis.enable && cfg.enable) {
    services.litellm = {
      port = 4000;
      host = "127.0.0.1";
      environmentFile = "/etc/litellm.env";

      settings = {
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
              fallbacks = ["gemini-free" "openrouter-free" "local"];
            };
          }
          {
            model_name = "gemini-free";
            litellm_params = {
              model = "gemini/gemini-2.5-flash";
              api_key = "os.environ/GEMINI_API_KEY";
              fallbacks = ["openrouter-free" "local"];
            };
          }
          {
            model_name = "openrouter-free";
            litellm_params = {
              model = "openrouter/meta-llama/llama-3.3-70b-instruct:free";
              api_key = "os.environ/OPENROUTER_API_KEY";
              fallbacks = ["local"];
            };
          }
        ];

        router_settings = {
          routing_strategy = "least-busy";
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
