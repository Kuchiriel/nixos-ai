{ pkgs, ... }:

let
  # GBNF Gramática que força o modelo a retornar APENAS o formato desejado.
  # Isso elimina a necessidade de prompts complexos ou "agentes".
  piGrammar = ''
    root ::= "{" ws "\"cmd\"" ws ":" ws string ws "}"
    string ::= "\"" ([^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]))* "\""
    ws ::= [ \t\n]*
  '';

  pi = pkgs.writePython3Bin "pi" {
    libraries = [ pkgs.python3Packages.requests ];
  } ''
    import sys, json, subprocess, requests, os

    # Configuração via variáveis de ambiente ou defaults
    SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8080/completion")
    
    def pi_exec(prompt):
        # Gramática embutida para forçar JSON puro
        grammar = r"""${piGrammar}"""
        
        payload = {
            "prompt": f"Convert the following request into a single shell command JSON. Request: {prompt}",
            "n_predict": 128,
            "grammar": grammar,
            "temperature": 0.0 # Determinístico
        }
        
        try:
            resp = requests.post(SERVER_URL, json=payload, timeout=10)
            data = resp.json()
            # O servidor garante a estrutura via gramática
            cmd = json.loads(data['content'])['cmd']
            
            # Executa diretamente no contexto do shell NixOS
            # Sem eval, sem agentes, sem arquivos extras
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
  # Injeta o executável no ambiente
  home.packages = [ pi ];
}
