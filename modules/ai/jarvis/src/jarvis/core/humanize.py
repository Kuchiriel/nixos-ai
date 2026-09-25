"""Ações humanizadas — o harness usa o computador como gente.

FERRAMENTA DE ACESSIBILIDADE (dono, 7 CIDs, 24/09 — não negociável):
opera o PC via periféricos simulados no nível do SO (evdev/uinput),
como leitor de tela, controle por voz ou o setup do Hawking — tecnologia
assistiva, não bot. Cadência humana + sem spam + regras dos servidores
respeitadas = uso legítimo. O que continua proibido: manipulação de DOM
em escala, spam/postagem em massa, violar ToS (isso bane e queima a conta).

Port da matemática do Wurm Ultimate (core/human_model.py — log-normal,
jitter gaussiano, burst-pause, fadiga) + caminho de mouse Bezier cúbico
+ atuadores Wayland (evdev/uinput direto; wtype p/ digitação).

Uso:
    from jarvis.core.humanize import HumanHand
    hand = HumanHand()
    hand.click(640, 480)      # move em curva + jitter + clique log-normal
    hand.type("olá mundo")    # cadência por tecla com variação

Anti-detecção E anti-ban: delays nunca fixos; movimento nunca retilíneo.
Acessibilidade do dono primeiro; abuso (spam, DOM em massa, rate violation)
continua recusado pelo harness. Uso legítimo: operação assistiva do próprio
dono, testes próprios, automação consentida.
"""

from __future__ import annotations

import math
import random
import shutil
import subprocess
import time


def _lognorm(mu: float, sigma: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, random.lognormvariate(mu, sigma)))


class HumanHand:
    """Mão humana: timing Wurm + Bezier + atuadores com fallback."""

    # Reação entre ações (ms, log-normal ~250ms)
    REACT_MU, REACT_SIG = 5.5, 0.3
    # Duração do clique (ms, log-normal ~70ms)
    CLICK_MU, CLICK_SIG = 3.0, 0.35
    # Jitter de mira (px, gaussiana)
    JITTER_X, JITTER_Y = 2.5, 2.0
    # Cadência de digitação por tecla (ms, log-normal ~90ms + rajadas)
    TYPE_MU, TYPE_SIG = 4.5, 0.5

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.actions = 0
        self.fatigue = 0.0

    # ── timing ──────────────────────────────────────────────
    def _think(self) -> None:
        ms = _lognorm(self.REACT_MU, self.REACT_SIG, 80, 800)
        ms *= 1.0 + self.fatigue * 0.4
        if not self.dry_run:
            time.sleep(ms / 1000.0)

    def _rest(self) -> None:
        # burst-pause: 60% rajada (pausa curta), senão pausa longa
        if random.random() < 0.6:
            s = _lognorm(-0.5, 0.4, 0.15, 0.8)
        else:
            s = random.uniform(0.4, 1.5) * (1.0 + self.fatigue * 0.3)
        if not self.dry_run:
            time.sleep(s)

    def _note(self) -> None:
        self.actions += 1
        self.fatigue = min(1.0, self.fatigue + 0.001)

    # ── mouse ───────────────────────────────────────────────
    @staticmethod
    def bezier_path(x0: float, y0: float, x1: float, y1: float,
                    n: int = 24) -> list[tuple[int, int]]:
        """Caminho Bezier cúbico com controle deslocado (nunca retilíneo)."""
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy) or 1.0
        # controle perpendicular, deslocamento proporcional à distância
        off = dist * random.uniform(0.05, 0.25) * random.choice([-1, 1])
        cx = mx - dy / dist * off + random.gauss(0, 8)
        cy = my + dx / dist * off + random.gauss(0, 8)
        pts = []
        for k in range(n + 1):
            t = k / n
            # quadrática (origem → controle → destino) chega perto o bastante
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
            y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
            pts.append((int(x), int(y)))
        return pts

    @staticmethod
    def cursor_pos() -> tuple[int, int] | None:
        """Posição atual via hyprctl (None sem display/Hyprland)."""
        if not shutil.which("hyprctl"):
            return None
        try:
            import json
            r = subprocess.run(["hyprctl", "cursorpos", "-j"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return None
            d = json.loads(r.stdout)
            return (int(d.get("x", 0)), int(d.get("y", 0)))
        except Exception:
            return None

    def _evdev(self):
        """Controlador uinput (lazy; None sem python-evdev/permissão)."""
        try:
            from evdev import UInput, ecodes as E
            ui = UInput({E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT],
                         E.EV_REL: [E.REL_X, E.REL_Y]}, name="jarvis-hand")
            return ui
        except Exception:
            return None

    def move(self, x: int, y: int) -> dict:
        """Move o cursor em curva Bezier com jitter de mira."""
        jx = random.gauss(0, self.JITTER_X)
        jy = random.gauss(0, self.JITTER_Y)
        tx, ty = int(x + jx), int(y + jy)
        pos = self.cursor_pos() or (tx, ty)
        path = self.bezier_path(pos[0], pos[1], tx, ty)
        if self.dry_run:
            return {"ok": True, "dry": True, "to": [tx, ty],
                    "steps": len(path)}
        ui = self._evdev()
        if ui is None:
            return {"ok": False,
                    "error": "sem atuador de mouse (python-evdev/uinput)"}
        try:
            from evdev import ecodes as E
            px, py = pos
            for sx, sy in path[1:]:
                ui.write(E.EV_REL, E.REL_X, sx - px)
                ui.write(E.EV_REL, E.REL_Y, sy - py)
                ui.syn()
                px, py = sx, sy
                time.sleep(random.uniform(0.002, 0.008))
            self._think()
            self._note()
            return {"ok": True, "to": [tx, ty], "steps": len(path)}
        except Exception as e:
            return {"ok": False, "error": f"mouse falhou: {e}"}
        finally:
            try:
                ui.close()
            except Exception:
                pass

    def click(self, x: int, y: int, button: str = "left") -> dict:
        """Move + clique com duração log-normal (como gente)."""
        mv = self.move(x, y)
        if not mv.get("ok"):
            return mv
        if self.dry_run:
            return {"ok": True, "dry": True, "at": mv["to"]}
        ui = self._evdev()
        if ui is None:
            return {"ok": False,
                    "error": "sem atuador de mouse (python-evdev/uinput)"}
        try:
            from evdev import ecodes as E
            btn = E.BTN_LEFT if button == "left" else E.BTN_RIGHT
            hold = _lognorm(self.CLICK_MU, self.CLICK_SIG, 25, 200) / 1000.0
            ui.write(E.EV_KEY, btn, 1)
            ui.syn()
            time.sleep(hold)
            ui.write(E.EV_KEY, btn, 0)
            ui.syn()
            self._rest()
            self._note()
            return {"ok": True, "at": mv["to"], "hold_ms": round(hold * 1000)}
        except Exception as e:
            return {"ok": False, "error": f"clique falhou: {e}"}
        finally:
            try:
                ui.close()
            except Exception:
                pass

    # ── teclado ─────────────────────────────────────────────
    def type(self, text: str) -> dict:
        """Digita com cadência humana (wtype; fallback: sem atuador)."""
        if self.dry_run:
            return {"ok": True, "dry": True, "chars": len(text)}
        if not shutil.which("wtype"):
            return {"ok": False,
                    "error": "wtype ausente (nix: wtype)"}
        try:
            for ch in text:
                subprocess.run(["wtype", ch], check=False,
                               capture_output=True, timeout=10)
                gap = _lognorm(self.TYPE_MU, self.TYPE_SIG, 20, 400) / 1000.0
                # pausa longa ocasional (pensando no meio da frase)
                if random.random() < 0.04:
                    gap += random.uniform(0.3, 0.9)
                time.sleep(gap)
            self._rest()
            self._note()
            return {"ok": True, "chars": len(text)}
        except Exception as e:
            return {"ok": False, "error": f"digitação falhou: {e}"}

    def key(self, *keys: str) -> dict:
        """Teclas especiais via wtype (ex: key('Return'), key('ctrl','c'))."""
        if self.dry_run:
            return {"ok": True, "dry": True, "keys": list(keys)}
        if not shutil.which("wtype"):
            return {"ok": False, "error": "wtype ausente (nix: wtype)"}
        try:
            args = []
            for k in keys:
                args += ["-k", k]
            subprocess.run(["wtype", *args], check=False,
                           capture_output=True, timeout=10)
            self._think()
            self._note()
            return {"ok": True, "keys": list(keys)}
        except Exception as e:
            return {"ok": False, "error": f"tecla falhou: {e}"}
