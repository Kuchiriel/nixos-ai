{ pkgs, ... }:

let
  pi = pkgs.writers.writePython3Bin "pi" {
    libraries = [ pkgs.python3Packages.requests ];
  } ''
    import json
    import os
    import subprocess
    import sys
    import requests

    SERVER_URL = os.getenv(
        "LLAMA_SERVER_URL",
        "http://127.0.0.1:8080/v1/chat/completions"
    )

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "execute_shell",
                "description": "Execute a shell command on the local NixOS system.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {
                            "type": "string",
                            "description": "The exact shell command to execute."
                        }
                    },
                    "required": ["cmd"]
                }
            }
        }
    ]


    def run_agent(user_prompt):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a pragmatic system administration assistant on NixOS. "
                    "Use the execute_shell tool to gather data or perform actions."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]

        for _ in range(5):
            payload = {
                "model": "default",
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.0,
            }

            try:
                resp = requests.post(SERVER_URL, json=payload, timeout=60)
                if resp.status_code != 200:
                    print(
                        f"Erro HTTP {resp.status_code}: {resp.text}",
                        file=sys.stderr
                    )
                    sys.exit(1)

                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]
                messages.append(message)

                if message.get("tool_calls"):
                    for tool_call in message["tool_calls"]:
                        func_name = tool_call["function"]["name"]
                        raw_args = tool_call["function"]["arguments"]

                        # Normalização defensiva (Trata dict retornado pelo llama-server)
                        if isinstance(raw_args, (dict, list)):
                            args = raw_args
                        else:
                            if not raw_args or not raw_args.strip():
                                args = {}
                            else:
                                args = json.loads(raw_args)

                        if func_name == "execute_shell":
                            cmd = args.get("cmd", "")
                            print(f"-> Executando: {cmd}")
                            
                            res = subprocess.run(
                                cmd,
                                shell=True,
                                capture_output=True,
                                text=True
                            )
                            output = res.stdout if res.returncode == 0 else res.stderr
                            if not output.strip():
                                output = f"Command executed with exit code {res.returncode}"

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": output
                            })
                else:
                    print(message.get("content", ""))
                    break

            except Exception as e:
                print(f"Erro crítico: {e}", file=sys.stderr)
                sys.exit(1)


    if __name__ == "__main__":
        if len(sys.argv) < 2:
            print("Uso: pi \"seu prompt aqui\"", file=sys.stderr)
            sys.exit(1)
        run_agent(" ".join(sys.argv[1:]))
  '';
in
{
  home.packages = [ pi ];
}
