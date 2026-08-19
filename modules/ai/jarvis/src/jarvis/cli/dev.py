"""jarvis dev — CLI interativo de desenvolvimento (estilo Aider).

REPL onde o usuário conversa com o agente e o agente pode:
  - Explorar a codebase (list_directory, code_search, read_file)
  - Editar arquivos (str_replace, write_file)
  - Rodar testes (run_tests, execute_shell)
  - Iterar sobre erros automaticamente

Uso:
  jarvis dev                    # inicia REPL no CWD
  jarvis dev --project /path    # inicia em diretório específico
  jarvis dev --approve          # ativa aprovação para comandos com efeito
  jarvis dev --once "tarefa"    # executa uma tarefa e sai

Inspirado em: Aider, Claude Code, pi (earendil-works).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


def _get_config():
    from jarvis.core.config import Config
    return Config()


def _detect_profile() -> dict[str, Any]:
    """Detecta o perfil do modelo."""
    cfg = _get_config()
    try:
        resp = requests.get(f"{cfg.llm_base_url.rstrip('/')}/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("data"):
            model_id = data["data"][0].get("id", "")
        else:
            model_id = ""
    except Exception:
        model_id = ""

    m = model_id.lower()
    if "32b" in m or "30b" in m:
        return {"name": "large", "max_tokens": 768, "temperature": 0.0}
    if "7b" in m:
        return {"name": "small", "max_tokens": 1024, "temperature": 0.0}
    if "4b" in m or "3b" in m or "1b" in m:
        return {"name": "tiny", "max_tokens": 512, "temperature": 0.0}
    return {"name": "default", "max_tokens": 1024, "temperature": 0.0}


SYSTEM_PROMPT = """You are JARVIS, a local-first dev assistant on NixOS. You can read, edit, and create files, search code, and run tests.

RESPOND IN PT-BR. Be concise and direct.

AVAILABLE TOOLS:
- read_file(path, offset?, limit?): Read a file
- write_file(path, content): Write/create a file (backup created)
- str_replace(path, old, new, allow_multiple?): Replace string in file (preferred for editing)
- list_directory(path?, max_depth?): List directory contents
- code_search(pattern, path?, max_results?): Search codebase
- run_tests(test_path?, pattern?, timeout?): Run pytest
- execute_shell(cmd): Run shell command

WORKFLOW:
1. Explore: list_directory / code_search to understand the codebase
2. Read: read_file to see relevant code
3. Edit: str_replace to make targeted changes (preferred over write_file)
4. Test: run_tests to validate changes
5. Iterate: if tests fail, read errors, fix, re-test

RULES:
- Always use str_replace for edits (safer than write_file)
- Run tests after every edit
- If a tool call fails, analyze the error and try a different approach
- Max 8 tool calls per turn to prevent loops
"""


def _call_llm(messages: list[dict[str, str]], tools: list[dict], profile: dict) -> dict:
    """Chama o LLM local."""
    cfg = _get_config()
    payload = {
        "model": cfg.llm_model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": profile["temperature"],
        "max_tokens": profile["max_tokens"],
        "parallel_tool_calls": False,
        "response_format": {"type": "json_object"},
    }
    if cfg.llm_disable_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}

    resp = requests.post(
        f"{cfg.llm_base_url.rstrip('/')}/chat/completions",
        json=payload,
        timeout=cfg.llm_timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _execute_tool_call(name: str, args: dict[str, Any], approve: bool = False) -> str:
    """Executa uma tool call e retorna o resultado."""
    from jarvis.core.devtools import handle_dev_tool
    from jarvis.core.agent import command_allowed
    import subprocess

    if name == "execute_shell":
        cmd = args.get("cmd", "")
        if not cmd:
            return "ERROR: empty command"
        if not command_allowed(cmd):
            if not approve:
                return f"ERROR: command not allowed: {cmd} (use --approve)"
            print(f"  ⚠  Comando: {cmd}")
            try:
                ans = input("  Permitir? [y/N] ").strip().lower()
            except EOFError:
                return "ERROR: approval denied (EOF)"
            if ans not in ("y", "yes", "s", "sim"):
                return "ERROR: command denied by user"
        try:
            res = subprocess.run(
                cmd.split(), capture_output=True, text=True, timeout=60,
            )
            output = res.stdout if res.returncode == 0 else res.stderr
            if not output.strip():
                output = f"(exit code {res.returncode})"
            return output[:3000]
        except subprocess.TimeoutExpired:
            return "ERROR: command timed out (60s)"
        except Exception as e:
            return f"ERROR: {e}"

    # Dev tools
    result = handle_dev_tool(name, args)
    # Trunca saída muito longa para o SLM
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and "entries" in parsed and len(parsed["entries"]) > 50:
            parsed["entries"] = parsed["entries"][:50]
            parsed["note"] = f"Truncated (showing 50 of {len(parsed['entries'])})"
            result = json.dumps(parsed, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass
    return result[:5000]


def _get_tools() -> list[dict[str, Any]]:
    """Retorna as tools disponíveis."""
    from jarvis.core.devtools import DEV_TOOLS
    from jarvis.core.vision import VISION_TOOL
    shell_tool = {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Shell command to execute."}
                },
                "required": ["cmd"],
            },
        },
    }
    return [shell_tool, VISION_TOOL, *DEV_TOOLS]


def _extract_tool_call(content: str) -> dict | None:
    """Extrai tool call do content (fallback para SLMs que vazam)."""
    import re
    tag_re = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
    codeblock_re = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

    for regex in [tag_re, codeblock_re]:
        match = regex.search(content)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict) and "name" in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

    # Tenta JSON solto
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "name" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    return None


def dev_repl(project_root: str | None = None, approve: bool = False) -> None:
    """REPL interativo do dev agent."""
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)

    profile = _detect_profile()
    tools = _get_tools()

    print(f"🤖 JARVIS Dev — SLM: {profile['name']} (max_tokens={profile['max_tokens']})")
    print(f"📁 Projeto: {os.getcwd()}")
    print(f"🔧 Tools: {len(tools)} disponíveis")
    print("   Comandos: /quit, /status, /clear, /help")
    print()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    while True:
        try:
            user_input = input("👤 Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Até logo!")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("👋 Até logo!")
            break
        if user_input == "/clear":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("🗑️  Contexto limpo.")
            continue
        if user_input == "/status":
            from jarvis.core.health_monitor import BackendHealthMonitor
            cfg = _get_config()
            monitor = BackendHealthMonitor(cfg.llm_base_url.replace("/v1", ""))
            status = monitor.status_dict()
            print(f"  Backend: {status['state']} ({status['latency_ms']}ms)")
            print(f"  Model: {profile['name']}")
            print(f"  Uptime: {status['uptime_pct']}%")
            continue
        if user_input == "/help":
            print("  /quit    — sair")
            print("  /clear   — limpar contexto")
            print("  /status  — status do backend")
            print("  /help    — esta ajuda")
            continue

        messages.append({"role": "user", "content": user_input})

        # Loop de tool calls (máx 8 por turno)
        for turn in range(8):
            print(f"  🤔 Pensando... (turno {turn + 1})", end="", flush=True)

            try:
                data = _call_llm(messages, tools, profile)
            except Exception as e:
                print(f"\n  ❌ Erro LLM: {e}")
                break

            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls")

            # Fallback: extrai tool call do content se não veio estruturado
            if not tool_calls and content:
                fallback = _extract_tool_call(content)
                if fallback:
                    tool_calls = [{
                        "id": "fallback-0",
                        "type": "function",
                        "function": {
                            "name": fallback["name"],
                            "arguments": json.dumps(fallback.get("arguments", {})),
                        },
                    }]
                    print(f" (recuperado via fallback)")
                else:
                    print()
            else:
                print()

            # Adiciona resposta do assistant
            messages.append({
                "role": "assistant",
                "content": "" if tool_calls else content,
                "tool_calls": tool_calls,
            })

            if not tool_calls:
                # Resposta final
                if content:
                    print(f"🤖 JARVIS: {content}")
                break

            # Executa tool calls
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                print(f"  🔧 {func_name}({args.get('path', args.get('cmd', ''))[:50]})")
                output = _execute_tool_call(func_name, args, approve)

                # Mostra resultado resumido
                try:
                    parsed = json.loads(output)
                    if isinstance(parsed, dict):
                        if parsed.get("ok"):
                            if "entries" in parsed:
                                print(f"  📂 {parsed.get('count', 0)} itens")
                            elif "content" in parsed:
                                lines = parsed.get("lines", 0)
                                total = parsed.get("total_lines", 0)
                                print(f"  📄 {lines}/{total} linhas")
                            elif "results" in parsed:
                                print(f"  🔍 {parsed.get('total', 0)} resultados")
                            elif "passed" in parsed:
                                p, f = parsed.get("passed", 0), parsed.get("failed", 0)
                                icon = "✅" if f == 0 else "❌"
                                print(f"  {icon} {p} passed, {f} failed")
                            elif "replacements" in parsed:
                                print(f"  ✏️  {parsed['replacements']} substituições")
                            elif "bytes" in parsed:
                                print(f"  💾 {parsed['bytes']} bytes escritos")
                            else:
                                print(f"  ✅ OK")
                        else:
                            print(f"  ⚠️  {parsed.get('error', 'erro')[:80]}")
                except (json.JSONDecodeError, TypeError):
                    if len(output) > 100:
                        print(f"  📤 {len(output)} chars")
                    else:
                        print(f"  📤 {output[:80]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": func_name,
                    "content": output[:5000],
                })


def dev_once(task: str, project_root: str | None = None, approve: bool = False) -> int:
    """Executa uma única tarefa e sai."""
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)

    profile = _detect_profile()
    tools = _get_tools()

    print(f"🤖 JARVIS Dev — {profile['name']}")
    print(f"📋 Tarefa: {task}")
    print()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for turn in range(10):
        try:
            data = _call_llm(messages, tools, profile)
        except Exception as e:
            print(f"❌ Erro LLM: {e}")
            return 1

        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")

        if not tool_calls and content:
            fallback = _extract_tool_call(content)
            if fallback:
                tool_calls = [{
                    "id": "fallback-0",
                    "type": "function",
                    "function": {
                        "name": fallback["name"],
                        "arguments": json.dumps(fallback.get("arguments", {})),
                    },
                }]

        messages.append({
            "role": "assistant",
            "content": "" if tool_calls else content,
            "tool_calls": tool_calls,
        })

        if not tool_calls:
            if content:
                print(f"🤖 {content}")
            return 0

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            print(f"  🔧 {func_name}({str(args)[:60]})")
            output = _execute_tool_call(func_name, args, approve)
            print(f"  → {output[:200]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "name": func_name,
                "content": output[:5000],
            })

    print("⚠️  Máximo de turnos atingido")
    return 1
