{ pkgs, config, lib, ... }:

let
  piAgent = pkgs.writeShellApplication {
    name = "pi";
    runtimeInputs = with pkgs; [
      curl
      jq
    ];
    text = ''
      PROMPT="$*"

      if [ -z "$PROMPT" ]; then
        echo "Erro: Nenhum prompt informado."
        echo "Uso: pi \"sua instrução ou pergunta aqui\""
        exit 1
      fi

      ENDPOINT="http://127.0.0.1:8080/v1/chat/completions"

      PAYLOAD=$(jq -n \
        --arg prompt "$PROMPT" \
        '{
          model: "local-model",
          messages: [
            {
              role: "system",
              content: "Você é um agente de engenharia de software integrado a um ambiente NixOS declarativo."
            },
            {
              role: "user",
              content: $prompt
            }
          ],
          temperature: 0.2
        }')

      RESPONSE=$(curl -s -X POST "$ENDPOINT" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD")

      echo "$RESPONSE" | jq -r '.choices[0].message.content // .error.message // .'
    '';
  };
in
{
  home.packages = [
    piAgent
  ];

  xdg.configFile."pi/settings.json".text = builtins.toJSON {
    provider = "openai-compatible";
    baseUrl = "http://127.0.0.1:8080/v1";
    apiKey = "local-no-key";
    model = "local-model";
    temperature = 0.2;
    maxTokens = 4096;
    systemPrompt = "Você é um agente de engenharia de software integrado a um ambiente NixOS declarativo.";
    tools = {
      readFiles = true;
      writeFiles = true;
      executeCommand = true;
    };
  };
}
