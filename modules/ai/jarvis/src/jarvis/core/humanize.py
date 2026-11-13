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

import json
import math
import os
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

    YDOTOOL_ENV = {"YDOTOOL_SOCKET": "/run/user/1000/.ydotool_socket"}
    # 07/10 (Buffy): ydotoold 1.0.4 deste ambiente é INSEGURO como atuador
    # primário — '-a' não é absoluto real (posição interna própria, perde
    # sincronia com o cursor) e relativo perde eventos em rajada.
    # ATUADOR PRIMÁRIO AGORA: uinput_raw.RawHand (REL cru + feedback
    # hyprctl) — determinístico, ±3px, medido. ydotool fica como fallback.

    @classmethod
    def _cursor(cls) -> tuple[int, int] | None:
        try:
            out = subprocess.run(["hyprctl", "cursorpos"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
            x, y = out.split(",")
            return (int(x), int(y))
        except Exception:
            return None

    def _evdev(self):
        """Controlador uinput (lazy; None sem python-evdev/permissão).

        (13/11) não devolve mais "ydotool": o ydotool presente no PATH não é
        um atuador de mouse utilizável (ver comentário do YDOTOOL_ENV), então
        o fallback caía num sentinela que nenhum caller sabia usar e o
        resultado era "sem atuador" com o ydotool instalado.
        """
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
        # ATUADOR 1 (primário): uinput cru + feedback por waypoint ABSOLUTO.
        # (13/11) antes os waypoints iam como REL cru, que o compositor
        # multiplica por ~1.5-2 => o cursor pousava longe e o alvo final
        # errava 30-50 px. Waypoint absoluto usa o mesmo loop fechado do
        # destino, então a curva é real e o pouso é exato.
        try:
            from jarvis.core.uinput_raw import RawHand
            if getattr(self, "_raw", None) is None:
                self._raw = RawHand()
            for sx, sy in path[1::3]:
                self._raw.move_abs(sx, sy, max_iter=2, tol=8)
            self._think()
            self._note()
            r = self._raw.move_abs(tx, ty)   # fecho por feedback
            r["actuator"] = "uinput-raw"
            r["bezier_steps"] = len(path)
            if not r.get("ok"):
                r["error"] = (f"nao cheguei no alvo: pedido ({tx},{ty}), "
                              f"cursor em {r.get('at')}")
            return r
        except Exception as e:
            uinput_err = f"uinput falhou: {e}"
        # ATUADOR 2: evdev/uinput (caminho relativo; só se ydotool sumir)
        ui = self._evdev()
        if ui is None or ui == "ydotool":
            return {"ok": False,
                    "error": f"sem atuador de mouse ({uinput_err}; evdev idem)"}
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
        # uinput cru com hold log-normal (mesma física, atuador confiável)
        try:
            from jarvis.core.uinput_raw import RawHand
            if getattr(self, "_raw", None) is None:
                self._raw = RawHand()
            hold = int(_lognorm(self.CLICK_MU, self.CLICK_SIG, 25, 200))
            r = self._raw.click(x, y, button, hold_ms=hold)
            self._think()
            self._note()
            if not r.get("ok"):
                r["error"] = (f"nao cheguei no alvo: pedido ({x},{y}), "
                              f"cursor em {r.get('at')}")
            return r
        except Exception as e:
            click_err = f"uinput click falhou: {e}"
        ui = self._evdev()
        if ui is None:
            return {"ok": False,
                    "error": f"sem atuador de clique ({click_err}; evdev idem)"}
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
        """Digita com cadência humana (ydotool; fallback: wtype).

        2026-10-02: o backend virou `ydotool`, não `wtype`. Motivo medido:
        `wtype` NÃO digita neste ambiente — o texto não aparecia no campo do
        jogo. Causa: o `ydotool` falhava em silêncio por socket em lugar
        errado, e o `wtype` depende do mesmo uinput (wayland-text-input).
        Agora com `ydotoald` no XDG_RUNTIME_DIR correto, os dois funcionam,
        mas `ydotool` é o backend comprovado — então é o primário.
        """
        if self.dry_run:
            return {"ok": True, "dry": True, "chars": len(text)}
        yt = shutil.which("ydotool")
        wt = shutil.which("wtype")
        if not yt and not wt:
            return {"ok": False,
                    "error": "nem ydotool nem wtype disponiveis"}
        # (13/11) sem o socket do daemon no env, o ydotool falha em SILÊNCIO
        # (check=False) e a tool respondia ok sem nada digitado. O socket do
        # dono vive no XDG_RUNTIME_DIR; se existir, manda no env.
        env = None
        if yt:
            sock = self.YDOTOOL_ENV["YDOTOOL_SOCKET"]
            if os.path.exists(sock):
                env = {**os.environ, **self.YDOTOOL_ENV}
        failures = 0
        try:
            for ch in text:
                if yt:
                    # (12/10, fix "12A12G12E...") ESTE ydotool não tem
                    # '--delay' (a flag real é '-d/--key-delay=N'): o parser
                    # engolia '--delay 12' e DIGITAVA "12" antes de cada
                    # tecla — todo texto do MCP chegava "12"+ch no destino
                    # (medido no terminal do outro agente). A cadência humana
                    # já vem do sleep lognorm abaixo; delay interno = letal.
                    run = subprocess.run([yt, "type", ch],
                                         check=False, capture_output=True,
                                         timeout=15, env=env)
                else:
                    run = subprocess.run(["wtype", ch], check=False,
                                         capture_output=True, timeout=10)
                if run.returncode != 0:
                    failures += 1
                gap = _lognorm(self.TYPE_MU, self.TYPE_SIG, 20, 400) / 1000.0
                # pausa longa ocasional (pensando no meio da frase)
                if random.random() < 0.04:
                    gap += random.uniform(0.3, 0.9)
                time.sleep(gap)
            self._rest()
            self._note()
            if failures and failures == len(text):
                return {"ok": False,
                        "error": ("nada foi digitado: ydotool/wtype retornaram "
                                  "erro em todas as teclas (daemon/socket?)")}
            return {"ok": True, "chars": len(text), "failed": failures}
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

    def double_click(self, x: int, y: int, button: str = "left") -> dict:
        """Dois cliques no MESMO ponto, com intervalo humano (abre arquivo)."""
        mv = self.move(x, y)
        if not mv.get("ok"):
            return mv
        if self.dry_run:
            return {"ok": True, "dry": True, "at": mv.get("to", [x, y])}
        try:
            from jarvis.core.uinput_raw import RawHand
            if getattr(self, "_raw", None) is None:
                self._raw = RawHand()
            at = self._raw.move_abs(x, y)
            if not at.get("ok"):
                at["error"] = (f"nao cheguei no alvo: pedido ({x},{y}), "
                               f"cursor em {at.get('at')}")
                return at
            for _ in range(2):
                self._raw.button(button, True)
                time.sleep(_lognorm(self.CLICK_MU, self.CLICK_SIG, 25, 120) / 1000.0)
                self._raw.button(button, False)
                time.sleep(random.uniform(0.06, 0.14))
            self._think()
            self._note()
            at["clicked"] = f"double-{button}"
            return at
        except Exception as e:
            return {"ok": False, "error": f"double click falhou: {e}"}

    def drag(self, x1: int, y1: int, x2: int, y2: int,
             button: str = "left") -> dict:
        """Arrasta de (x1,y1) a (x2,y2) com o botão pressionado.

        O botão SEMPRE solta no finally: um drag interrompido não pode deixar
        o mouse do dono travado em "pressionado" (mesma classe do incidente
        do ydotool que grudava tecla).
        """
        mv = self.move(x1, y1)
        if not mv.get("ok"):
            return mv
        if self.dry_run:
            return {"ok": True, "dry": True, "from": [x1, y1], "to": [x2, y2]}
        try:
            from jarvis.core.uinput_raw import RawHand
            if getattr(self, "_raw", None) is None:
                self._raw = RawHand()
            self._raw.move_abs(x1, y1)
        except Exception as e:
            return {"ok": False, "error": f"drag: sem atuador: {e}"}
        self._raw.button(button, True)
        try:
            # waypoints intermediários: o compositor vê um arrasto, não um salto
            for k in range(1, 9):
                t = k / 8
                self._raw.move_abs(int(x1 + (x2 - x1) * t),
                                   int(y1 + (y2 - y1) * t),
                                   max_iter=2, tol=12)
                time.sleep(random.uniform(0.02, 0.06))
            r = self._raw.move_abs(x2, y2)
        except Exception as e:
            return {"ok": False, "error": f"drag falhou: {e}"}
        finally:
            self._raw.button(button, False)
        self._think()
        self._note()
        r["dragged"] = {"from": [x1, y1], "to": [x2, y2]}
        return r

    def scroll(self, dy: int = 300) -> dict:
        """Scroll com passos humanos (ydotool; fallback: wtype -M)."""
        if self.dry_run:
            return {"ok": True, "dry": True, "dy": dy}
        yt = shutil.which("ydotool")
        try:
            if yt:
                rest = int(dy)
                while rest:
                    passo = 120 if rest > 0 else -120
                    subprocess.run([yt, "click", "0x80" if dy > 0 else "0x81"],
                                   check=False, capture_output=True, timeout=10)
                    rest -= passo
                    time.sleep(_lognorm(4.0, 0.4, 20, 200) / 1000.0)
            else:
                # wtype tem scroll por botão virtual
                botao = 4 if dy > 0 else 5
                n = max(1, min(30, abs(dy) // 120))
                for _ in range(n):
                    subprocess.run(["wtype", "-M", str(botao), "-m", str(botao)],
                                   check=False, capture_output=True, timeout=10)
                    time.sleep(0.03)
            self._note()
            return {"ok": True, "dy": dy}
        except Exception as e:
            return {"ok": False, "error": f"scroll falhou: {e}"}


# ── localizar por texto (OCR → coordenadas) ────────────────
#
# Por que existe (13/11): o ciclo observe → clicar tinha um buraco. O
# observe devolve TEXTO, e o modelo tinha de adivinhar o pixel do botão.
# localizar pelo texto que ele já leu fecha o ciclo sem chute: o tesseract
# TSV (nível 5 = palavra) dá caixa e confiança por palavra, e a caixa vira
# coordenada de tela.


def _norm_text(s: str) -> str:
    """Casefold sem acento e sem pontuação de borda (busca tolerante)."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold().strip(" \t\n\r.,:;!?()[]{}<>\"'|/\\-–—")


def _ocr_tsv(path: str, lang: str = "eng", psm: str = "11",
             timeout: float = 25.0) -> list[dict]:
    """Palavras do tesseract TSV com caixa e confiança.

    Só o nível 5 tem texto e confiança (0-100); os níveis 1-4 são layout e
    vêm com conf -1 (documentação do formato TSV).
    """
    try:
        r = subprocess.run(
            ["tesseract", path, "stdout", "-l", lang, "--psm", psm, "tsv"],
            capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out: list[dict] = []
    for line in (r.stdout or "").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            level = int(cols[0])
            conf = float(cols[10])
            left, top = int(cols[6]), int(cols[7])
            w, h = int(cols[8]), int(cols[9])
        except ValueError:
            continue
        text = cols[11].strip()
        if level != 5 or not text or conf < 0:
            continue
        out.append({"text": text, "left": left, "top": top, "w": w,
                    "h": h, "conf": conf,
                    "line": (cols[1], cols[2], cols[3], cols[4])})
    return out


def _ocr_words_any(path: str, budget: float = 30.0,
                   lang: str = "eng") -> list[dict]:
    """Palavras com o melhor psm e, se vazio, com a imagem em alto contraste.

    Tema escuro é o caso do dono: sem o pré-processamento o tesseract
    devolve pouco ou nada. Ordem: imagem crua, depois binarizada (psm 11 e
    6). Para no primeiro resultado não vazio.

    (13/11) TETO TOTAL obrigatório: uma tela cheia de terminal levou 72 s
    porque cada variante/psm rodava com timeout próprio, um atrás do outro.
    Agora o orçamento é um só e o próximo passo nunca começa sem tempo.
    """
    deadline = time.time() + max(6.0, float(budget))

    def restante(cap: float) -> float:
        return max(0.5, min(cap, deadline - time.time()))

    # O primeiro passe fica com a maior fatia: numa tela densa ele sozinho
    # passou de 15 s, e um teto curto matava o único passe que ia funcionar.
    # `eng` primeiro: medido nesta tela, 5,5 s contra 12,2 s de `por+eng`.
    # Acento em pt-BR é resolvido no segundo passe (só quando não achar).
    words = _ocr_tsv(path, lang=lang, psm="11",
                     timeout=restante(max(6.0, float(budget) * 0.7)))
    if words:
        return words
    variants = []
    if deadline - time.time() > 2.0:
        try:
            from PIL import Image, ImageOps
            img = Image.open(path).convert("L")
            img = ImageOps.autocontrast(img)
            alt = path.rsplit(".", 1)[0] + "-locate.png"
            img.point(lambda p: 255 if p > 140 else 0).save(alt)
            variants.append(alt)
        except Exception:
            pass
    for v in variants:
        for psm in ("11", "6", "3"):
            if deadline - time.time() <= 1.0:
                return []
            words = _ocr_tsv(v, lang=lang, psm=psm, timeout=restante(8.0))
            if words:
                return words
    return []


def _match_hits(words: list[dict], query: str,
                min_conf: float = 40.0) -> list[dict]:
    """Casa a busca contra as palavras: exato > prefixo > contido, e frase.

    Frase ("Salvar como") é casada por palavras consecutivas na MESMA linha
    do TSV, com a caixa unida. Cada hit leva `score` para desempatar.
    """
    q = _norm_text(query)
    if not q:
        return []
    qtok = [t for t in q.split() if t]
    hits: list[dict] = []
    for w in words:
        if w["conf"] < min_conf:
            continue
        nw = _norm_text(w["text"])
        if not nw:
            continue
        score = 0
        if len(qtok) == 1:
            if nw == q:
                score = 4
            elif nw == qtok[0]:
                score = 3
            elif nw.startswith(q) or q in nw:
                score = 2
            elif nw in q and len(nw) >= 4:
                score = 1   # OCR juntou/partiu palavra
        else:
            # token único da frase (ex.: "Salvar" de "Salvar como"):
            # vale menos que a frase inteira
            if nw == qtok[0]:
                score = 1
        if score:
            hits.append({**w, "score": score, "matched": w["text"]})

    if len(qtok) > 1:
        by_line: dict[tuple, list[dict]] = {}
        for w in words:
            if w["conf"] >= min_conf:
                by_line.setdefault(w["line"], []).append(w)
        for line_words in by_line.values():
            line_words.sort(key=lambda x: x["left"])
            for i in range(len(line_words)):
                acc: list[dict] = []
                for j in range(i, min(i + len(qtok) + 2, len(line_words))):
                    acc.append(line_words[j])
                    joined = _norm_text(" ".join(x["text"] for x in acc))
                    if joined == q:
                        score = 5
                    elif len(acc) == len(qtok) and joined.startswith(q):
                        score = 3
                    else:
                        continue
                    left = min(x["left"] for x in acc)
                    top = min(x["top"] for x in acc)
                    right = max(x["left"] + x["w"] for x in acc)
                    bottom = max(x["top"] + x["h"] for x in acc)
                    hits.append({"text": " ".join(x["text"] for x in acc),
                                 "left": left, "top": top,
                                 "w": right - left, "h": bottom - top,
                                 "conf": min(x["conf"] for x in acc),
                                 "line": acc[0]["line"], "score": score,
                                 "matched": " ".join(x["text"] for x in acc)})
                    break

    # dedupe por caixa (frase + palavra geram o mesmo alvo)
    seen = set()
    uniq = []
    for h in hits:
        key = (h["left"], h["top"], h["w"], h["h"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    uniq.sort(key=lambda h: (-h["score"], -h["conf"], h["top"], h["left"]))
    return uniq


def _screen_geometry() -> dict:
    """Monitor focado (hyprctl): nome, origem, tamanho lógico e escala."""
    try:
        mons = json.loads(subprocess.run(
            ["hyprctl", "monitors", "-j"], capture_output=True,
            text=True, timeout=5).stdout)
        m = next((x for x in mons if x.get("focused")), mons[0] if mons else {})
        return {"name": m.get("name", "?"), "x": int(m.get("x", 0)),
                "y": int(m.get("y", 0)), "width": int(m.get("width", 0)),
                "height": int(m.get("height", 0)),
                "scale": float(m.get("scale", 1.0) or 1.0)}
    except Exception:
        return {}


def locate_text(text: str, min_conf: float = 40.0,
                limit: int = 6, budget: float = 30.0) -> dict:
    """Acha `text` na tela por OCR e devolve coordenadas de clique.

    Lê a captura inteira (grim), roda o tesseract em TSV e converte a caixa
    da palavra para pixels LÓGICOS do monitor focado (o que o human_input
    usa). Devolve `best` mais até `limit` candidatos ordenados por
    qualidade, para o modelo escolher quando há dois botões iguais.
    """
    if not text or not str(text).strip():
        return {"ok": False, "error": "locate precisa text"}
    if not shutil.which("tesseract"):
        return {"ok": False, "error": "tesseract ausente (nix: tesseract)"}
    try:
        from jarvis.core.vision import capture_full
    except Exception as e:
        return {"ok": False, "error": f"vision indisponivel: {e}"}
    shot = capture_full()
    if not shot.get("ok"):
        return {"ok": False, "error": shot.get("error", "captura falhou")}
    path = shot["path"]

    deadline = time.time() + max(8.0, float(budget))
    words = _ocr_words_any(path, budget=max(6.0, deadline - time.time()))
    hits = _match_hits(words, str(text), min_conf=min_conf)
    if not hits:
        # Segundo passe com o modelo pt-BR (mais lento): só quando o eng não
        # achou, para acento/ç não virarem "nao encontrado".
        restante = deadline - time.time()
        if restante > 4.0:
            words2 = _ocr_words_any(path, budget=restante, lang="por+eng")
            hits = _match_hits(words2, str(text), min_conf=min_conf)
            words = words or words2
    if not words:
        return {"ok": False,
                "error": (f"OCR nao leu texto na tela em {budget:.0f}s "
                          "(tela densa demais? tente um texto maior/curto)"),
                "image": path}
    if not hits:
        # ajuda o modelo: o que EXISTE na tela, para ele corrigir a busca
        amostra = sorted(words, key=lambda w: -w["conf"])[:12]
        return {"ok": False, "error": f"texto nao encontrado: {text!r}",
                "image": path,
                "visible": [w["text"] for w in amostra]}

    geo = _screen_geometry()
    # imagem (pixels físicos) -> tela (pixels lógicos): grim pode capturar
    # em resolução maior que a lógica (escala > 1).
    img_w = img_h = 0
    try:
        from PIL import Image
        with Image.open(path) as im:
            img_w, img_h = im.size
    except Exception:
        pass
    fx = (geo.get("width", 0) / img_w) if img_w and geo.get("width") else 1.0
    fy = (geo.get("height", 0) / img_h) if img_h and geo.get("height") else 1.0

    out = []
    for h in hits[:max(1, int(limit))]:
        cx, cy = h["left"] + h["w"] / 2, h["top"] + h["h"] / 2
        out.append({"text": h["matched"], "conf": round(h["conf"]),
                    "score": h["score"],
                    "image": [round(cx), round(cy)],
                    "screen": [round(geo.get("x", 0) + cx * fx),
                               round(geo.get("y", 0) + cy * fy)],
                    "box": [h["left"], h["top"], h["w"], h["h"]]})
    return {"ok": True, "query": str(text), "best": out[0],
            "matches": out, "image": path, "monitor": geo}


def human_input(args: dict) -> str:
    """Tool do MCP (jarvis_human_input): mão humana no desktop Wayland.

    Aceita o formato declarado no mcp_server (action/x/y/button/text/
    keys/dy/dry_run). Tudo por cima do HumanHand — nada de input cru.
    """
    action = (args.get("action") or "").strip().lower()
    dry = bool(args.get("dry_run", False))
    hand = HumanHand(dry_run=dry)

    if action == "move":
        if args.get("x") is None or args.get("y") is None:
            return "ERROR: move precisa x e y (pixels da tela 1920x1080)"
        r = hand.move(int(args["x"]), int(args["y"]))
    elif action == "click":
        if args.get("x") is None or args.get("y") is None:
            return "ERROR: click precisa x e y"
        r = hand.click(int(args["x"]), int(args["y"]),
                       args.get("button", "left"))
    elif action == "type":
        text = args.get("text")
        if not text:
            return "ERROR: type precisa text"
        r = hand.type(str(text))
    elif action == "key":
        keys = (args.get("keys") or "").split()
        if not keys:
            return "ERROR: key precisa keys (ex: 'mod+m' ou 'space')"
        # 'mod+m' → dois argumentos: mod + m (HumanHand.key aceita variádico)
        expanded = []
        for k in keys:
            if "+" in k:
                expanded += k.split("+")
            else:
                expanded.append(k)
        r = hand.key(*expanded)
    elif action == "scroll":
        r = hand.scroll(int(args.get("dy", 300)))
    elif action == "double_click":
        if args.get("x") is None or args.get("y") is None:
            return "ERROR: double_click precisa x e y"
        r = hand.double_click(int(args["x"]), int(args["y"]),
                              args.get("button", "left"))
    elif action == "drag":
        falta = [k for k in ("x", "y", "x2", "y2") if args.get(k) is None]
        if falta:
            return f"ERROR: drag precisa x, y, x2 e y2 (falta: {', '.join(falta)})"
        r = hand.drag(int(args["x"]), int(args["y"]),
                      int(args["x2"]), int(args["y2"]),
                      args.get("button", "left"))
    elif action == "locate":
        # Fecha o ciclo sem chute de pixel: o modelo passa o TEXTO que já
        # leu no observe e recebe a coordenada (OCR TSV do tesseract).
        text = args.get("text")
        if not text or not str(text).strip():
            return "ERROR: locate precisa text (o texto visivel na tela)"
        r = locate_text(str(text), min_conf=float(args.get("min_conf", 40.0)),
                        budget=float(args.get("budget", 30.0)))
        if not r.get("ok"):
            vis = r.get("visible") or []
            extra = f" | visivel: {', '.join(vis[:12])}" if vis else ""
            return f"ERROR: {r.get('error', 'texto nao encontrado')}{extra}"
        return json.dumps(r, ensure_ascii=False)
    else:
        return (f"ERROR: action desconhecida '{action}'. "
                "Use: move, click, double_click, drag, type, key, scroll, "
                "locate")

    if not r.get("ok", False):
        return f"ERROR: {r.get('error', 'falhou')}"
    return json.dumps(r, ensure_ascii=False)

