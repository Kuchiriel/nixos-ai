{ pkgs, ... }:

let
  piAgent = pkgs.writers.writePython3Bin "pi" {
    libraries = [ pkgs.python3Packages.requests ];
  } ''
    import sys
    import json
    import subprocess
    import requests

    def execute_tool(json_obj):
        try:
            if json_obj.get('tool') == 'bash':
                res = subprocess.run(json_obj['cmd'], shell=True, capture_output=True, text=True)
                return res.stdout if res.returncode == 0 else res.stderr
            return "Erro: Ferramenta desconhecida."
        except Exception as e:
            return f"Erro na execução: {str(e)}"

    def main():
        user_input = " ".join(sys.argv[1:])
        
        # System Prompt focado em execução direta
        system_prompt = (
            "Você é um executor de comandos NixOS. "
            "Sua tarefa é identificar a necessidade de um comando shell e executar. "
            "Retorne APENAS o JSON no formato: {'tool': 'bash', 'cmd': 'comando_aqui'}. "
            "Não adicione textos extras."
        )

        payload = {
            "model": "local-model",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        # Query
        try:
            resp = requests.post("http://127.0.0.1:8080/v1/chat/completions", json=payload, timeout=10)
            reply = resp.json()['choices'][0]['message']['content']
            
            tool_call = json.loads(reply)
            
            if 'tool' in tool_call:
                # Executa e printa o resultado DO COMANDO, não do JSON
                print(execute_tool(tool_call))
            else:
                print(reply)
        except Exception as e:
            print(f"Erro no pi: {e}")

    if __name__ == "__main__":
        main()
  '';
in
{
  home.packages = [ piAgent ];
}
