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
        "http://127.0.0.1:8080/completion"
    )

    GRAMMAR = (
        'root ::= "{" ws "\\"cmd\\"" ws ":" ws string ws "}\\n"'
        'string ::= "\\"" ([^"\\\\] | "\\\\" '
        '(["\\\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] '
        '[0-9a-fA-F] [0-9a-fA-F]))* "\\""\\n"'
        'ws ::= [ \\t\\n]*\\n'
    )


    def pi_exec(prompt):
        msg = (
            "Convert the following request into a single "
            f"shell command JSON. Request: {prompt}"
        )
        payload = {
            "prompt": msg,
            "n_predict": 128,
            "grammar": GRAMMAR,
            "temperature": 0.0,
        }

        try:
            resp = requests.post(
                SERVER_URL, json=payload, timeout=10
            )
            data = resp.json()
            cmd = json.loads(data["content"])["cmd"]

            print(f"-> Executando: {cmd}")
            subprocess.run(cmd, shell=True, check=True)

        except Exception as e:
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)


    if __name__ == "__main__":
        pi_exec(" ".join(sys.argv[1:]))
  '';
in
{
  home.packages = [ pi ];
}
