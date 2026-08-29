"""Nightwatch v3 — LLM-Powered Autonomous Code Improvement

Uses the local LLM (via llama.cpp) to:
1. Read code
2. Understand what could be improved
3. Make actual improvements
4. Test them
5. Commit if good

Inspired by:
- The "Ralph Wiggum" technique (Addy Osmani, Ryan Carson)
- Self-improving coding agents
- Compound Product philosophy

Key principles:
1. Each iteration is isolated (fresh context)
2. LLM reads code, proposes improvements
3. Improvements are tested automatically
4. Only committed if tests pass
5. Learnings are persisted to AGENTS.md
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


# ═══ Configuration ═══

LLAMA_CPP_URL = os.environ.get("LLAMA_CPP_URL", "http://127.0.0.1:8080")
REPO_ROOT = Path.home() / "projects" / "nixos-ai"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
PROGRESS_LOG = Path.home() / ".local/state/jarvis/nightwatch/progress.jsonl"
TASK_STATE = Path.home() / ".local/state/jarvis/nightwatch/tasks.json"


@dataclass
class Task:
    """A single improvement task for the LLM."""
    id: str
    description: str
    target_files: list[str]
    acceptance_criteria: str
    status: str = "pending"  # pending, in_progress, completed, failed


@dataclass
class IterationResult:
    """Result of a single LLM iteration."""
    task_id: str
    success: bool
    files_changed: list[str]
    tests_passed: bool
    commit_sha: str | None
    learnings: str
    error: str | None = None


# ═══ LLM Interface ═══

def call_llm(prompt: str, max_tokens: int = 2048, disable_thinking: bool = True) -> str:
    """Call the local LLM via llama.cpp API."""
    try:
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,  # Low temp for focused code improvement
        }
        
        # Disable thinking for code generation (faster, more tokens for actual content)
        if disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        
        response = requests.post(
            f"{LLAMA_CPP_URL}/v1/chat/completions",
            json=payload,
            timeout=300,  # 5 minutes for code generation
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        
        # Handle thinking/reasoning models
        content = message.get("content", "")
        reasoning = message.get("reasoning_content", "")
        
        # If content is empty but reasoning exists, use reasoning
        if not content and reasoning:
            return reasoning
        
        return content
    except Exception as e:
        return f"ERROR: LLM call failed: {e}"


def read_file(path: str) -> str:
    """Read a file from the repo."""
    try:
        # Handle both absolute and relative paths
        if path.startswith("/"):
            full_path = Path(path)
        else:
            # Remove common prefixes the LLM might add
            for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
                if path.startswith(prefix):
                    path = path[len(prefix):]
                    break
            full_path = REPO_ROOT / "modules/ai/jarvis/src" / path
        
        if not full_path.exists():
            # Try alternative locations
            alt_paths = [
                REPO_ROOT / path,
                REPO_ROOT / "modules/ai/jarvis/src" / path,
                REPO_ROOT / "src" / path,
            ]
            for alt in alt_paths:
                if alt.exists():
                    full_path = alt
                    break
        
        return full_path.read_text(encoding="utf-8")[:8000]  # Limit to 8K chars
    except Exception as e:
        return f"ERROR: Could not read {path}: {e}"


def write_file(path: str, content: str) -> bool:
    """Write a file to the repo."""
    try:
        # Handle both absolute and relative paths
        if path.startswith("/"):
            full_path = Path(path)
        else:
            # Remove common prefixes the LLM might add
            for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
                if path.startswith(prefix):
                    path = path[len(prefix):]
                    break
            full_path = REPO_ROOT / "modules/ai/jarvis/src" / path
        
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"ERROR: Could not write {path}: {e}")
        return False


def run_tests() -> tuple[bool, str]:
    """Run the test suite and return (passed, output)."""
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "modules/ai/jarvis/tests/test_agent.py", "-x", "-q", "--tb=short"],
            capture_output=True, text=True, timeout=120,
            cwd=str(REPO_ROOT),
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output[:3000]
    except Exception as e:
        return False, f"Test error: {e}"


def git_commit(message: str) -> str | None:
    """Commit changes and return SHA."""
    try:
        subprocess.run(["git", "add", "-A"], capture_output=True, timeout=10, cwd=str(REPO_ROOT))
        result = subprocess.run(
            ["git", "commit", "-m", message, "--no-verify"],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
            ).stdout.strip()
            return sha
    except Exception:
        pass
    return None


def git_diff() -> str:
    """Get current git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=10, cwd=str(REPO_ROOT),
        )
        return result.stdout
    except Exception:
        return ""


# ═══ Task Discovery ═══

def discover_tasks_from_llm() -> list[Task]:
    """Use the LLM to discover improvement tasks in the codebase."""
    
    # Get a high-level view of the codebase
    repo_map = subprocess.run(
        ["find", str(REPO_ROOT / "modules/ai/jarvis/src"), "-name", "*.py", "-type", "f"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip().split("\n")[:30]  # Limit to 30 files
    
    prompt = f"""You are analyzing a Python codebase for improvement opportunities.

The project is an AI agent harness called JARVIS with:
- CLI (dev.py)
- MCP server (mcp_server.py)
- Agent core (agent.py, devtools.py)
- Memory system (memory.py, vault.py)
- RAG system (rag.py)
- Nightwatch autonomous loop

Key files:
{chr(10).join(repo_map[:20])}

Analyze this codebase and identify 3-5 specific, actionable improvement tasks.
For each task, provide:
1. A short description
2. Which files to modify
3. Acceptance criteria (how to verify it works)

Focus on:
- Code quality improvements
- Missing error handling
- Performance optimizations
- Security improvements
- Documentation gaps
- Test coverage

Return as JSON array:
[
  {{
    "description": "...",
    "target_files": ["file1.py", "file2.py"],
    "acceptance_criteria": "..."
  }}
]"""
    
    response = call_llm(prompt, max_tokens=1500)
    
    # Parse JSON from response
    try:
        # Find JSON in response
        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            tasks_data = json.loads(response[start:end])
            tasks = []
            for i, t in enumerate(tasks_data):
                tasks.append(Task(
                    id=f"llm-{int(time.time())}-{i}",
                    description=t.get("description", ""),
                    target_files=t.get("target_files", []),
                    acceptance_criteria=t.get("acceptance_criteria", ""),
                ))
            return tasks
    except json.JSONDecodeError:
        pass
    
    # Fallback: return a generic task
    return [Task(
        id=f"llm-{int(time.time())}",
        description="Review and improve code quality in agent.py",
        target_files=["modules/ai/jarvis/src/jarvis/core/agent.py"],
        acceptance_criteria="Tests pass, code is cleaner",
    )]


# ═══ LLM Improvement Loop ═══

def llm_improve_task(task: Task) -> IterationResult:
    """Use the LLM to improve code for a specific task."""
    
    # Read the target files
    file_contents = {}
    for path in task.target_files:
        content = read_file(path)
        if not content.startswith("ERROR"):
            file_contents[path] = content
    
    if not file_contents:
        return IterationResult(
            task_id=task.id,
            success=False,
            files_changed=[],
            tests_passed=False,
            commit_sha=None,
            learnings="Could not read target files",
            error="No files readable",
        )
    
    # Ask LLM to improve the code
    prompt = f"""You are improving Python code for an AI agent harness.

Task: {task.description}

Acceptance criteria: {task.acceptance_criteria}

Current code:
{chr(10).join(f"=== {path} ==={chr(10)}{content[:3000]}" for path, content in file_contents.items())}

Provide the improved code. For each file you want to change, use this format:

=== FILE: path/to/file.py ===
```python
# improved code here
```

Rules:
1. Only change what's needed for the task
2. Preserve existing functionality
3. Add error handling where missing
4. Follow existing code style
5. Don't add unnecessary complexity

If no changes are needed, respond with "NO_CHANGES_NEEDED"."""
    
    response = call_llm(prompt, max_tokens=3000)
    
    if "NO_CHANGES_NEEDED" in response:
        return IterationResult(
            task_id=task.id,
            success=True,
            files_changed=[],
            tests_passed=True,
            commit_sha=None,
            learnings="LLM determined no changes were needed",
        )
    
    # Parse and apply changes
    files_changed = []
    current_file = None
    current_content = []
    
    for line in response.split("\n"):
        if line.startswith("=== FILE: ") and line.endswith(" ==="):
            # Save previous file if any
            if current_file and current_content:
                new_content = "\n".join(current_content)
                # Extract code from markdown blocks
                if "```python" in new_content:
                    start = new_content.find("```python") + 9
                    end = new_content.find("```", start)
                    if end > start:
                        new_content = new_content[start:end].strip()
                
                if write_file(current_file, new_content):
                    files_changed.append(current_file)
            
            current_file = line[10:-4]  # Extract path
            current_content = []
        elif current_file is not None:
            current_content.append(line)
    
    # Save last file
    if current_file and current_content:
        new_content = "\n".join(current_content)
        if "```python" in new_content:
            start = new_content.find("```python") + 9
            end = new_content.find("```", start)
            if end > start:
                new_content = new_content[start:end].strip()
        
        if write_file(current_file, new_content):
            files_changed.append(current_file)
    
    # Run tests
    tests_passed, test_output = run_tests()
    
    # Commit if tests pass
    commit_sha = None
    if tests_passed and files_changed:
        commit_sha = git_commit(f"nightwatch(llm): {task.description}")
    
    return IterationResult(
        task_id=task.id,
        success=tests_passed,
        files_changed=files_changed,
        tests_passed=tests_passed,
        commit_sha=commit_sha,
        learnings=f"Changed {len(files_changed)} files, tests {'passed' if tests_passed else 'failed'}",
    )


# ═══ Main Loop ═══

def run_llm_nightwatch(max_iterations: int = 5, max_minutes: int = 60) -> list[IterationResult]:
    """Run the LLM-powered nightwatch loop.
    
    Each iteration:
    1. LLM discovers tasks
    2. LLM improves code
    3. Tests run
    4. Changes committed if tests pass
    5. Learnings persisted
    """
    results = []
    started = time.time()
    
    print("🌙 LLM Nightwatch Starting...")
    print(f"Max iterations: {max_iterations}")
    print(f"Max minutes: {max_minutes}")
    print(f"LLM endpoint: {LLAMA_CPP_URL}")
    print()
    
    # Send start notification
    send_telegram(f"🌙 *Nightwatch Started*\nMax iterations: {max_iterations}\nMax minutes: {max_minutes}")
    
    for i in range(max_iterations):
        if (time.time() - started) > max_minutes * 60:
            print(f"⏰ Time limit reached ({max_minutes} minutes)")
            break
        
        print(f"━━━ Iteration {i+1}/{max_iterations} ━━━")
        
        # 1. Discover tasks
        print("🔍 Discovering tasks...")
        tasks = discover_tasks_from_llm()
        print(f"   Found {len(tasks)} tasks")
        
        if not tasks:
            print("   No tasks found, stopping")
            break
        
        # 2. Execute first task
        task = tasks[0]
        print(f"📝 Task: {task.description}")
        print(f"   Files: {', '.join(task.target_files)}")
        
        # 3. LLM improves code
        print("🤖 LLM improving code...")
        result = llm_improve_task(task)
        results.append(result)
        
        # 4. Report result
        if result.success:
            print(f"   ✅ Success! Changed {len(result.files_changed)} files")
            if result.commit_sha:
                print(f"   📦 Committed: {result.commit_sha[:8]}")
        else:
            print(f"   ❌ Failed: {result.error or 'Tests failed'}")
        
        # 5. Persist learnings
        persist_learnings(result)
        
        print()
    
    # Summary
    elapsed = time.time() - started
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    
    print("━━━ Summary ━━━")
    print(f"Iterations: {len(results)}")
    print(f"Success: {sum(1 for r in results if r.success)}")
    print(f"Failed: {sum(1 for r in results if not r.success)}")
    print(f"Files changed: {sum(len(r.files_changed) for r in results)}")
    print(f"Commits: {sum(1 for r in results if r.commit_sha)}")
    print(f"Duration: {minutes}m {seconds}s")
    
    # Send summary notification
    success = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    files = sum(len(r.files_changed) for r in results)
    commits = sum(1 for r in results if r.commit_sha)
    
    summary = f"🌙 *Nightwatch Complete*\n"
    summary += f"Duration: {minutes}m {seconds}s\n"
    summary += f"Success: {success} | Failed: {failed}\n"
    summary += f"Files changed: {files}\n"
    summary += f"Commits: {commits}\n"
    
    if commits > 0:
        summary += f"\n📦 Auto-committed {commits} improvements"
    
    send_telegram(summary)
    
    return results


def send_telegram(message: str) -> bool:
    """Send message to Telegram."""
    try:
        env_file = Path("/etc/jarvis-telegram.env")
        if not env_file.exists():
            return False
        env = {}
        for line in env_file.read_text().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

        token = env.get("JARVIS_TELEGRAM_TOKEN", "")
        chat_id = env.get("JARVIS_TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return False

        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def persist_learnings(result: IterationResult) -> None:
    """Persist learnings to progress log and AGENTS.md."""
    # Append to progress log
    PROGRESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_LOG, "a") as f:
        f.write(json.dumps({
            "timestamp": time.time(),
            "task_id": result.task_id,
            "success": result.success,
            "files_changed": result.files_changed,
            "tests_passed": result.tests_passed,
            "commit_sha": result.commit_sha,
            "learnings": result.learnings,
        }, ensure_ascii=False) + "\n")
    
    # Append to AGENTS.md if there are learnings
    if result.learnings and result.learnings != "LLM determined no changes were needed":
        with open(AGENTS_MD, "a") as f:
            f.write(f"\n\n## Nightwatch Learning — {time.strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"- Task: {result.task_id}\n")
            f.write(f"- Result: {'success' if result.success else 'failed'}\n")
            f.write(f"- Learnings: {result.learnings}\n")
            if result.files_changed:
                f.write(f"- Files: {', '.join(result.files_changed)}\n")
    
    # Send Telegram notification
    icon = "✅" if result.success else "❌"
    files = len(result.files_changed)
    msg = f"{icon} *Nightwatch Update*\n"
    msg += f"Task: {result.task_id[:20]}...\n"
    msg += f"Files changed: {files}\n"
    msg += f"Tests: {'passed' if result.tests_passed else 'failed'}\n"
    if result.commit_sha:
        msg += f"Commit: {result.commit_sha[:8]}\n"
    send_telegram(msg)


# ═══ CLI Entry Point ═══

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="LLM-powered nightwatch")
    parser.add_argument("--iterations", type=int, default=5, help="Max iterations")
    parser.add_argument("--minutes", type=int, default=60, help="Max minutes")
    parser.add_argument("--llm-url", type=str, default=LLAMA_CPP_URL, help="LLM endpoint URL")
    args = parser.parse_args()
    
    LLAMA_CPP_URL = args.llm_url
    
    results = run_llm_nightwatch(
        max_iterations=args.iterations,
        max_minutes=args.minutes,
    )
    
    # Exit with success if any iteration succeeded
    exit(0 if any(r.success for r in results) else 1)
