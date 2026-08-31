"""
Real Agent Loop — executes tasks through the local LLM with tool calling.

This is the MINIMUM implementation needed to prove the harness works.
It calls the real LLM server, parses structured responses, executes tools,
and validates results.

Architecture:
  system prompt (persona)
  + task description
  + project context
  ↓
  LLM (via llama.cpp /chat/completions)
  ↓
  structured response (JSON action or text)
  ↓
  tool execution (if action requires it)
  ↓
  validation (AST, tests, syntax)
  ↓
  evidence collection
  ↓
  commit
"""

import ast
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# LLM Client — calls the real llama.cpp server
# ---------------------------------------------------------------------------

class LLMClient:
    """Minimal client for llama.cpp /chat/completions endpoint."""
    
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = (base_url or os.environ.get(
            "LLAMA_CPP_URL", "http://127.0.0.1:8080"
        )).rstrip("/")
        self.model = model or "default"
        self._query_context_size()
    
    def _query_context_size(self):
        """Query actual n_ctx from the server."""
        try:
            resp = requests.get(f"{self.base_url}/props", timeout=5)
            data = resp.json()
            settings = data.get("default_generation_settings", {})
            self.n_ctx = settings.get("n_ctx", 32768)
        except Exception:
            self.n_ctx = 32768
    
    def chat(self, messages: list[dict], tools: list[dict] = None,
             temperature: float = 0.3, max_tokens: int = 2048) -> dict:
        """Send a chat completion request to the LLM."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        t0 = time.monotonic()
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=300,
        )
        elapsed = time.monotonic() - t0
        resp.raise_for_status()
        data = resp.json()
        
        choice = data["choices"][0]
        message = choice["message"]
        
        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
            "finish_reason": choice.get("finish_reason", ""),
            "usage": data.get("usage", {}),
            "latency_seconds": elapsed,
        }


# ---------------------------------------------------------------------------
# Tool definitions — what the agent can do
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project. Returns the full content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates or overwrites.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "content": {"type": "string", "description": "Full file content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "str_replace",
            "description": "Surgically replace a string in a file. More precise than write_file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "old": {"type": "string", "description": "Exact string to replace"},
                    "new": {"type": "string", "description": "Replacement string"}
                },
                "required": ["path", "old", "new"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command. Returns stdout, stderr, and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_python",
            "description": "Validate a Python file parses as valid AST. Returns True/False and any errors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to Python file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run Python tests on a file or directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Test file or directory"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff of current changes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit current changes with a message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"}
                },
                "required": ["message"]
            }
        }
    },
]


# ---------------------------------------------------------------------------
# Tool executor — runs tools and returns structured results
# ---------------------------------------------------------------------------

class ToolExecutor:
    """Executes tool calls from the LLM and returns structured results."""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.tool_log: list[dict] = []
        self._file_snapshots: dict[str, str] = {}

    def snapshot_file(self, path: str) -> None:
        """Save file content before modification for rollback."""
        full = self.project_root / path
        if full.exists():
            self._file_snapshots[path] = full.read_text(errors="replace")

    def rollback_all(self) -> list[str]:
        """Restore all snapshotted files."""
        restored = []
        for path, content in self._file_snapshots.items():
            full = self.project_root / path
            full.write_text(content)
            restored.append(path)
        self._file_snapshots.clear()
        return restored

    def execute(self, tool_call: dict) -> dict:
        """Execute a single tool call and return structured result."""
        func_name = tool_call["function"]["name"]
        try:
            args = json.loads(tool_call["function"]["arguments"])
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON in arguments"}
        
        t0 = time.monotonic()
        result = self._dispatch(func_name, args)
        elapsed = time.monotonic() - t0
        
        log_entry = {
            "tool": func_name,
            "args": args,
            "success": result.get("success", False),
            "latency": round(elapsed, 3),
            "timestamp": time.time(),
        }
        self.tool_log.append(log_entry)
        
        result["tool"] = func_name
        result["latency_seconds"] = round(elapsed, 3)
        return result
    
    def _dispatch(self, name: str, args: dict) -> dict:
        dispatch = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "str_replace": self._str_replace,
            "run_command": self._run_command,
            "validate_python": self._validate_python,
            "run_tests": self._run_tests,
            "git_diff": self._git_diff,
            "git_commit": self._git_commit,
        }
        fn = dispatch.get(name)
        if not fn:
            return {"success": False, "error": f"Unknown tool: {name}"}
        try:
            return fn(**args)
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _read_file(self, path: str, **kw) -> dict:
        full = self.project_root / path
        if not full.exists():
            return {"success": False, "error": f"File not found: {path}"}
        content = full.read_text(errors="replace")
        return {"success": True, "content": content, "lines": len(content.splitlines())}
    
    def _write_file(self, path: str, content: str, **kw) -> dict:
        full = self.project_root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return {"success": True, "path": path, "lines": len(content.splitlines())}
    
    def _str_replace(self, path: str, old: str, new: str, **kw) -> dict:
        full = self.project_root / path
        if not full.exists():
            return {"success": False, "error": f"File not found: {path}"}
        content = full.read_text(errors="replace")
        if old not in content:
            return {"success": False, "error": f"String not found in {path}"}
        count = content.count(old)
        if count > 1:
            return {"success": False, "error": f"Ambiguous: {count} matches in {path}"}
        new_content = content.replace(old, new, 1)
        full.write_text(new_content)
        return {"success": True, "path": path, "replaced": True}
    
    def _run_command(self, command: str, **kw) -> dict:
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=120, cwd=str(self.project_root),
            )
            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout[-8000:],
                "stderr": result.stderr[-4000:],
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out (120s)"}
    
    def _validate_python(self, path: str, **kw) -> dict:
        full = self.project_root / path
        if not full.exists():
            return {"success": False, "error": f"File not found: {path}"}
        try:
            source = full.read_text(errors="replace")
            ast.parse(source)
            return {"success": True, "valid": True, "path": path}
        except SyntaxError as e:
            return {"success": False, "valid": False, "error": str(e), "line": e.lineno}
    
    def _run_tests(self, path: str, **kw) -> dict:
        return self._run_command(f"python3 -m unittest {path} -v 2>&1")
    
    def _git_diff(self, **kw) -> dict:
        return self._run_command("git diff --stat 2>&1")
    
    def _git_commit(self, message: str, **kw) -> dict:
        return self._run_command(
            f'git add -A && git commit -m "{message}" 2>&1'
        )


# ---------------------------------------------------------------------------
# AST Validator — structural validation before accepting changes
# ---------------------------------------------------------------------------

class ASTValidator:
    """Validates Python code structural integrity."""
    
    @staticmethod
    def validate(file_path: str) -> dict:
        """Validate a Python file parses correctly and has no obvious corruption."""
        try:
            with open(file_path) as f:
                source = f.read()
            tree = ast.parse(source)
            
            # Check for markdown fences outside strings
            in_docstring = False
            for i, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    in_docstring = not in_docstring
                if not in_docstring and '```' in line:
                    return {"valid": False, "error": f"Markdown fence at line {i}"}
            
            # Check imports are present
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
            
            return {"valid": True, "imports": imports, "lines": len(source.splitlines())}
        except SyntaxError as e:
            return {"valid": False, "error": str(e), "line": e.lineno}


# ---------------------------------------------------------------------------
# Agent Loop — the main execution cycle
# ---------------------------------------------------------------------------

class RealAgentLoop:
    """
    Executes a task through the local LLM with real tool calling.
    
    Flow:
      1. Build system prompt from persona
      2. Add task + context
      3. Call LLM
      4. If LLM returns tool calls → execute tools → feed results back
      5. Repeat until LLM produces final answer or max iterations
      6. Validate all changes with AST
      7. Run tests
      8. Collect evidence
      9. Commit
    """
    
    def __init__(self, project_root: str, persona: str = "backend_engineer",
                 max_iterations: int = 10, verbose: bool = True):
        self.project_root = project_root
        self.persona = persona
        self.max_iterations = max_iterations
        self.verbose = verbose
        
        self.llm = LLMClient()
        self.tools = ToolExecutor(project_root)
        self.validator = ASTValidator()
        
        self.messages: list[dict] = []
        self.tool_calls_made: list[dict] = []
        self.files_changed: set[str] = set()
        self.iteration = 0
        self.total_tokens = 0
        self.total_latency = 0.0
        self._consecutive_test_failures = 0
        self._rollback_threshold = 3  # rollback after 3 consecutive failures
    
    def _build_system_prompt(self, task: str, context: str = "") -> str:
        """Build system prompt incorporating persona."""
        persona_prompts = {
            "backend_engineer": (
                "You are a Backend Engineer working on a real project. "
                "You have access to file system tools. "
                "When you make changes, use str_replace for surgical edits, "
                "never write entire files unless creating new ones. "
                "Always validate Python files with validate_python after changes. "
                "Always run tests after changes. "
                "When done, call git_commit with a descriptive message. "
                "Be precise, minimal, and correct."
            ),
            "architect": (
                "You are a Software Architect. Focus on structural improvements, "
                "refactoring, and code quality. Read code before changing it."
            ),
            "qa_engineer": (
                "You are a QA Engineer. Focus on testing, validation, "
                "and finding issues. Write tests, run them, report results."
            ),
        }
        
        system = persona_prompts.get(self.persona, persona_prompts["backend_engineer"])
        
        if context:
            system += f"\n\nProject context:\n{context}"
        
        return system
    
    def run(self, task: str, context: str = "") -> dict:
        """Execute a task through the real LLM loop."""
        t0 = time.time()
        
        system_prompt = self._build_system_prompt(task, context)
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
        
        if self.verbose:
            print(f"\n{'='*60}")
            print(f"AGENT LOOP — Task: {task[:80]}")
            print(f"Persona: {self.persona}")
            print(f"Project: {self.project_root}")
            print(f"LLM: {self.llm.base_url}")
            print(f"Context: {self.llm.n_ctx} tokens")
            print(f"{'='*60}")
        
        final_response = ""
        
        for iteration in range(self.max_iterations):
            self.iteration = iteration + 1
            
            if self.verbose:
                print(f"\n--- Iteration {self.iteration}/{self.max_iterations} ---")
            
            # Call LLM
            response = self.llm.chat(
                messages=self.messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.3,
                max_tokens=2048,
            )
            
            self.total_tokens += response.get("usage", {}).get("total_tokens", 0)
            self.total_latency += response["latency_seconds"]
            
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])
            
            if self.verbose:
                print(f"  LLM responded in {response['latency_seconds']:.1f}s")
                if content:
                    print(f"  Content: {content[:200]}{'...' if len(content) > 200 else ''}")
                if tool_calls:
                    print(f"  Tool calls: {len(tool_calls)}")
            
            # Add assistant message to history
            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.messages.append(assistant_msg)
            
            # If no tool calls, this is the final response
            if not tool_calls:
                final_response = content
                break
            
            # Execute each tool call
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                if self.verbose:
                    args_preview = tc["function"].get("arguments", "")[:100]
                    print(f"  → {tool_name}({args_preview})")
                
                # Snapshot before modification for rollback
                if tool_name in ("write_file", "str_replace"):
                    try:
                        snap_args = json.loads(tc["function"]["arguments"])
                        self.tools.snapshot_file(snap_args.get("path", ""))
                    except Exception:
                        pass

                result = self.tools.execute(tc)
                self.tool_calls_made.append({
                    "tool": tool_name,
                    "args_preview": tc["function"].get("arguments", "")[:200],
                    "success": result.get("success", False),
                    "latency": result.get("latency_seconds", 0),
                })
                
                if result.get("success"):
                    # Track file changes
                    if tool_name in ("write_file", "str_replace"):
                        path = result.get("path", "")
                        if path:
                            self.files_changed.add(path)
                            self._consecutive_test_failures = 0  # reset on progress
                else:
                    # Deferred rollback: track consecutive test failures
                    if tool_name == "run_command":
                        try:
                            cmd_args = json.loads(tc["function"]["arguments"])
                            cmd = cmd_args.get("command", "")
                            if any(w in cmd.lower() for w in ["test", "unittest", "pytest"]):
                                self._consecutive_test_failures += 1
                                if self.verbose:
                                    print(f"    Test failed ({self._consecutive_test_failures}/{self._rollback_threshold} before rollback)")
                                if self._consecutive_test_failures >= self._rollback_threshold:
                                    restored = self.tools.rollback_all()
                                    if restored and self.verbose:
                                        print(f"    ROLLBACK: restored {restored}")
                                    self.files_changed -= set(restored)
                                    self._consecutive_test_failures = 0
                        except Exception:
                            pass
                
                if self.verbose:
                    status = "✅" if result.get("success") else "❌"
                    print(f"    {status} {result.get('tool', '?')}: {result.get('success', False)}")
                
                # Add tool result to messages
                self.messages.append({
                    "role": "tool",
                    "content": json.dumps(result, default=str),
                })
        
        # Post-execution validation
        validation_results = []
        for f in self.files_changed:
            if f.endswith(".py"):
                v = self.validator.validate(str(Path(self.project_root) / f))
                v["file"] = f
                validation_results.append(v)
                if self.verbose:
                    status = "✅" if v.get("valid") else "❌"
                    print(f"  AST {status}: {f}")
        
        duration = time.time() - t0
        
        return {
            "task": task,
            "persona": self.persona,
            "project": str(self.project_root),
            "iterations": self.iteration,
            "final_response": final_response[:500],
            "tool_calls_count": len(self.tool_calls_made),
            "tool_calls": self.tool_calls_made,
            "files_changed": list(self.files_changed),
            "validation": validation_results,
            "total_tokens": self.total_tokens,
            "total_latency": round(self.total_latency, 2),
            "duration": round(duration, 2),
        }


# ---------------------------------------------------------------------------
# Quick test if run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent = RealAgentLoop(
        project_root=os.path.expanduser("~/projects/Corretor"),
        persona="backend_engineer",
        max_iterations=5,
    )
    result = agent.run(
        task="Read corretor.py and tell me: what Python version is this written for? "
             "List any Python 2 specific syntax you find.",
    )
    print("\n" + "="*60)
    print("RESULT:")
    print(json.dumps(result, indent=2, default=str))
