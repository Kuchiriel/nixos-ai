{ pkgs, ... }:

let
  piAgent = pkgs.writers.writePython3Bin "pi" {
    libraries = [ pkgs.python3Packages.requests ];
    flakeIgnore = [ "E302" "E305" "W293" "E261" "F401" "E501" ];
  } ''
    import sys
    import json
    import subprocess
    import requests

    TOOLS = {
        "bash": "Executa comando shell: {'tool': 'bash', 'cmd': 'ls -la'}",
        "read_file": "Lê um arquivo: {'tool': 'read_file', 'path': '/etc/nixos/configuration.nix'}",
    }


    def clean_json_response(text):
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text


    def execute_tool(json_obj):
        try:
            if json_obj['tool'] == 'bash':
                res = subprocess.run(
                    json_obj['cmd'],
                    shell=True,
                    capture_output=True,
                    text=True
                )
                return res.stdout if res.returncode == 0 else res.stderr
            elif json_obj['tool'] == 'read_file':
                with open(json_obj['path'], 'r') as f:
                    return f.read()
        except Exception as e:
            return f"Erro na execução: {str(e)}"
        return "Ferramenta desconhecida."


    def query(messages):
        host = "127.0.0.1"
        port = "8080"
        url = f"http://{host}:{port}/v1/chat/completions"
        payload = {
            "model": "local-model",
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        response = requests.post(url, json=payload, timeout=60)
        data = response.json()
        return data['choices'][0]['message']['content']


    def main():
        user_input = " ".join(sys.argv[1:])
        system_prompt = (
            "Você é um agente técnico NixOS.\n"
            "Ferramentas disponíveis: bash, read_file\n"
            "Se precisar usar uma ferramenta, retorne APENAS um JSON bruto "
            "sem blocos markdown com o formato da ferramenta.\n"
            "Se não, responda normalmente ao usuário."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        reply = query(messages)
        cleaned_reply = clean_json_response(reply)

        try:
            tool_call = json.loads(cleaned_reply)
            if 'tool' in tool_call:
                output = execute_tool(tool_call)
                messages.append({"role": "assistant", "content": reply})
                messages.append({
                    "role": "user",
                    "content": f"Resultado da execução: {output}"
                })
                print(query(messages))
            else:
                print(reply)
        except json.JSONDecodeError:
            print(reply)


    if __name__ == "__main__":
        main()
  '';
in
{
  home.packages = [ piAgent ];
}
