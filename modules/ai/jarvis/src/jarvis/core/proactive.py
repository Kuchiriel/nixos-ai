"""Proactive Diagnostics — JARVIS monitors system and warns like MCU JARVIS.

MCU JARVIS proactively says: "The compression in cylinder 3 appears to be low"
Our JARVIS should proactively say: "GPU temperature is rising, consider cooling"

This module runs periodic checks and generates warnings before problems occur.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.core.logging import get_logger

logger = get_logger(__name__)

# Thresholds for proactive warnings
THRESHOLDS = {
    "gpu_temp_warn": 75,      # GPU temperature warning (°C)
    "gpu_temp_critical": 85,  # GPU temperature critical (°C)
    "gpu_vram_warn": 0.85,    # VRAM usage warning (85%)
    "ram_warn": 0.80,         # RAM usage warning (80%)
    "ram_critical": 0.90,     # RAM usage critical (90%)
    "disk_warn": 0.85,        # Disk usage warning (85%)
    "cpu_warn": 0.90,         # CPU usage warning (90%)
    "thermal_throttle_delta": 200,  # MHz drop indicates throttling
}


@dataclass
class DiagnosticAlert:
    """A proactive diagnostic alert."""
    severity: str  # info, warning, critical
    component: str  # gpu, ram, disk, cpu, thermal
    message: str
    value: Any = None
    threshold: Any = None
    suggestion: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "component": self.component,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "suggestion": self.suggestion,
            "timestamp": self.timestamp,
        }


def check_gpu() -> list[DiagnosticAlert]:
    """Check GPU health and generate proactive alerts."""
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
        power = float(parts[1])
        vram_used = float(parts[2])
        vram_total = float(parts[3])
        clock_current = float(parts[4])
        clock_max = float(parts[5])

        vram_pct = vram_used / vram_total if vram_total > 0 else 0

        # Temperature alerts
        if temp >= THRESHOLDS["gpu_temp_critical"]:
            alerts.append(DiagnosticAlert(
                severity="critical",
                component="gpu",
                message=f"GPU temperature CRITICAL: {temp:.0f}°C",
                value=temp,
                threshold=THRESHOLDS["gpu_temp_critical"],
                suggestion="Consider stopping heavy workloads or improving cooling"
            ))
        elif temp >= THRESHOLDS["gpu_temp_warn"]:
            alerts.append(DiagnosticAlert(
                severity="warning",
                component="gpu",
                message=f"GPU temperature elevated: {temp:.0f}°C",
                value=temp,
                threshold=THRESHOLDS["gpu_temp_warn"],
                suggestion="Monitor closely, may throttle soon"
            ))

        # VRAM alerts
        if vram_pct >= THRESHOLDS["gpu_vram_warn"]:
            alerts.append(DiagnosticAlert(
                severity="warning",
                component="gpu",
                message=f"VRAM usage high: {vram_used:.0f}MB/{vram_total:.0f}MB ({vram_pct:.0%})",
                value=vram_pct,
                threshold=THRESHOLDS["gpu_vram_warn"],
                suggestion="Consider reducing context size or model layers"
            ))

        # Thermal throttling detection
        if clock_max > 0 and clock_current < (clock_max - THRESHOLDS["thermal_throttle_delta"]):
            alerts.append(DiagnosticAlert(
                severity="warning",
                component="thermal",
                message=f"GPU throttling detected: {clock_current:.0f}MHz vs {clock_max:.0f}MHz max",
                value=clock_current,
                threshold=clock_max,
                suggestion="GPU is thermally throttled, performance reduced"
            ))

    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass

    return alerts


def check_ram() -> list[DiagnosticAlert]:
    """Check RAM usage and generate proactive alerts."""
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
                alerts.append(DiagnosticAlert(
                    severity="critical",
                    component="ram",
                    message=f"RAM usage CRITICAL: {mem_used_pct:.0%}",
                    value=mem_used_pct,
                    threshold=THRESHOLDS["ram_critical"],
                    suggestion="System may become unresponsive, consider freeing memory"
                ))
            elif mem_used_pct >= THRESHOLDS["ram_warn"]:
                alerts.append(DiagnosticAlert(
                    severity="warning",
                    component="ram",
                    message=f"RAM usage elevated: {mem_used_pct:.0%}",
                    value=mem_used_pct,
                    threshold=THRESHOLDS["ram_warn"],
                    suggestion="Monitor closely"
                ))

    except Exception:
        pass

    return alerts


def check_disk() -> list[DiagnosticAlert]:
    """Check disk usage and generate proactive alerts."""
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
                    alerts.append(DiagnosticAlert(
                        severity="warning",
                        component="disk",
                        message=f"Disk usage high: {used_pct:.0%}",
                        value=used_pct,
                        threshold=THRESHOLDS["disk_warn"],
                        suggestion="Consider cleaning up old files or logs"
                    ))
    except Exception:
        pass

    return alerts


def run_proactive_diagnostics() -> list[DiagnosticAlert]:
    """Run all proactive diagnostic checks and return alerts."""
    alerts = []
    alerts.extend(check_gpu())
    alerts.extend(check_ram())
    alerts.extend(check_disk())
    return alerts


def format_alerts(alerts: list[DiagnosticAlert]) -> str:
    """Format alerts for display."""
    if not alerts:
        return "✅ All systems nominal"

    lines = []
    for alert in sorted(alerts, key=lambda a: {"critical": 0, "warning": 1, "info": 2}[a.severity]):
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}[alert.severity]
        lines.append(f"{icon} {alert.message}")
        if alert.suggestion:
            lines.append(f"   💡 {alert.suggestion}")

    return "\n".join(lines)


def get_system_summary() -> dict[str, Any]:
    """Get a comprehensive system summary for proactive monitoring."""
    summary = {
        "timestamp": time.time(),
        "alerts": [],
        "gpu": {},
        "ram": {},
        "disk": {},
    }

    # GPU
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            summary["gpu"] = {
                "temp_c": float(parts[0]),
                "power_w": float(parts[1]),
                "vram_used_mb": float(parts[2]),
                "vram_total_mb": float(parts[3]),
                "vram_pct": float(parts[2]) / float(parts[3]) if float(parts[3]) > 0 else 0,
            }
    except Exception:
        pass

    # RAM
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    summary["ram"]["total_kb"] = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    summary["ram"]["available_kb"] = int(line.split()[1])
        if "total_kb" in summary["ram"] and "available_kb" in summary["ram"]:
            summary["ram"]["used_pct"] = 1 - (summary["ram"]["available_kb"] / summary["ram"]["total_kb"])
    except Exception:
        pass

    # Alerts
    summary["alerts"] = [a.to_dict() for a in run_proactive_diagnostics()]

    return summary


if __name__ == "__main__":
    alerts = run_proactive_diagnostics()
    print(format_alerts(alerts))
    print(json.dumps(get_system_summary(), indent=2))
