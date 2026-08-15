{ pkgs, config, lib, ... }:

let
  piAgent = pkgs.writers.writePython3Bin "pi" {
    libraries = [];
    flakeIgnore = [ "E501" "W293" ];
  } ''
    import sys
    import subprocess
    import re
    import urllib.request
    import json

    BASE_URL = "http://127.0.0.1:8080/v1"
    ENDPOINT = f"{BASE_URL}/chat/completions"


    def get_model():
        try:
            req = urllib.request.Request(f"{BASE_URL}/models")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data['data'][0]['id']
        except Exception:
            return "local-model"


    def query_llama(messages, model):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1
        }
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data['choices'][0]['message']['content']


    def main():
        if len(sys.argv) < 2:
            print("Uso: pi \"<prompt>\"")
            sys.exit(1)
            
        user_prompt = " ".join(sys.argv[1:])
        model = get_model()
        
        system_prompt = (
            "Você é um agente de engenharia de software integrado a um ambiente NixOS. "
            "Para coletar dados ou executar ações no sistema, você DEVE retornar um bloco de código bash exatamente assim:\n"
            "```bash\ncomando\n```\n"
            "O sistema executará o comando e retornará a saída para você continuar. "
            "Quando tiver todas as informações, responda diretamente ao usuário sem blocos de comando."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        for _ in range(5):
            reply = query_llama(messages, model)
            
            match = re.search(r"```bash\n(.*?)\n```", reply, re.DOTALL)
            if not match:
                print(reply)
                break
                
            command = match.group(1).strip()
            print(f"[Executando]: {command}", file=sys.stderr)
            
            res = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = res.stdout if res.returncode == 0 else res.stderr
            if not output.strip():
                output = "[Comando executado com sucesso, sem output]"
                
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "system", "content": f"Command output:\n{output}"})


    if __name__ == "__main__":
        main()
  '';
in
{
  home.packages = [
    piAgent
  ];

  xdg.configFile."pi/settings.json".text = builtins.toJSON {
    provider = "openai-compatible";
    baseUrl = "http://127.0.0.1:8080/v1";
    apiKey = "local-no-key";
    temperature = 0.1;
    maxTokens = 4096;
    systemPrompt = "Você é um agente de engenharia de software integrado a um ambiente NixOS declarativo.";
    tools = {
      readFiles = true;
      writeFiles = true;
      executeCommand = true;
    };
  };
}
