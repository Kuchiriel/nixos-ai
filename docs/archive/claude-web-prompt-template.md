# Prompt for Claude Web

Copy and paste this into Claude Web (claude.ai). It will generate a detailed implementation prompt for Mimo (the local AI on NixOS).

---

You are helping build a self-sustaining local AI system on NixOS. The system has:

**Hardware**: RTX 4050 6GB, i7-13620H, 32GB RAM, NVMe Gen4
**OS**: NixOS (declarative, reproducible, btrfs with snapshots)
**LLM**: Qwen3.6-35B-A3B Q4_K_M via llama.cpp (~28-32 tok/s)
**Agent**: JARVIS — Python harness with 20 MCP tools, REPL, Telegram bot
**Version control**: Git (nixos-ai repo), btrfs snapshots, NixOS rebuilds are reversible
**Safety**: nightwatch loop with grounded reflection (test→verify→commit/revert)

**Current state**:
- nightwatch.py exists but only has 6 basic categories (test, docs, security, dedup, status, nix-lint)
- No Obsidian/HackMD integration for knowledge persistence
- No automatic error discovery loop
- No self-improvement feedback loop (find error → fix → test → commit → learn)
- The local AI (Qwen) has vision, tools, memory, RAG — but they're not connected in an autonomous loop

**What I need you to generate**:

A detailed implementation prompt for the local AI agent (Mimo 2.5 running in a CLI called Freebuff) that will:

1. **Make the overnight mode work**: The agent should be able to run `jarvis nightwatch --tasks 20 --report-telegram` and have it actually find real issues, fix them safely, test, commit, and report progress.

2. **Add more safe task categories** that can run overnight without human supervision:
   - Code quality (dead code, unused imports, type hints)
   - Documentation consistency (code vs docs mismatch)
   - Test coverage gaps
   - Security scanning (hardcoded secrets, unsafe patterns)
   - Performance profiling opportunities
   - NixOS configuration drift
   - Git hygiene (stale branches, uncommitted work)

3. **Obsidian + HackMD integration**: Create MCP tools that:
   - Sync project docs to Obsidian vault (local knowledge base)
   - Push important findings to HackMD (collaborative, shareable)
   - Read from Obsidian/HackMD to inform the agent's decisions
   - Use HackMD API (https://api.hackmd.io/v1) for CRUD operations

4. **Self-improvement loop**: After each nightwatch cycle:
   - Log what was found and fixed
   - Update the agent's memory with lessons learned
   - Identify patterns in errors (recurring issues)
   - Suggest architectural improvements based on accumulated data

5. **Safety guarantees**: The prompt must ensure:
   - All file modifications go through git (revertible)
   - btrfs snapshots before major changes
   - No modifications to llama.cpp server (the AI's own brain)
   - No modifications to system services during overnight
   - All changes tested before commit
   - Telegram notifications for critical findings
   - Automatic revert if tests fail

**Constraints**:
- The local model has 32K context (system prompt takes ~15-20K)
- Output must be efficient (no verbose explanations in the loop)
- Everything must be NixOS-declarative (no imperative hacks)
- The system should work even if the local model is slow (~28 tok/s)

**Generate a prompt** that I can paste into the local AI agent (Mimo) to implement all of this. The prompt should be:
- Specific enough to implement directly
- Include file paths and function signatures
- Include the nightwatch categories with exact commands
- Include the HackMD/Obsidian integration code structure
- Include safety checks at each step
- Be in Portuguese (PT-BR) since the agent works in PT-BR

Do NOT just describe what to do. Generate the actual implementation prompt with code snippets, file paths, and step-by-step instructions.
