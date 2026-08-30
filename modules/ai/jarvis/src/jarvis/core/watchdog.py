"""Watchdog — unified JARVIS daemon that monitors, warns, and heals.

MCU JARVIS: "Sir, I'm detecting a problem with..."
Our Watchdog: monitors everything, speaks via TTS, shows on waybar, heals.

This REPLACES: idle.py, doctor.py, proactive.py, health_monitor.py
keeps: heal.py (audit trail), nightwatch (autonomous tasks)

Architecture:
    Watchdog runs as systemd service
    → checks GPU, RAM, disk, services, thermal, VRAM
    → if problem found: speak via TTS + waybar update + telegram
    → if service down: auto-heal (with cooldown)
    → logs everything to state dir
"""

from __future__ import annotations

import json
import subprocess
import time
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.core.logging import get_logger

logger = get_logger(__name__)

# ═══ State ═══
STATE_DIR = Path.home() / ".local/state/jarvis/watchdog"
STATE_DIR.mkdir(parents=True, exist_ok=True)
ALERT_LOG = STATE_DIR / "alerts.jsonl"
HEAL_LOG = STATE_DIR / "heal-audit.jsonl"

# ═══ Thresholds ═══
THRESHOLDS = {
    "gpu_temp_warn": 75,
    "gpu_temp_critical": 85,
    "gpu_vram_warn": 0.85,
    "ram_warn": 0.80,
    "ram_critical": 0.90,
    "disk_warn": 0.85,
    "thermal_throttle_mhz": 500,  # drop from max
}

# ═══ Cooldowns (prevent spam) ═══
COOLDOWNS = {
    "gpu_temp": 300,      # 5 min between GPU temp warnings
    "gpu_vram": 300,
    "ram": 600,           # 10 min between RAM warnings
    "disk": 3600,         # 1 hour between disk warnings
    "service_restart": 300,  # 5 min between restart attempts
    "tts": 30,            # 30 sec between TTS messages (avoid talking over each other)
}

_last_alert: dict[str, float] = {}


def _can_alert(key: str) -> bool:
    """Check if enough time has passed since last alert of this type."""
    now = time.time()
    last = _last_alert.get(key, 0)
    cooldown = COOLDOWNS.get(key, 60)
    if now - last >= cooldown:
        _last_alert[key] = now
        return True
    return False


# ═══ TTS ═══

def speak(message: str, priority: str = "normal") -> bool:
    """Speak a message via TTS. Returns True if spoken.
    
    Priority:
    - critical: always speaks (bypass cooldown)
    - normal: respects cooldown
    - low: only speaks if nothing else recently
    """
    if priority != "critical" and not _can_alert("tts"):
        return False

    try:
        # Direct TTS call — no subprocess (avoids PATH issues in systemd)
        from jarvis.core.voice import speak as tts_speak
        tts_speak(message, play=True)
        logger.info(f"TTS: {message}")
        return True
    except Exception as e:
        logger.info(f"TTS failed: {e}")
        return False


# ═══ Waybar Update ═══

def update_waybar(status: str, icon: str = "jarvis") -> None:
    """Update waybar status via feedback.py."""
    try:
        from jarvis.core.feedback import waybar_format
        data = waybar_format()
        data["text"] = f"{icon} {status}"
        data["tooltip"] = f"JARVIS: {status}"
        
        # Write to waybar status file
        status_file = Path("/tmp/jarvis-status.json")
        status_file.write_text(json.dumps(data))
    except Exception as e:
        logger.debug(f"Waybar update failed: {e}")


# ═══ Telegram ═══

def notify_telegram(message: str, priority: str = "normal") -> bool:
    """Send notification to Telegram. Only for critical/warning."""
    if priority not in ("critical", "warning"):
        return False
    
    try:
        from jarvis.providers.telegram import send_message
        return send_message(message)
    except Exception:
        return False


# ═══ Logging ═══

def _log_alert(alert: dict) -> None:
    """Log alert to JSONL file."""
    alert["timestamp"] = time.time()
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(alert) + "\n")


def _log_heal(action: dict) -> None:
    """Log heal action to JSONL file."""
    action["timestamp"] = time.time()
    with open(HEAL_LOG, "a") as f:
        f.write(json.dumps(action) + "\n")


# ═══ Checks ═══

def check_gpu() -> list[dict]:
    """Check GPU and return alerts."""
    alerts = []
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,memory.used,memory.total,clocks.current.graphics,clocks.max.graphics",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return alerts

        parts = result.stdout.strip().split(", ")
        if len(parts) < 6:
            return alerts

        temp = float(parts[0])
        vram_used = float(parts[2])
        vram_total = float(parts[3])
        clock_current = float(parts[4])
        clock_max = float(parts[5])

        vram_pct = vram_used / vram_total if vram_total > 0 else 0

        # Temperature
        if temp >= THRESHOLDS["gpu_temp_critical"]:
            alerts.append({
                "severity": "critical",
                "component": "gpu",
                "type": "gpu_temp",
                "message": f"GPU temperature CRITICAL: {temp:.0f}°C",
                "speak": f"Warning. GPU temperature is critical at {temp:.0f} degrees. Consider reducing workload.",
            })
        elif temp >= THRESHOLDS["gpu_temp_warn"]:
            alerts.append({
                "severity": "warning",
                "component": "gpu",
                "type": "gpu_temp",
                "message": f"GPU temperature elevated: {temp:.0f}°C",
                "speak": f"GPU temperature is {temp:.0f} degrees. Monitoring closely.",
            })

        # VRAM
        if vram_pct >= THRESHOLDS["gpu_vram_warn"]:
            alerts.append({
                "severity": "warning",
                "component": "gpu",
                "type": "gpu_vram",
                "message": f"VRAM usage high: {vram_used:.0f}MB/{vram_total:.0f}MB ({vram_pct:.0%})",
                "speak": f"VRAM usage is at {vram_pct:.0%}. Consider reducing context.",
            })

        # Throttling
        if clock_max > 0 and clock_current < (clock_max - THRESHOLDS["thermal_throttle_mhz"]):
            alerts.append({
                "severity": "warning",
                "component": "thermal",
                "type": "gpu_throttle",
                "message": f"GPU throttled: {clock_current:.0f}MHz vs {clock_max:.0f}MHz max",
                "speak": f"GPU is throttled to {clock_current:.0f} megahertz due to thermal pressure.",
            })

    except Exception:
        pass

    return alerts


def check_ram() -> list[dict]:
    """Check RAM usage."""
    alerts = []
    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.readlines()

        mem_total = 0
        mem_available = 0
        for line in lines:
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mem_available = int(line.split()[1])

        if mem_total > 0:
            mem_used_pct = 1 - (mem_available / mem_total)

            if mem_used_pct >= THRESHOLDS["ram_critical"]:
                alerts.append({
                    "severity": "critical",
                    "component": "ram",
                    "type": "ram",
                    "message": f"RAM usage CRITICAL: {mem_used_pct:.0%}",
                    "speak": f"Warning. RAM usage is critical at {mem_used_pct:.0%}. System may become unresponsive.",
                })
            elif mem_used_pct >= THRESHOLDS["ram_warn"]:
                alerts.append({
                    "severity": "warning",
                    "component": "ram",
                    "type": "ram",
                    "message": f"RAM usage elevated: {mem_used_pct:.0%}",
                })

    except Exception:
        pass

    return alerts


def check_disk() -> list[dict]:
    """Check disk usage."""
    alerts = []
    try:
        result = subprocess.run(
            ["df", "/home", "--output=pcent"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                used_pct = int(lines[1].strip().rstrip("%")) / 100
                if used_pct >= THRESHOLDS["disk_warn"]:
                    alerts.append({
                        "severity": "warning",
                        "component": "disk",
                        "type": "disk",
                        "message": f"Disk usage high: {used_pct:.0%}",
                        "speak": f"Disk usage is at {used_pct:.0%}. Consider cleaning up.",
                    })
    except Exception:
        pass

    return alerts


def check_services() -> list[dict]:
    """Check critical services."""
    alerts = []
    services = {
        "llama-cpp-server": "LLM server",
        "qdrant": "Vector database",
        "llama-cpp-embeddings": "Embeddings server",
    }

    for service, name in services.items():
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() != "active":
                alerts.append({
                    "severity": "critical",
                    "component": "service",
                    "type": f"service_{service}",
                    "message": f"{name} ({service}) is {result.stdout.strip()}",
                    "speak": f"Warning. {name} is down. Attempting auto-repair.",
                    "service": service,
                    "auto_heal": True,
                })
        except Exception:
            pass

    return alerts


# ═══ Auto-Heal ═══

def auto_heal(service: str) -> bool:
    """Try to restart a failed service."""
    if not _can_alert(f"heal_{service}"):
        logger.info(f"Heal cooldown active for {service}")
        return False

    try:
        result = subprocess.run(
            ["systemctl", "restart", service],
            capture_output=True, text=True, timeout=30
        )
        
        _log_heal({
            "action": "restart",
            "service": service,
            "success": result.returncode == 0,
            "output": result.stdout + result.stderr,
        })

        if result.returncode == 0:
            speak(f"{service} has been restarted successfully.", priority="normal")
            return True
        else:
            speak(f"Failed to restart {service}. Manual intervention may be needed.", priority="critical")
            return False

    except Exception as e:
        logger.error(f"Heal failed for {service}: {e}")
        return False


# �══ Main Loop ═══

def watchdog_cycle() -> dict[str, Any]:
    """Run one watchdog cycle. Returns summary of actions taken."""
    cycle_start = time.time()
    all_alerts = []
    actions = []

    # Run all checks
    all_alerts.extend(check_gpu())
    all_alerts.extend(check_ram())
    all_alerts.extend(check_disk())
    all_alerts.extend(check_services())

    # Process alerts
    for alert in all_alerts:
        _log_alert(alert)

        # Speak if message exists
        if "speak" in alert:
            spoke = speak(alert["speak"], priority=alert.get("severity", "normal"))
            alert["spoken"] = spoke

        # Auto-heal if needed
        if alert.get("auto_heal") and "service" in alert:
            healed = auto_heal(alert["service"])
            actions.append({"service": alert["service"], "healed": healed})

        # Telegram for critical
        if alert.get("severity") == "critical":
            notify_telegram(alert["message"], priority="critical")

    # Update waybar
    critical = [a for a in all_alerts if a.get("severity") == "critical"]
    warnings = [a for a in all_alerts if a.get("severity") == "warning"]

    if critical:
        update_waybar("⚠️ CRITICAL", "🔴")
    elif warnings:
        update_waybar(f"⚡ {len(warnings)} warnings", "🟡")
    else:
        update_waybar("✅ Online", "🟢")

    return {
        "timestamp": cycle_start,
        "duration": time.time() - cycle_start,
        "alerts": len(all_alerts),
        "critical": len(critical),
        "warnings": len(warnings),
        "actions": actions,
    }


def run_watchdog_loop(interval: int = 60, max_cycles: int = 0) -> None:
    """Run watchdog continuously.
    
    Args:
        interval: seconds between cycles
        max_cycles: 0 = infinite
    """
    cycle = 0
    logger.info(f"Watchdog started (interval={interval}s)")

    while max_cycles == 0 or cycle < max_cycles:
        try:
            result = watchdog_cycle()
            if result["alerts"] > 0:
                logger.info(f"Cycle {cycle}: {result['alerts']} alerts, {result['actions']} actions")
            cycle += 1
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Watchdog stopped by user")
            break
        except Exception as e:
            logger.error(f"Watchdog cycle error: {e}")
            time.sleep(interval)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        result = watchdog_cycle()
        print(json.dumps(result, indent=2))
    else:
        run_watchdog_loop()
