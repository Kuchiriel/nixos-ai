"""`jarvis doctor` — diagnóstico de saúde do sistema JARVIS.

Reporta, em JSON, a saúde de cada camada: llama.cpp (chat e embeddings),
Qdrant, estado do disco e gerações NixOS. Sem dependência de root — usa
apenas HTTP (health endpoints) e leituras locais. É o alicerce do self-heal:
tudo que o agente precisa saber para decidir o que consertar.

Componentes retornam status "ok" | "degraded" | "down", com detalhes.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

import requests

from jarvis.core.config import Config


@dataclass
class ComponentHealth:
    name: str
    status: str = "down"  # ok | degraded | down
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _http_ok(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return True, "ok"
        return False, f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)


def check_llm(cfg: Config) -> ComponentHealth:
    """llama.cpp chat — health + modelo carregado."""
    h = ComponentHealth("llama_cpp")
    base = cfg.llm_base_url.rstrip("/")
    ok, detail = _http_ok(f"{base.replace('/v1', '')}/health")
    h.status = "ok" if ok else "down"
    h.detail = detail
    if ok:
        try:
            resp = requests.get(f"{base}/models", timeout=3)
            data = resp.json()
            if data.get("data"):
                h.data["model"] = data["data"][0].get("id", "")
        except (requests.RequestException, ValueError):
            pass
    return h


def check_embeddings(cfg: Config) -> ComponentHealth:
    """llama.cpp embeddings (porta 8081)."""
    h = ComponentHealth("llama_cpp_embeddings")
    base = cfg.embed_base_url.rstrip("/")
    ok, detail = _http_ok(f"{base.replace('/v1', '')}/health")
    h.status = "ok" if ok else "down"
    h.detail = detail
    return h


def check_qdrant(cfg: Config) -> ComponentHealth:
    """Qdrant — health + coleções existentes."""
    h = ComponentHealth("qdrant")
    base = cfg.qdrant_url.rstrip("/")
    ok, detail = _http_ok(f"{base}/collections")
    h.status = "ok" if ok else "down"
    h.detail = detail
    if ok:
        try:
            resp = requests.get(f"{base}/collections", timeout=3)
            collections = [c["name"] for c in resp.json()["result"]["collections"]]
            h.data["collections"] = collections
            # `books` é do legado (audiobooks) e só existe quando indexado —
            # ausência não degrada o sistema (code + memories são essenciais).
            essential = [cfg.qdrant_collection_code, cfg.qdrant_collection_memories]
            missing = [name for name in essential if name not in collections]
            if missing:
                h.status = "degraded"
                h.detail = f"faltam coleções essenciais: {', '.join(missing)}"
        except (requests.RequestException, ValueError, KeyError) as exc:
            h.status = "degraded"
            h.detail = f"coleções ilegíveis: {exc}"
    return h


def check_disk() -> ComponentHealth:
    """Espaço em disco do sistema."""
    import shutil as _shutil

    h = ComponentHealth("disk")
    try:
        usage = shutil.disk_usage("/")
        total_gb = usage.total / (1024**3)
        free_gb = usage.free / (1024**3)
        pct = usage.used / usage.total * 100
        h.data = {
            "total_gb": round(total_gb, 1),
            "free_gb": round(free_gb, 1),
            "used_percent": round(pct, 1),
        }
        if pct >= 90:
            h.status = "degraded"
            # binário declarativo do store (nixos/modules/scripts.nix);
            # fallback para o script da raiz se o pacote não estiver ativo
            clean = _shutil.which("clean") or _shutil.which("jarvis-clean")
            h.detail = (f"disco {pct:.0f}% cheio — rodar {clean or './clean.sh'}")
        elif pct >= 80:
            h.status = "degraded"
            h.detail = f"disco {pct:.0f}% — planejar limpeza"
        else:
            h.status = "ok"
            h.detail = f"{free_gb:.1f} GB livres"
    except OSError as exc:
        h.detail = str(exc)
    return h


def _user_unit_active(unit: str) -> tuple[bool, str]:
    """Verifica se um serviço de usuário está ativo (systemctl --user)."""
    try:
        out = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=5, check=False,
        )
        state = out.stdout.strip()
        if state == "active":
            return True, "ativo"
        if state == "inactive":
            return False, "inativo (esperado?)"
        return state in ("failed", "activating"), state
    except (OSError, subprocess.SubprocessError):
        return False, "systemd user indisponível (SSH/sem sessão?)"


def _proc_running(name: str) -> bool:
    """Verifica se um processo está rodando (pgrep por nome)."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", name], capture_output=True, text=True, timeout=5,
            check=False,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_ui() -> ComponentHealth:
    """Elementos cosméticos da interface — waybar, hyprland, rofi, mpvpaper.

    Saúde da UI/UX: o sistema não "morre" se o waybar cair, mas o usuário
    perde o feedback do JARVIS (estados idle/listening/thinking...).
    Componentes agrupados; apenas degradam (nunca derrubam o overall).
    """
    h = ComponentHealth("ui")
    issues: list[str] = []

    # Hyprland (compositor) — o mais crítico dos cosméticos
    if not _proc_running("Hyprland"):
        issues.append("hyprland não está rodando (SSH?)")
    # Waybar — feedback visual do JARVIS (estados animados)
    if not _proc_running("waybar"):
        issues.append("waybar parado (feedback do JARVIS ausente)")
    # Notificações (swaync) — feedback de popups
    if not _proc_running("swaync"):
        issues.append("swaync (notificações) parado")
    # Tema rofi jarvis-cyan — porta do legado
    try:
        from pathlib import Path

        theme = Path.home() / ".local/share/rofi/themes/jarvis-cyan.rasi"
        if not theme.exists():
            issues.append("tema rofi jarvis-cyan ausente")
    except OSError:
        pass
    # mpvpaper — wallpaper animado (host; na VM é esperado ausente)
    mpvpaper_active, _ = _user_unit_active("mpvpaper.service")
    if not mpvpaper_active:
        # Na VM é esperado (ConditionVirtualization=!vm); no host é problema
        try:
            is_vm = subprocess.run(
                ["systemd-detect-virt", "-q"], capture_output=True, check=False,
            ).returncode == 0
        except OSError:
            is_vm = True
        if not is_vm:
            issues.append("mpvpaper inativo no host (wallpaper animado parado?)")

    if issues:
        h.status = "degraded"
        h.detail = "; ".join(issues)
        h.data["issues"] = issues
    else:
        h.status = "ok"
        h.detail = "waybar/hyprland/rofi/mpvpaper ok"
    return h


def check_nixos_generations() -> ComponentHealth:
    """Gerações NixOS instaladas (via boot.loader.nixos-version / generations)."""
    h = ComponentHealth("nixos")
    try:
        from pathlib import Path

        gen_dir = Path("/nix/var/nix/profiles/system")
        if gen_dir.exists():
            h.data["profile"] = str(gen_dir.resolve())
            h.status = "ok"
            h.detail = f"profile: {gen_dir.resolve()}"
        else:
            h.status = "degraded"
            h.detail = "profile system não encontrado (fora de NixOS?)"
    except OSError as exc:
        h.status = "degraded"
        h.detail = str(exc)
    return h


def run_doctor(cfg: Config | None = None) -> list[ComponentHealth]:
    cfg = cfg or Config()
    return [
        check_llm(cfg),
        check_embeddings(cfg),
        check_qdrant(cfg),
        check_disk(),
        check_nixos_generations(),
        check_ui(),
    ]


def doctor_report(cfg: Config | None = None) -> dict[str, Any]:
    """Relatório completo em dict (para JSON)."""
    checks = run_doctor(cfg)
    overall = "ok"
    for c in checks:
        if c.status == "down":
            overall = "down"
            break
        if c.status == "degraded" and overall == "ok":
            overall = "degraded"
    return {
        "overall": overall,
        "checks": [
            {"name": c.name, "status": c.status, "detail": c.detail, **({"data": c.data} if c.data else {})}
            for c in checks
        ],
    }
