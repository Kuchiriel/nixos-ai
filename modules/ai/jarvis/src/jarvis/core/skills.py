"""Skills — capability packages on-demand (standard Agent Skills).

Filosofia Pi roubada sem trocar a nossa: progressive disclosure — só
`name + description` entram no system prompt; o SKILL.md completo carrega
via tool `load_skill` quando a tarefa casa. Skills NÃO executam nada por
si (são prompt); scripts referenciados rodam via execute_shell (com
approval/audit normal). Mesmo trust que docs do repo — revisar antes de
instalar skill de terceiro (aviso do Pi, adotado).

Fontes (ordem): JARVIS_SKILLS_DIR > ./skills (repo) > ~/.jarvis/skills >
~/.claude/skills + ~/.codex/skills (reuso Pi/Claude/Codex, como o Pi faz).

Formato: diretório com SKILL.md + frontmatter `name:`/`description:`.
Leniente como o Pi (nome pode diferir do diretório).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_SKILL_CHARS = 12000
MAX_DESCRIPTIONS = 40


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str = ""


def _frontmatter(text: str) -> dict[str, str]:
    """Parse mínimo do frontmatter --- name/description (sem dep yaml)."""
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    if end < 0:
        return out
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        if k in ("name", "description"):
            out[k] = v.strip().strip("\"'")
    return out


def skill_dirs() -> list[Path]:
    """Diretórios de skills existentes (nesta ordem de prioridade)."""
    dirs: list[Path] = []
    env = os.environ.get("JARVIS_SKILLS_DIR")
    if env:
        dirs.append(Path(env).expanduser())
    dirs.append(Path("skills"))
    home = Path.home()
    dirs.extend([
        home / ".jarvis" / "skills",
        home / ".claude" / "skills",
        home / ".codex" / "skills",
    ])
    return [d for d in dirs if d.is_dir()]


def _iter_skill_files(base: Path) -> list[Path]:
    """SKILL.md em filhos imediatos (standard) + .md com frontmatter na raiz (leniente, Pi)."""
    found: list[Path] = []
    try:
        for child in sorted(base.iterdir()):
            if child.is_dir():
                cand = child / "SKILL.md"
                if cand.is_file():
                    found.append(cand)
            elif child.suffix == ".md" and child.is_file():
                found.append(child)
        # Recursão 1 nível p/ skills/ aninhados (ex: plugin com skills/*/)
        for child in sorted(base.iterdir()):
            if child.is_dir():
                for grand in sorted(child.iterdir()):
                    if grand.is_dir():
                        cand = grand / "SKILL.md"
                        if cand.is_file() and cand not in found:
                            found.append(cand)
    except OSError:
        pass
    return found


def list_skills() -> list[Skill]:
    """Descobre skills (dedupe por nome — primeira fonte vence)."""
    skills: list[Skill] = []
    seen: set[str] = set()
    for base in skill_dirs():
        for f in _iter_skill_files(base):
            try:
                fm = _frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            name = fm.get("name")
            if not name:
                # SKILL.md → nome do diretório; .md solto → stem do arquivo.
                name = f.parent.name if f.name == "SKILL.md" else f.stem
            desc = fm.get("description", "")
            if not name or name in seen:
                continue
            seen.add(name)
            skills.append(Skill(name=name, description=desc, path=f,
                                source=str(base)))
    return skills


def descriptions_block() -> str:
    """Bloco compacto p/ system prompt (só nomes+descrições)."""
    skills = list_skills()[:MAX_DESCRIPTIONS]
    if not skills:
        return ""
    lines = ["<skills>"]
    for s in skills:
        lines.append(f'<skill name="{s.name}">{s.description}</skill>')
    lines.append("</skills>")
    lines.append("Para usar uma skill, chame load_skill(name) e siga o SKILL.md.")
    return "\n".join(lines)


def load_skill(name: str) -> dict:
    """Carrega o SKILL.md completo (cap 12k chars)."""
    for s in list_skills():
        if s.name == name:
            try:
                content = s.path.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                return {"ok": False, "error": f"skill {name!r} ilegível: {e}"}
            if len(content) > MAX_SKILL_CHARS:
                content = content[:MAX_SKILL_CHARS] + "\n…[truncado]"
            return {"ok": True, "name": name, "source": s.source,
                    "content": content}
    known = [s.name for s in list_skills()]
    return {"ok": False, "error": f"skill desconhecida: {name!r}",
            "known": known}
