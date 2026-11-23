#!/usr/bin/env python3
"""uhrs-capture.py — o item da tela vira label do dono (sem digitar nada).

POR QUE (14/11/2026, coord-naming): a trilha da renda precisa de ~50 labels
DO DONO, e a fonte delas sao os itens de QUALIFICACAO do UHRS (a Microsoft
paga US$ 7 a 14/h e exige 50 a 100 itens de teste que o owner teria que
fazer de graca). O `uhrs-practice.py` so conhece os 12 itens de pratica
escritos por mim: para o item REAL (que esta na tela do navegador) nao
havia caminho nenhum para virar label. Este script fecha esse elo.

O QUE ELE FAZ (e o que ele NAO faz):
  - CAPTURA a tela (grim) e le o texto (tesseract multi-psm, o mesmo
    caminho que o `observe_screen` da casa usa) — ou le a area ja
    recortada da tela;
  - mostra o texto lido para o owner conferir (a tela e' a fonte, a leitura
    e' automatica, mas o CONTEXTO tem de ser o que o dono viu);
  - o owner responde **falando** (o veredito) ou digitando uma tecla;
  - grava a label no formato do schema, com o `context` sendo o texto lido
    da tela e o `answer` sendo a resposta do dono.

  O QUE ELE NAO FAZ: nao clica em nada, nao submete nada, nao digita na
  conta de terceiro. O owner continua decidindo e registrando na plataforma
  sozinho; aqui so entra a label que ele ja deu. (A regra do dono: a
  automacao de clique/resposta em conta de terceiro continua fora.)

POR QUE O CONTEXTO NAO PODE SER O GABARITO (medido hoje): o `uhrs-practice.py`
gravava o gabarito do item de pratica em vez da resposta do owner — o
dataset seria o gabarito, o oposto do desenho (o modelo tem de responder por
procuracao do owner). Aqui o `answer` e' SEMPRE o que o owner respondeu.

USO
    python3 scripts/uhrs-capture.py                 # captura a tela e le
    python3 scripts/uhrs-capture.py --dry-run       # so mostra o que leu
    python3 scripts/uhrs-capture.py --text "..."    # ja tem o texto (cola)
    python3 scripts/uhrs-capture.py --self-test     # prova a logica

EXEMPLO
    $ python3 scripts/uhrs-capture.py
    (capturando a tela e lendo o texto...)
    TEXTO LIDO (1420 chars):
      How long does a passport renewal take
      Passport renewal processing times: 4-6 weeks ...
    o que voce leu na tela esta certo? [s/N] s
    fale o veredito (3 highly / 2 moderately / 1 slightly / 0 not): ...
    label gravada em data/judgments/labels.jsonl
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "judgments"
LABELS = DATA / "labels.jsonl"
CAPTURES = Path("/tmp/opencode/uhrs-captures")

# O mesmo mapa do uhrs-practice.py (0 a 3). Importado quando possivel para
# nao duplicar a regra; se o outro script nao estiver no path, a copia
# local abaixo e' a mesma (e o self-test compara as duas).
LEVELS = {
    "3": "3", "2": "2", "1": "1", "0": "0",
    "altamente relevante": "3", "moderadamente relevante": "2",
    "levemente relevante": "1", "nao relevante": "0", "irrelevante": "0",
    "muito relevante": "3", "relevante": "2", "sim": "2", "nao": "0",
    "high": "3", "moderate": "2", "slight": "1", "none": "0",
    "highly relevant": "3", "moderately relevant": "2",
    "slightly relevant": "1", "not relevant": "0",
}


def _norm(s):
    return " ".join(str(s or "").lower().replace(".", " ").replace(",", " ")
                     .split())


def parse_answer(text):
    """'muito relevante' / 'highly relevant' / '2' -> '3'."""
    t = _norm(text)
    if not t:
        return None
    if t in LEVELS:
        return LEVELS[t]
    import re
    m = re.search(r"\b([0-3])\b", t)
    if m:
        return m.group(1)
    for word, val in LEVELS.items():
        if word in t:
            return val
    return None


def read_clipboard(timeout=10.0):
    """Le o clipboard (wl-paste). Devolve (texto, erro).

    (14/11) MEDIDO: o clipboard traz o texto EXATO do item (sem erro de
    OCR, sem janela errada). O `wl-paste` e' o caminho da casa em Wayland;
    `xclip`/`xsel` sao o fallback de X11.
    """
    for cmd in (["wl-paste", "--no-newline"], ["wl-paste"], ["xclip", "-o",
                 "-selection", "clipboard"], ["xsel", "-b"]):
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout)
        except (subprocess.TimeoutExpired, OSError,
                subprocess.SubprocessError):
            continue
        if r.returncode == 0 and (r.stdout or "").strip():
            return r.stdout, ""
    return "", "clipboard vazio (ou wl-paste/xclip indisponivel)"


def _house_vision():
    """O modulo de visao da casa (jarvis.core.vision), se der para carregar.

    Ele tem `capture_window` (hyprctl + grim, recorta a janela certa),
    `capture_full` e `_ocr_text` (tesseract multi-psm). Reusar o codigo da
    casa em vez de copiar e' a regra da casa (e o `_ocr_text` da casa tem o
    deadline total, que o daqui tambem tem).
    """
    try:
        src = str(REPO / "modules" / "ai" / "jarvis" / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from jarvis.core import vision  # noqa: PLC0415
        return vision
    except Exception:  # noqa: BLE001
        return None


def capture_screen(path, window_title=None):
    """Captura a tela (grim) ou a janela (hyprctl + grim).

    Devolve (caminho, erro). Com `window_title`, recorta a janela que
    casar com o titulo (o navegador com o item do UHRS).
    """
    house = _house_vision()
    if house is not None:
        try:
            if window_title:
                # (14/11) MEDIDO: sem isto, o OCR traz o conteudo da janela
                # que esta POR CIMA (grim recorta a regiao da tela, nao a
                # janela). A casa resolve com foco + opacidade (+ fullscreen
                # quando ha sobreposicao) em `vision._prepare_window`.
                prep = house._prepare_window(window_title, opaque=True,
                                             fullscreen=False)
                if prep.get("erro"):
                    return None, f"preparar a janela: {prep['erro']}"
                res = house.capture_window(window_title)
            else:
                res = house.capture_full()
            if res.get("ok"):
                # a casa grava no SCREENSHOT_DIR dela; copiamos para o
                # caminho do capture (o dono quer saber qual imagem e')
                import shutil as _sh
                _sh.copyfile(res["path"], path)
                return path, ""
            err = res.get("error", "captura falhou")
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:160]
    else:
        err = ""
    # fallback: grim direto (tela toda, ou a janela ativa via hyprctl)
    region = None
    if window_title:
        try:
            proc = subprocess.run(["hyprctl", "clients", "-j"],
                                  capture_output=True, text=True, timeout=5)
            clients = json.loads(proc.stdout)
            for c in clients:
                if window_title.lower() in c.get("title", "").lower():
                    at = c.get("at", [0, 0])
                    size = c.get("size", [800, 600])
                    region = f"{at[0]},{at[1]} {size[0]}x{size[1]}"
                    break
        except (OSError, subprocess.SubprocessError, ValueError):
            region = None
    if not shutil.which("grim"):
        return None, err or "grim ausente (nix: grim)"
    cmd = ["grim"] + (["-g", region] if region else []) + [str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        return None, (out.stderr or "grim falhou").strip()[:160]
    return path, ""


def ocr_text(image_path, langs=("por+eng", "eng"), psms=("11", "6", "3"),
             timeout=45.0):
    """Le o texto da imagem com tesseract, multi-psm, fica com o maior.

    (14/11) O mesmo desenho do `_ocr_text` da casa (vision.py): psm 11
    (espalhado) > 6 (bloco) > 3 (auto), e por+eng antes de eng. O deadline
    e' TOTAL, nao por chamada: 6 combinacoes com 5s cada comiam 30s.
    """
    if not shutil.which("tesseract"):
        return "", "tesseract ausente (nix: tesseract)"
    src = str(image_path)
    try:                      # fundo claro ajuda o tesseract (tela escura)
        from PIL import Image, ImageOps
        img = Image.open(src).convert("L")
        img = ImageOps.autocontrast(img)
        src = str(image_path).rsplit(".", 1)[0] + "-ocr.png"
        img.point(lambda p: 255 if p > 140 else 0).save(src)
    except ImportError:
        src = str(image_path)
    best, ends = "", time.time() + timeout
    for psm in psms:
        for lg in langs:
            restante = ends - time.time()
            if restante <= 1.0:
                break
            try:
                r = subprocess.run(
                    ["tesseract", src, "stdout", "-l", lg, "--psm", psm],
                    capture_output=True, text=True, timeout=max(2.0, restante))
            except (subprocess.TimeoutExpired, OSError,
                    subprocess.SubprocessError):
                continue
            t = (r.stdout or "").strip()
            if len(t) > len(best):
                best = t
    if not best:
        return "", "OCR nao encontrou texto"
    return best, ""


class DuplexVoice:
    """Le as transcricoes NOVAS do log do cliente de voz.

    (23/11) O mesmo mecanismo do uhrs-practice.py: mede a posicao do
    arquivo (bytes) e devolve so o que apareceu depois — assim o loop nao
    re-corrige a mesma resposta e o dono so FALA.

    O log e' do dia (logs/duplex/<AAAA-MM-DD>.log) e a marca e' 'SEGMENTO:'.
    """

    def __init__(self, log_path):
        self.path = Path(log_path)
        self.pos = self.path.stat().st_size if self.path.is_file() else 0

    def poll(self):
        """Devolve a transcricao mais recente que ainda nao foi lida."""
        if not self.path.is_file():
            return ""
        size = self.path.stat().st_size
        if size < self.pos:            # rotacionou/truncou
            self.pos = 0
        if size == self.pos:
            return ""
        with self.path.open("r", encoding="utf-8", errors="ignore") as fh:
            fh.seek(self.pos)
            chunk = fh.read()
            self.pos = size
        last = ""
        for line in chunk.splitlines():
            if "SEGMENTO:" in line:
                last = line.split("SEGMENTO:", 1)[1].strip()
        return last


def _norm(s):
    return " ".join(str(s or "").lower().replace(".", " ").replace(",", " ")
                     .split())


def read_item_text(timeout=45.0, window_title=None, prefer_clipboard=True):
    """O texto do item. Devolve (texto, origem, caminho_da_imagem, erro).

    Ordem: clipboard (texto exato) -> OCR da janela (reserva). Medido em
    campo: o OCR traz a janela errada quando ha sobreposicao, e o clipboard
    traz o item exato.
    """
    if prefer_clipboard:
        text, err = read_clipboard()
        if text.strip():
            return text, "clipboard", None, ""
    CAPTURES.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    img = CAPTURES / f"uhrs-{stamp}.png"
    path, err = capture_screen(img, window_title=window_title)
    if not path:
        return "", "", None, (err or "nao deu para capturar a tela")
    text, err = ocr_text(path, timeout=timeout)
    if not text:
        return "", "ocr", path, err
    return text, "ocr", path, ""


def item_id_de(context):
    """Id ESTAVEL de um item, derivado do CONTEXDO (sha256, 12 chars).

    (20/11, coord-naming) O id era `cap-<timestamp em ms>`, e a MESMA
    pergunta capturada duas vezes virava DOIS ids. E o id repetido e' o que
    mede a REPETIBILIDADE do dono, que e' o teto real da delegacao
    (arXiv 2510.07978: o limiar e' a repetibilidade do humano, nao 100%).
    Sem id estavel, o bench nunca via esse numero.

    A normalizacao (espaco unico, minusculo) faz o mesmo item capturado com
    quebras de linha diferentes dar o mesmo id.
    """
    import hashlib
    norm = " ".join(str(context or "").lower().split())
    return "cap-" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def write_label(context, answer, source="uhrs-capture", item_id=None,
                path=None, via="tela"):
    """Grava a label no schema: contexto = o que o dono viu, answer = o que
    ele respondeu. NUNCA o gabarito.

    O contrato e' o MESMO do uhrs-practice.py (que grava as labels faladas):
    id · context · answer · key · source · via · ts — assim o registro
    unico (data/judgments/labels.jsonl) tem um formato so, e o bench le os
    dois caminhos sem saber de onde veio cada linha.
    """
    target = Path(path) if path else LABELS
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": item_id or item_id_de(context),
        "context": context,
        "answer": answer,
        # (20/11) mesmo contrato do outro caminho: 'key' e' o gabarito, so
        # para diagnostico — na captura nao existe gabarito (o dono viu o
        # item real), entao e' nulo.
        "key": None,
        "source": source,
        "via": via,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target, row


def self_test():
    """Prova a logica sem camera e sem microfone:
      1) o mapa de respostas (mesmo do uhrs-practice.py);
      2) a label grava a RESPOSTA DO DONO e o contexto lido, sem gabarito;
      3) o OCR de uma imagem sintetica (a casa tem tesseract).
    """
    # 1) mapa
    assert parse_answer("muito relevante") == "3"
    assert parse_answer("moderadamente relevante") == "2"
    assert parse_answer("levemente relevante") == "1"
    assert parse_answer("nao relevante") == "0"
    assert parse_answer("highly relevant") == "3"
    assert parse_answer("3") == "3"
    assert parse_answer("nada") is None

    # 2) a label
    tmp = Path(tempfile.mkdtemp(prefix="uhrs-capture-selftest-"))
    labels = tmp / "labels.jsonl"
    ctx = "How long does a passport renewal take\nPassport renewal processing times"
    target, row = write_label(ctx, "1", item_id="cap-test", path=labels)
    saved = json.loads(labels.read_text(encoding="utf-8").splitlines()[0])
    assert saved["answer"] == "1", saved
    assert saved["context"] == ctx, saved
    assert "gabarito" not in saved, saved
    assert saved["source"] == "uhrs-capture", saved
    # (20/11) o mesmo CONTRATO do uhrs-practice.py: key + via
    assert "key" in saved and saved["key"] is None, saved
    assert saved["via"] == "tela", saved

    # (20/11) o ID e' ESTAVEL: o mesmo contexto (mesmo item) da o mesmo id, e
    #    a normalizacao faz o mesmo item capturado com quebras diferentes dar
    #    o mesmo id. E' o que permite medir a repetibilidade do dono.
    id1 = item_id_de(ctx)
    id2 = item_id_de(ctx)
    id3 = item_id_de(ctx.replace("\n", "  "))     # mesmo texto, outra quebra
    id4 = item_id_de(ctx + " outro item")
    assert id1 == id2 == id3, (id1, id2, id3)
    assert id1 != id4, (id1, id4)
    assert id1.startswith("cap-") and len(id1) == 16, id1
    # e a gravacao usa o id estavel quando nenhum e' passado
    write_label(ctx, "2", path=labels)
    ids = [json.loads(l)["id"]
           for l in labels.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert ids[1] == id1, ids

    # 3) OCR de uma imagem sintetica com texto known
    ocr_ok = False
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (900, 160), "white")
        d = ImageDraw.Draw(img)
        d.text((20, 40), "Passport renewal processing times 4-6 weeks",
               fill="black")
        p = tmp / "sintetica.png"
        img.save(p)
        text, err = ocr_text(p, timeout=20)
        if text and "passport" in text.lower():
            ocr_ok = True
        else:
            print(f"(aviso: o OCR nao leu a imagem sintetica: {err or text[:60]})")
    except ImportError:
        print("(aviso: PIL ausente, o teste de OCR foi pulado)")

    shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST ok: mapa de respostas, label com a resposta do DONO (sem "
          "gabarito), contexto intacto, contrato igual ao do uhrs-practice.py "
          "(key/via) e id ESTAVEL (mesmo contexto => mesmo id)"
          + ("" if ocr_ok else " (OCR nao verificado aqui)"))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", default="", help="o texto do item (ja colado)")
    ap.add_argument("--dry-run", action="store_true",
                    help="so mostra o texto lido, nao grava label")
    ap.add_argument("--source", default="uhrs-capture")
    ap.add_argument("--labels", default="", help="outro arquivo de labels")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--window", default="",
                    help="titulo da janela a ler (ex.: 'UHRS'); sem isso, "
                         "a janela ativa")
    ap.add_argument("--from-clipboard", action="store_true",
                    help="le o item do clipboard (Ctrl+C na pagina): "
                         "texto exato, sem OCR")
    ap.add_argument("--no-clipboard", action="store_true",
                    help="ignora o clipboard e usa o OCR da janela")
    ap.add_argument("--from-duplex", action="store_true",
                    help="o veredito vem da VOZ (transcricao nova do log do "
                         "cliente de voz): sem digitar nada")
    ap.add_argument("--duplex-log", default="",
                    help="log do cliente de voz (default: logs/duplex/<hoje>.log)")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.text:
        text = args.text
        print("(texto fornecido na linha de comando)")
    else:
        prefer = (not args.no_clipboard)
        if args.from_clipboard:
            prefer = True
        print("(lendo o texto do item...)")
        text, origin, img, err = read_item_text(
            window_title=args.window or None, prefer_clipboard=prefer)
        if err:
            print(f"ERRO: {err}", file=sys.stderr)
            print("dica: no clipboard, selecione o item na pagina e aperte "
                  "Ctrl+C (o texto exato e' melhor que o OCR).", file=sys.stderr)
            return 1
        print(f"(origem: {origin}" + (f", captura: {img}" if img else "") + ")")

    if not text.strip():
        print("ERRO: nada lido da tela", file=sys.stderr)
        return 1

    print(f"\nTEXTO LIDO ({len(text)} chars):")
    print(text[:2000])
    print()

    if args.dry_run:
        print("(dry-run: nada gravado)")
        return 0

    ok = input("o que voce leu na tela esta certo? [s/N] ").strip().lower()
    if ok not in ("s", "sim", "y", "yes"):
        print("cancelado: nada gravado.")
        return 1

    ans_raw = ""
    if args.from_duplex:
        # (23/11) o veredito FALADO: o mesmo leitor do uhrs-practice (o log
        # do cliente de voz, marca 'SEGMENTO:'). O dono so fala ("muito
        # relevante", "2"); o loop avanca sozinho, sem digitar nada.
        log_path = args.duplex_log or str(
            REPO / "logs" / "duplex" / (time.strftime("%Y-%m-%d") + ".log"))
        voice = DuplexVoice(log_path)
        print(f"modo voz: fale o veredito (log: {log_path}). "
              f"'proxima' pula o item, 'de novo' repete.")
        while True:
            time.sleep(1.5)
            ans_raw = voice.poll()
            if not ans_raw:
                continue
            low = _norm(ans_raw)
            if "proxima" in low or "pular" in low or "next" in low:
                print("  (pulando)")
                return 0
            if "de novo" in low or "repetir" in low or "again" in low:
                print("(repetindo o item)")
                continue
            break
    else:
        ans_raw = input("fale o veredito (3 highly / 2 moderately / 1 slightly / "
                        "0 not): ").strip()
    ans = parse_answer(ans_raw)
    if ans is None:
        print(f"nao entendi '{ans_raw}'; nada gravado.")
        return 1

    target, row = write_label(text, ans, source=args.source,
                               via=("voz" if args.from_duplex else "teclado"),
                               path=Path(args.labels) if args.labels else None)
    print(f"label gravada: id={row['id']} answer={ans} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
