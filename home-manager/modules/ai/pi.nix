{ pkgs, ... }:

let
  piAgent = pkgs.writers.writePython3Bin "pi" {
    libraries = [];
    flakeIgnore = [ "E302" "E305" "W293" "E261" "F401" ];
  } ''
    import sys
    import json
    import subprocess
    import urllib.request

    TOOLS = {
        "bash": "Executa comando shell: {'tool': 'bash', 'cmd': 'ls -la'}",
        "read_file": "Lê um arquivo: {'tool': 'read_file', 'path': '/etc/nixos/configuration.nix'}",
    }


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
        payload = {
            "model": "local-model",
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        req = urllib.request.Request(
            "http://127.0.0.1:8080/v1/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content']


    def main():
        user_input = " ".join(sys.argv[1:])
        system_prompt = f"""Você é um agente técnico NixOS.
        Ferramentas disponíveis: {json.dumps(TOOLS)}
        Se precisar usar uma ferramenta, retorne APENAS um JSON com o formato da ferramenta.
        Se não, responda normalmente ao usuário."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        reply = query(messages)

        try:
            tool_call = json.loads(reply)
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
