#!/usr/bin/env python3
"""uinput_raw — atuador de mouse por /dev/uinput cru (SEM python-evdev).

POR QUE EXISTE (07/10, medido pelo Buffy):
- ydotoold 1.0.4 deste ambiente: '-a' NÃO é absoluto real (mantém posição
 interna própria, dessincroniza do cursor); relativo perde eventos
 (segundoocê_sub_SEGUNDO 'mousemove 100 50' seguido não move);
- rel cru com GANHO CONSTANTE (~1.96 = aceleração do Hyprland) + FEEDBACK
 por hyprctl cursorpos (fechar em ≤3 iterações) acerta em ±3px sempre.

Não depende de nenhuma lib externa. Compatível com EventRel em contextos
de rede sem rootLEEP (/dev/uinput precisa grupo input/uinput — dono tem).

API:
  hand = RawHand()
  hand.move_abs(960, 540)  → dict ok/at/iter
  hand.click(960, 540)     → move + clique (hold log-normal fica no caller)
  hand.button(button, down=True/False)
"""
from __future__ import annotations

import fcntl
import os
import struct
import subprocess
import time

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
BTN = {"left": 0x110, "right": 0x111, "middle": 0x112}
REL_X, REL_Y = 0, 1

EV = struct.Struct("LLHHi")   # input_event padrão 64-bit (timeval 2×L)
UDEV = struct.Struct("80shhhhI" + "i" * 256)

_BTN_DOWN = {}


class RawHand:
    """Mão de mouse por uinput cru + feedback (determinístico)."""

    def __init__(self, gain: tuple[float, float] | None = None):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
        for b in BTN.values():
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, b)
        for r in (REL_X, REL_Y):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, r)
        setup = b"jarvis-hand".ljust(80, b"\0") + struct.pack(
            "hhhh", 0x06, 0, 0, 1) + struct.pack("I", 0) + b"\0" * (64 * 4 * 4)
        os.write(self.fd, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE, 1)
        time.sleep(0.05)
        self._gain = gain
        self._init_pos = self.cursor_pos()

    # ── infra ───────────────────────────────────────────────
    def _ev(self, t: int, c: int, v: int) -> None:
        os.write(self.fd, EV.pack(0, 0, t, c, v))

    def _syn(self) -> None:
        self._ev(EV_SYN, 0, 0)

    def rel(self, dx: int, dy: int) -> None:
        self._ev(EV_REL, REL_X, dx)
        self._ev(EV_REL, REL_Y, dy)
        self._syn()

    @staticmethod
    def cursor_pos() -> tuple[int, int] | None:
        try:
            out = subprocess.run(["hyprctl", "cursorpos"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
            x, y = out.split(",")
            return int(x), int(y)
        except Exception:
            return None

    def _calibrate(self, x: int, y: int) -> tuple[float, float]:
        """Ganho real/enviado com probe na DIREÇÃO do alvo (fechado por
        feedback). Medir na direção real importa: a curva de aceleração do
        compositor varia com velocidade/direção (medido: ~1.96 rápido,
        ~0.63 em micro-passos lentos, ~1.5 intermediário). Probe curto na
        direção certa + iterações de correção convergem pra qualquer alvo.
        """
        if self._gain is not None:
            return self._gain
        p0 = self.cursor_pos()
        if p0 is None:
            self._gain = (1.0, 1.0)
            return self._gain
        dx, dy = x - p0[0], y - p0[1]
        n = max(30, min(120, max(abs(dx), abs(dy)) // 3))
        ux = (1 if dx > 0 else -1) if dx else 0
        uy = (1 if dy > 0 else -1) if dy else 0
        for _ in range(n):
            self.rel(ux, uy)
        time.sleep(0.12)
        p1 = self.cursor_pos() or p0
        mx, my = p1[0] - p0[0], p1[1] - p0[1]
        gx = max(0.2, min(6.0, mx / n if n else 1.0)) if ux else 1.0
        gy = max(0.2, min(6.0, my / n if n else 1.0)) if uy else 1.0
        self._gain = (gx, gy)
        return self._gain

    # ── alto nível ──────────────────────────────────────────
    def move_abs(self, x: int, y: int, max_iter: int = 4,
                 tol: int = 2) -> dict:
        """Move por REL 1×1 + feedback (converge por bissecção natural).

        Por que micro-passos de 1: a aceleração do compositor torna o mape
        unidade→px NÃO-LINEAR (0.63–1.96 medido) e dependente de direção;
        passos de 1 vivem no chão da curva (≈1.5×) e o loop por feedback
        corrige o resto — sem modelo do ganho, convergência garantida.
        """
        gx, gy = self._calibrate(x, y)
        at = self.cursor_pos() or (x, y)
        it = 0
        for it in range(1, max_iter + 1):
            dx, dy = x - at[0], y - at[1]
            if abs(dx) <= tol and abs(dy) <= tol:
                break
            # ESTRATÉGIA: enviar o ERRO RESIDUAL inteiro como micro-passos
            # de 1 unidade crua (sem depender de ganho! 1 cru = 1.5–2 reais,
            # nunca 0 — o feedback fecha o loop sem matemática frágil)
            n = max(1, min(200, max(abs(dx), abs(dy))))
            ux = (1 if dx > 0 else -1) if dx else 0
            uy = (1 if dy > 0 else -1) if dy else 0
            for _ in range(n):
                self.rel(ux, uy)
            time.sleep(0.08)
            at = self.cursor_pos() or at
            # se passou do alvo (overshoot), a próxima iteração volta — o
            # loop converge por bisection natural; máx 4 iterações
        return {"ok": abs(at[0] - x) <= max(6, tol * 3)
                and abs(at[1] - y) <= max(6, tol * 3),
                "at": list(at), "iter": it, "gain": [round(gx, 3),
                                                     round(gy, 3)]}

    def button(self, button: str = "left", down: bool = True) -> None:
        b = BTN.get(button, BTN["left"])
        v = 1 if down else 0
        self._ev(EV_KEY, b, v)
        self._syn()
        _BTN_DOWN[button] = down if v else False

    def click(self, x: int, y: int, button: str = "left",
              hold_ms: int = 70) -> dict:
        mv = self.move_abs(x, y)
        if not mv["ok"]:
            mv["error"] = "não cheguei no alvo"
            return mv
        self.button(button, True)
        time.sleep(max(0.02, hold_ms / 1000.0))
        self.button(button, False)
        mv["clicked"] = button
        return mv

    def close(self) -> None:
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY, 0)
        except Exception:
            pass
        os.close(self.fd)
