{pkgs, ...}: let
  pi =
    pkgs.writers.writePython3Bin "pi" {
      libraries = [pkgs.python3Packages.requests];
    } ''
      import json
      import os
      import re
      import subprocess
      import sys
      import requests

      # --------------------------------------------------------------------
      # Config via env (definido no systemd unit / home-manager, ver abaixo)
      # --------------------------------------------------------------------
      SERVER_URL = os.getenv(
          "LLAMA_SERVER_URL",
          "http://127.0.0.1:8080/v1/chat/completions"
      )
      MODELS_URL = os.getenv(
          "LLAMA_MODELS_URL",
          "http://127.0.0.1:8080/v1/models"
      )
      MAX_REPAIR_RETRIES = int(os.getenv("PI_MAX_REPAIR_RETRIES", "2"))
      MAX_TURNS = int(os.getenv("PI_MAX_TURNS", "8"))
      DEBUG = os.getenv("PI_DEBUG", "0") == "1"

      TOOLS = [
          {
              "type": "function",
              "function": {
                  "name": "execute_shell",
                  "description": (
                      "Execute a shell command "
                      "on the local NixOS system."
                  ),
                  "parameters": {
                      "type": "object",
                      "properties": {
                          "cmd": {
                              "type": "string",
                              "description": (
                                  "The exact shell command "
                                  "to execute."
                              )
                          }
                      },
                      "required": ["cmd"]
                  }
              }
          }
      ]

      # --------------------------------------------------------------------
      # Fallback de recuperação (estilo Aider): o llama-server com
      # Qwen2.5-Coder às vezes NÃO entra na gramática Hermes 2 Pro e
      # devolve o tool_call como texto puro em `content` em vez de
      # `tool_calls[]` estruturado (bug documentado com Qwen2.5-Coder-32B
      # + tool_choice="auto" no llama.cpp). Capturamos os dois formatos
      # nativos do Qwen: <tool_call>{...}</tool_call> e JSON solto.
      # --------------------------------------------------------------------
      TOOL_CALL_TAG_RE = re.compile(
          r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL
      )
      BARE_JSON_RE = re.compile(
          r"(\{[^{}]*\"name\"\s*:\s*\"[^\"]+\"[^{}]*"
          r"\"arguments\"\s*:\s*\{.*?\}\s*\})",
          re.DOTALL
      )


      def extract_fallback_tool_call(content):
          if not content:
              return None
          match = TOOL_CALL_TAG_RE.search(content) or BARE_JSON_RE.search(content)
          if not match:
              return None
          try:
              parsed = json.loads(match.group(1))
              name = parsed.get("name")
              if not name:
                  return None
              arguments = parsed.get("arguments", {})
              if isinstance(arguments, str):
                  arguments = json.loads(arguments) if arguments.strip() else {}
              return {"name": name, "arguments": arguments}
          except (json.JSONDecodeError, AttributeError):
              return None

      # --------------------------------------------------------------------
      # Perfis adaptativos: o mesmo binário `pi` se comporta diferente
      # dependendo de qual modelo o llama-server está servindo no momento
      # (7B na VM vs 32B bare-metal, ver modules/services/llama-cpp.nix).
      # Detecção via /v1/models, sem hardcode de caminho de modelo.
      # --------------------------------------------------------------------


      def detect_profile():
          model_id = ""
          try:
              resp = requests.get(MODELS_URL, timeout=5)
              resp.raise_for_status()
              data = resp.json()
              if data.get("data"):
                  model_id = data["data"][0].get("id", "")
          except Exception:
              pass

          m = model_id.lower()

          if "32b" in m or "30b" in m:
              # Modelo maior: mais capaz semanticamente, porém é onde o
              # bug de "vazamento" de tool_call como texto é mais comum.
              # Reduzimos max_tokens por turno para forçar respostas mais
              # objetivas e cortar o "overthinking" que precede o vazamento.
              return {
                  "name": "large",
                  "model_id": model_id,
                  "temperature": 0.0,
                  "tool_choice": "auto",
                  "parallel_tool_calls": False,
                  "max_tokens_per_turn": 768,
              }
          elif "7b" in m:
              return {
                  "name": "small",
                  "model_id": model_id,
                  "temperature": 0.0,
                  "tool_choice": "auto",
                  "parallel_tool_calls": False,
                  "max_tokens_per_turn": 1024,
              }
          else:
              return {
                  "name": "default",
                  "model_id": model_id,
                  "temperature": 0.0,
                  "tool_choice": "auto",
                  "parallel_tool_calls": False,
                  "max_tokens_per_turn": 1024,
              }


      def call_server(messages, profile):
          payload = {
              "model": "default",
              "messages": messages,
              "tools": TOOLS,
              "tool_choice": profile["tool_choice"],
              "temperature": profile["temperature"],
              "max_tokens": profile["max_tokens_per_turn"],
              "parallel_tool_calls": profile["parallel_tool_calls"],
          }
          resp = requests.post(SERVER_URL, json=payload, timeout=120)
          if resp.status_code != 200:
              print(
                  f"Erro HTTP {resp.status_code}: {resp.text}",
                  file=sys.stderr
              )
              sys.exit(1)
          return resp.json()


      def run_shell_tool(cmd):
          print(f"-> Executando: {cmd}")
          res = subprocess.run(
              cmd, shell=True, capture_output=True, text=True
          )
          output = res.stdout if res.returncode == 0 else res.stderr
          if not output.strip():
              output = f"Command executed with exit code {res.returncode}"
          return output


      def run_agent(user_prompt):
          profile = detect_profile()
          if DEBUG:
              print(f"[pi] Perfil detectado: {profile}", file=sys.stderr)

          messages = [
              {
                  "role": "system",
                  "content": (
                      "You are a pragmatic system administration assistant "
                      "on NixOS. Use the execute_shell tool to gather data "
                      "or perform actions. When you decide to call a tool, "
                      "ALWAYS wrap the call exactly as "
                      "<tool_call>{\"name\": ..., \"arguments\": {...}}"
                      "</tool_call> and never mix a tool call with prose "
                      "in the same message."
                  ),
              },
              {"role": "user", "content": user_prompt},
          ]

          repair_attempts = 0

          for _ in range(MAX_TURNS):
              try:
                  data = call_server(messages, profile)
              except Exception as e:
                  print(f"Erro crítico: {e}", file=sys.stderr)
                  sys.exit(1)

              choice = data["choices"][0]
              message = choice["message"]
              content = message.get("content") or ""
              tool_calls = message.get("tool_calls")

              recovered = False
              if not tool_calls:
                  fallback = extract_fallback_tool_call(content)
                  if fallback is not None:
                      tool_calls = [{
                          "id": "fallback-0",
                          "type": "function",
                          "function": {
                              "name": fallback["name"],
                              "arguments": json.dumps(fallback["arguments"]),
                          },
                      }]
                      recovered = True
                      if DEBUG:
                          print(
                              f"[pi] Tool call recuperado via fallback de "
                              f"texto: {fallback['name']}",
                              file=sys.stderr
                          )

              messages.append({
                  "role": "assistant",
                  "content": "" if (tool_calls and not recovered) else content,
                  "tool_calls": tool_calls,
              })

              if not tool_calls:
                  print(content)
                  break

              for tool_call in tool_calls:
                  func_name = tool_call["function"]["name"]
                  raw_args = tool_call["function"]["arguments"]

                  if isinstance(raw_args, (dict, list)):
                      args = raw_args
                  elif not raw_args or not raw_args.strip():
                      args = {}
                  else:
                      try:
                          args = json.loads(raw_args)
                      except json.JSONDecodeError:
                          repair_attempts += 1
                          if repair_attempts > MAX_REPAIR_RETRIES:
                              print(
                                  f"Erro: JSON de argumentos malformado "
                                  f"após {MAX_REPAIR_RETRIES} tentativas "
                                  f"de reparo: {raw_args}",
                                  file=sys.stderr,
                              )
                              sys.exit(1)
                          messages.append({
                              "role": "tool",
                              "tool_call_id": tool_call.get("id", ""),
                              "name": func_name,
                              "content": (
                                  f"ERROR: invalid JSON in arguments: "
                                  f"{raw_args!r}. Reissue the tool call "
                                  "with strictly valid JSON arguments."
                              ),
                          })
                          continue

                  if func_name == "execute_shell":
                      output = run_shell_tool(args.get("cmd", ""))
                  else:
                      output = f"Unknown tool: {func_name}"

                  messages.append({
                      "role": "tool",
                      "tool_call_id": tool_call.get("id", ""),
                      "name": func_name,
                      "content": output,
                  })
          else:
              print(
                  "Erro: número máximo de iterações atingido sem "
                  "resposta final.",
                  file=sys.stderr
              )
              sys.exit(1)


      if __name__ == "__main__":
          if len(sys.argv) < 2:
              print(
                  "Uso: pi \"seu prompt aqui\"",
                  file=sys.stderr
              )
              sys.exit(1)
          run_agent(" ".join(sys.argv[1:]))
    '';
in {
  home.packages = [pi];
}
