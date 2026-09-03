"""
Context Assembly Pipeline — just-in-time context for each prompt.

Based on Sourcegraph's four pillars (Instructions, Retrieval, Memory, Tools)
and OpenDev's adaptive context compaction.

The pipeline assembles the minimal sufficient context for each task,
preventing context bloat while ensuring the agent has what it needs.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ContextLayer:
    """A layer of context to include."""
    name: str
    content: str
    priority: int  # lower = more important (loaded first)
    token_estimate: int = 0
    source: str = ""  # where this came from


@dataclass
class ContextBudget:
    """Token budget management."""
    max_tokens: int = 32000
    reserved_for_response: int = 4096
    system_prompt_tokens: int = 2000
    tool_tokens: int = 3000

    @property
    def available_for_context(self) -> int:
        return self.max_tokens - self.reserved_for_response - self.system_prompt_tokens - self.tool_tokens


class ContextPipeline:
    """Assembles context for each prompt/query.

    Three-layer architecture:
    1. HANDOFF.md index (always loaded, ~100 lines)
    2. RAG search + Memory recall (just-in-time)
    3. read_files() for specific modules (on demand)
    """

    def __init__(self, project_root: str = None):
        if project_root is None:
            # Resolve from environment or workspace discovery — never hardcode.
            project_root = os.environ.get(
                "JARVIS_PROJECT_ROOT",
                os.environ.get("JARVIS_WORKSPACE_ROOT", "") or "",
            )
            if not project_root:
                # Last resort: discover from cwd (walks up looking for .git)
                from pathlib import Path as _P
                cur = _P.cwd()
                for _ in range(10):
                    if (cur / ".git").exists() or (cur / "flake.nix").exists():
                        project_root = str(cur)
                        break
                    if cur.parent == cur:
                        break
                    cur = cur.parent
            if not project_root:
                project_root = os.path.expanduser("~/projects")
        self.project_root = Path(project_root)
        self.handoff_path = self.project_root / "HANDOFF.md"
        self.buffy_path = self.project_root / "BUFFY.md"
        self.budget = ContextBudget()

        # Import here to avoid circular imports
        self._rag = None
        self._memory = None

    def _get_rag(self):
        """Lazy-load RAG module."""
        if self._rag is None:
            try:
                from .rag import RAGEngine
                self._rag = RAGEngine()
            except Exception:
                self._rag = False  # Mark as unavailable
        return self._rag if self._rag is not False else None

    def _get_memory(self):
        """Lazy-load memory module."""
        if self._memory is None:
            try:
                from .memory import MemoryEngine
                self._memory = MemoryEngine()
            except Exception:
                self._memory = False
        return self._memory if self._memory is not False else None

    def assemble(
        self,
        query: str,
        project_id: str = None,
        include_tools: bool = False,
        max_tokens: int = None,
    ) -> str:
        """Assemble context for a query.

        This is the main entry point. It builds the minimal context
        needed to answer the query effectively.
        """
        if max_tokens:
            self.budget.max_tokens = max_tokens

        layers = []
        remaining_budget = self.budget.available_for_context

        # Layer 1: HANDOFF index (always)
        handoff = self._load_handoff()
        if handoff:
            est = len(handoff) // 4  # rough token estimate
            if est < remaining_budget:
                layers.append(ContextLayer(
                    name="handoff",
                    content=handoff,
                    priority=0,
                    token_estimate=est,
                    source="HANDOFF.md",
                ))
                remaining_budget -= est

        # Layer 2: Project-specific context
        if project_id:
            project_ctx = self._load_project_context(project_id)
            if project_ctx:
                est = len(project_ctx) // 4
                if est < remaining_budget:
                    layers.append(ContextLayer(
                        name="project",
                        content=project_ctx,
                        priority=1,
                        token_estimate=est,
                        source=f"project:{project_id}",
                    ))
                    remaining_budget -= est

        # Layer 3: RAG search results
        rag = self._get_rag()
        if rag:
            try:
                results = rag.search(query, limit=5)
                if results:
                    rag_text = "\n".join(
                        f"[{r.get('score', 0):.2f}] {r.get('path', '?')}: "
                        f"{r.get('text', '')[:200]}"
                        for r in results
                    )
                    est = len(rag_text) // 4
                    if est < remaining_budget:
                        layers.append(ContextLayer(
                            name="rag",
                            content=rag_text,
                            priority=2,
                            token_estimate=est,
                            source="rag-search",
                        ))
                        remaining_budget -= est
            except Exception:
                pass

        # Layer 4: Memory recall
        memory = self._get_memory()
        if memory:
            try:
                memories = memory.recall(query, limit=5)
                if memories:
                    mem_text = "\n".join(
                        f"[{m.get('type', '?')}] {m.get('content', '')}"
                        for m in memories
                    )
                    est = len(mem_text) // 4
                    if est < remaining_budget:
                        layers.append(ContextLayer(
                            name="memory",
                            content=mem_text,
                            priority=3,
                            token_estimate=est,
                            source="memory-recall",
                        ))
                        remaining_budget -= est
            except Exception:
                pass

        # Layer 5: Lessons from past errors
        if memory:
            try:
                lessons = memory.lessons(query, limit=3)
                if lessons:
                    lesson_text = "\n".join(
                        f"[lesson] {l.get('content', '')}"
                        for l in lessons
                    )
                    est = len(lesson_text) // 4
                    if est < remaining_budget:
                        layers.append(ContextLayer(
                            name="lessons",
                            content=lesson_text,
                            priority=4,
                            token_estimate=est,
                            source="lessons",
                        ))
                        remaining_budget -= est
            except Exception:
                pass

        # Assemble in priority order
        layers.sort(key=lambda l: l.priority)
        return self._format_context(layers)

    def _load_handoff(self) -> str:
        """Load the lightweight HANDOFF index."""
        if self.handoff_path.exists():
            try:
                return self.handoff_path.read_text(errors="ignore")
            except Exception:
                return ""
        return ""

    def _load_project_context(self, project_id: str) -> str:
        """Load project-specific context (AGENTS.md, manifest)."""
        project_dir = self.project_root.parent / project_id
        if not project_dir.exists():
            project_dir = self.project_root / project_id

        parts = []

        # AGENTS.md
        agents_md = project_dir / "AGENTS.md"
        if agents_md.exists():
            try:
                parts.append(f"# {project_id} AGENTS.md\n{agents_md.read_text(errors='ignore')[:2000]}")
            except Exception:
                pass

        # README.md (first 50 lines)
        readme = project_dir / "README.md"
        if readme.exists():
            try:
                lines = readme.read_text(errors="ignore").splitlines()[:50]
                parts.append(f"# {project_id} README\n" + "\n".join(lines))
            except Exception:
                pass

        return "\n\n".join(parts) if parts else ""

    def _format_context(self, layers: list[ContextLayer]) -> str:
        """Format assembled context into a single string."""
        if not layers:
            return ""

        parts = []
        for layer in layers:
            parts.append(f"=== {layer.name.upper()} ({layer.source}) ===\n{layer.content}")

        return "\n\n".join(parts)

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate (English ~4 chars per token)."""
        return len(text) // 4

    def compact(self, text: str, target_tokens: int) -> str:
        """Compact text to fit within token budget.

        Strategy: keep the beginning and end, compress the middle.
        """
        current_tokens = self.estimate_tokens(text)
        if current_tokens <= target_tokens:
            return text

        # Keep first 25% and last 25%, summarize middle
        lines = text.splitlines()
        keep_lines = max(target_tokens * 4 // 4 // 2, 10)  # rough estimate

        if len(lines) <= keep_lines * 2:
            return text

        beginning = "\n".join(lines[:keep_lines])
        middle_summary = f"\n... [{len(lines) - keep_lines * 2} lines omitted] ...\n"
        end = "\n".join(lines[-keep_lines:])

        return beginning + middle_summary + end
