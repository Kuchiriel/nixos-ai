"""`jarvis doctor` — diagnóstico de saúde do sistema JARVIS.

Reporta, em JSON, a saúde de cada camada: llama.cpp (chat e embeddings),
Qdrant, estado do disco e gerações NixOS. Sem dependência de root — usa
apenas HTTP (health endpoints) e leituras locais. É o alicerce do self-heal:
tudo que o agente precisa saber para decidir o que consertar.

Componentes retornam status "ok" | "degraded" | "down", com detalhes.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Any

import requests

from jarvis.core.config import Config
from jarvis.core.logging import get_logger


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
            clean = shutil.which("clean") or shutil.which("jarvis-clean")
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


def check_network() -> ComponentHealth:
    """Conectividade de rede local e internet."""
    h = ComponentHealth("network")
    issues: list[str] = []
    # Gateway local
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect(("1.1.1.1", 53))
            s.close()
        except (OSError, TimeoutError):
            issues.append("sem acesso a 1.1.1.1:53 (internet?)")
        finally:
            s.close()
    except OSError:
        issues.append("socket indisponível")
    # DNS
    try:
        socket.getaddrinfo("cache.nixos.org", 443, socket.AF_INET, socket.SOCK_STREAM)
    except (OSError, socket.gaierror):
        issues.append("DNS cache.nixos.org falhou")
    if issues:
        h.status = "degraded"
        h.detail = "; ".join(issues)
    else:
        h.status = "ok"
        h.detail = "rede local + internet OK"
    return h


def check_sockets(cfg: Config) -> ComponentHealth:
    """Verifica se as portas dos serviços estão aceitando conexões."""
    h = ComponentHealth("sockets")
    ports = {
        "llama_cpp": cfg.llm_base_url.replace("http://", "").split(":")[1].split("/")[0] if":" in cfg.llm_base_url else "8080",
        "embeddings": cfg.embed_base_url.replace("http://", "").split(":")[1].split("/")[0] if":" in cfg.embed_base_url else "8081",
        "qdrant": cfg.qdrant_url.replace("http://", "").split(":")[1].split("/")[0] if":" in cfg.qdrant_url else "6333",
    }
    results = {}
    for name, port in ports.items():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            result = s.connect_ex(("127.0.0.1", int(port)))
            s.close()
            results[name] = result == 0
        except (OSError, ValueError):
            results[name] = False
    closed = [name for name, ok in results.items() if not ok]
    h.data = results
    if closed:
        h.status = "degraded"
        h.detail = f"portas fechadas: {', '.join(closed)}"
    else:
        h.status = "ok"
        h.detail = ", ".join(f"{k}:{v}" for k, v in results.items())
    return h


def check_btrfs() -> ComponentHealth:
    """Verificação de saúde do filesystem Btrfs (se aplicável)."""
    h = ComponentHealth("btrfs")
    try:
        proc = subprocess.run(
            ["btrfs", "filesystem", "show", "/"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if proc.returncode != 0:
            # Não é Btrfs — ok, outros filesystems são válidos
            h.status = "ok"
            h.detail = "não é Btrfs (ok)"
            return h
        # Verifica erros
        proc2 = subprocess.run(
            ["btrfs", "device", "stats", "/"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if proc2.returncode == 0:
            # Conta erros
            errors = 0
            for line in proc2.stdout.strip().splitlines():
                if ": 0" not in line and line.strip():
                    parts = line.split(":")
                    if len(parts) >= 2:
                        try:
                            errors += int(parts[1].strip())
                        except ValueError:
                            pass
            if errors > 0:
                h.status = "degraded"
                h.detail = f"Btrfs: {errors} erros de device"
            else:
                h.status = "ok"
                h.detail = "Btrfs: sem erros"
        else:
            h.status = "ok"
            h.detail = "Btrfs: stats indisponíveis (ok)"
    except (OSError, subprocess.SubprocessError):
        h.status = "ok"
        h.detail = "btrfs não disponível"
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
        check_network(),
        check_sockets(cfg),
        check_btrfs(),
    ]


def doctor_report(cfg: Config | None = None) -> dict[str, Any]:
    """Relatório completo em dict (para JSON)."""
    log = get_logger("doctor")
    checks = run_doctor(cfg)
    overall = "ok"
    for c in checks:
        if c.status == "down":
            overall = "down"
            break
        if c.status == "degraded" and overall == "ok":
            overall = "degraded"
    report = {
        "overall": overall,
        "checks": [
            {"name": c.name, "status": c.status, "detail": c.detail, **({"data": c.data} if c.data else {})}
            for c in checks
        ],
    }
    down_count = sum(1 for c in checks if c.status == "down")
    degraded_count = sum(1 for c in checks if c.status == "degraded")
    log.info("doctor_report", detail={
        "overall": overall, "down": down_count, "degraded": degraded_count,
        "total": len(checks),
    })
    return report
