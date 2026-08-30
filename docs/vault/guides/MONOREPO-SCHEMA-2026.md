# Monorepo Schema & Refactoring Prompts — State of the Art 2026

> Research from: monorepo.tools, GitClear, Augment Code, Prompt Architects
> Date: 2026-08-30

---

## Monorepo Schema (Best Practices)

### Core Principles
1. **Single source of truth** — common code lives ONE place
2. **Atomic commits** — changes across projects land in same PR
3. **Enforceable conventions** — rules apply everywhere automatically
4. **No polyrepo tax** — sharing code is as simple as creating a folder
5. **AI-compatible** — agent sees beyond repo boundaries

### Directory Structure
```
project/
├── packages/           # Shared libraries (single source of truth)
│   ├── core/           # Core business logic
│   ├── utils/          # Shared utilities
│   └── ui/             # Shared UI components
├── apps/               # Applications
│   ├── web/
│   ├── api/
│   └── cli/
├── tools/              # Build tools, scripts
├── docs/               # Documentation
├── AGENTS.md           # AI agent instructions (Linux Foundation spec)
├── README.md           # Human documentation
└── flake.nix           # Nix flake (our case)
```

### Naming Conventions
- **Directories**: lowercase, hyphens for multi-word (`my-package`)
- **Files**: lowercase, underscores for Python (`my_module.py`)
- **Packages**: scoped (`@org/package-name`)
- **Branches**: `feature/`, `fix/`, `chore/`

### Dependency Rules
- Shared code → `packages/` (imported by all)
- App-specific code → stays in app directory
- Never duplicate across apps
- Dependencies flow: apps → packages → core

---

## Refactoring Prompts (State of the Art)

### The 5-Component System
Every prompt needs: **Role, Context, Task, Constraints, Output Format**

### Prompt 1: Find Duplications
```
Role: Senior code quality engineer specializing in deduplication.

Context:
- Language: [Python/Nix/JS]
- Framework: [JARVIS/NixOS]
- Codebase size: [X files, Y lines]

Task: Find duplicated code across the codebase.

Rules:
1. Search for functions/classes with similar names AND similar logic
2. Search for copy-pasted blocks (>5 lines identical)
3. Search for modules doing similar things (idle, doctor, health)
4. For each duplication found, provide:
   - File paths and line numbers
   - What it does
   - What's different between copies
   - Which one to keep (or if new abstraction needed)

Output: Table with columns: Duplication | Files | Lines | Recommendation
```

### Prompt 2: Consolidation Plan
```
Role: Software architect planning module consolidation.

Context:
- Current modules: [list all modules]
- Dependencies: [what imports what]
- Shared state: [what state do they share]

Task: Create a consolidation plan.

Rules:
1. Group modules by responsibility
2. Identify the "single source of truth" for each responsibility
3. Plan migration path (what to merge into what)
4. Ensure no functionality is lost
5. Keep backward compatibility during migration

Output: Consolidation map with BEFORE → AFTER for each module
```

### Prompt 3: Refactoring Checklist
```
Role: Code reviewer checking refactoring safety.

Context:
- Code to refactor: [paste code]
- Tests: [what tests exist]
- Dependencies: [what depends on this code]

Task: Create a safe refactoring checklist.

Rules:
1. What must be true BEFORE refactoring (tests pass, backups exist)
2. What to change (step by step)
3. What to verify AFTER each step
4. What could go wrong (regression risks)
5. Rollback plan

Output: Numbered checklist with verification steps
```

### Prompt 4: Dependency Audit
```
Role: Dependency analyst mapping module relationships.

Context:
- Modules: [list all .py files]
- Imports: [what each imports]

Task: Map all dependencies and find circular imports.

Rules:
1. For each module, list what it imports
2. For each module, list what imports it
3. Find circular dependencies
4. Find modules that should be independent but aren't
5. Suggest dependency direction corrections

Output: Dependency graph (text) + issues found
```

---

## AI Code Quality Data (GitClear 2026)

### Risk Signals (Getting Worse)
| Signal | 2023 | 2026 | Change |
|--------|------|------|--------|
| Block duplication | 40.3/M lines | 73.0/M lines | **+81%** |
| Copy/paste | 9.4% | 15.7% | **+67%** |
| Error-masking | baseline | +47% | **+47%** |
| Code churn | baseline | +15% | **+15%** |

### Reuse Signals (Getting Worse)
| Signal | 2023 | 2026 | Change |
|--------|------|------|--------|
| Refactoring moves | 21% | 3.8% | **-82%** |
| Cross-file calls | 343/1K lines | 223/1K lines | **-35%** |
| Legacy maintenance | 1.7% | 0.46% | **-74%** |

### Key Insight
> "The biggest risk isn't that AI writes code your team can't maintain. It's that it writes that code faster than ever, and the debt it accrues concentrates among developers who haven't recognized the failure modes."

---

## Duplicate Detection Tools

### jscpd (JavaScript Copy/Paste Detector)
```bash
# Find all duplications
npx jscpd --min-tokens 50 --threshold 0 --reporters console .

# Auto-fix
npx jscpd --min-tokens 50 --threshold 0 --fix .
```

### Python-specific
```bash
# Find similar functions
pylint --disable=all --enable=similarities .

# Find duplicate code
python -m duplication --min-lines 5 .
```

### Manual Detection
```bash
# Find files with similar names
find . -name "*.py" | sort | uniq -d

# Find similar function signatures
grep -rn "def " --include="*.py" | awk -F: '{print $3}' | sort | uniq -d
```

---

## Application to Our Project

### Current State (Problems)
1. **idle.py, doctor.py, proactive.py, health_monitor.py, heal.py** — 5 modules doing similar things
2. **context_budget.py** — was duplicated (consolidated, but others remain)
3. **security.py** — conflicted with existing module
4. **watchdog.py** — new module that consolidates some of the above

### Consolidation Plan
```
BEFORE:                          AFTER:
├── idle.py                      ├── watchdog.py (consolidates all)
├── doctor.py                    │   ├── check_gpu()
├── proactive.py       ──►       │   ├── check_ram()
├── health_monitor.py            │   ├── check_services()
├── heal.py                      │   ├── auto_heal()
└── watchdog.py (new)            │   └── speak()
```

### Rules for Future
1. **NEVER create a new module** without checking if existing modules can be extended
2. **ALWAYS use JARVIS tools** (RAG, recall, lessons) before writing code
3. **Consolidate first**, create new only when consolidation is impossible
4. **One module per responsibility** — if two modules do the same thing, merge them
5. **Test consolidation** — ensure no functionality is lost
