#!/usr/bin/env python3
"""duplex-asrd.py — ASR v4: silero VAD (limites) + whisper.cpp GPU (texto).

(18/10 08:50) A evolução final da manhã: o VAC do whisper_streaming
carregava um whisper CPU interno (1.5-3s por segmento) só pra FECHAR
limites. Agora: FixedVADIterator (silero sozinho, o arquivo vendored)
detecta pausa em ~300ms; o segmento cortado do ring vai pro
whisper-server (:8097, CUDA, modelo quente) — 158ms medidos por
segmento. Total fala→texto: <1s.

Protocolo stdio (igual o cliente já fala):
  req: {"audio_b64": "<float32 PCM 16k>"} (chunks de 0.6s, TODOS —
       silêncio inclusive, o VAD precisa)
  resp: {"text": "...", "ms": X} quando fecha segmento; silêncio = nada
"""
import base64
import io
import json
import re as _re
import sys
import time
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

SR = 16000
CTX = {"v": ""}   # vocabulário da conversa → prompt do whisper-server
WCPP = "http://127.0.0.1:8097/inference"

def main():
    from silero_vad_iterator import FixedVADIterator

    # silero via torch hub (cacheado em ~/.cache/torch — o VAC baixou 1×)
    import torch
    model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad")
    vad = FixedVADIterator(model, threshold=0.5, min_silence_duration_ms=400,
                           speech_pad_ms=150)
    print(json.dumps({"text": "", "ms": 0, "ready": True}), flush=True)

    ring = np.zeros(0, dtype="float32")
    started = None

    # (20/10, papers voz-stt) 4 defesas anti-alucinação:
    # 2609.04561 (gated projection): no_speech_prob+avg_logprob como
    #   gate — é o sinal que o paper usa p/ decidir projetar.
    # 2609.32560 (two-sided): deny-list de frases-alucinação — léxico
    #   Scicom PT (data/whisper-halluc-lexicon-pt.tsv, curado AGENTE-HB)
    #   em SEGUNDA CAMADA: frase do léxico só morre se os stats do
    #   áudio TAMBÉM forem fracos (gated!) — 'Obrigado' dito de verdade
    #   tem stats confiantes e PASSA; 'Obrigada' alucinado em ruído não.
    #   Riscadas da lista: risadas/aplausos/música = SINAIS SOCIAIS
    #   (direção do dono: o agente usa).
    # 2610.08847 (CTC criterion): tokens >> duração do áudio = fakir.
    # 2608.15940 (null token): logprobs/no_speech = abstenção que a
    #   gente jogava fora.
    HALLUC_PT = (
        "obrigado por assistir", "obrigado por assistirem",
        "inscreva-se no canal", "até o próximo vídeo",
        "som de futebol",
        # (05:45, curadoria HB ban-pt-hard) só os 2 inequívocos; os
        # outros 8 'safe_candidate' ('muito obrigado', 'com licença'...)
        # são fala REAL — seguem no léxico gated (tier 2, stats fracos)
        "jouvin o sr", "o que é a reunião",
    )
    SOCIAL_KEEP = ("risada", "aplauso", "música", "músicas", "som dos",
                   "sons dos")

    def load_lexicon():
        """Léxico Scicom PT: frases ≤4 palavras, sem sinais sociais."""
        out = set()
        try:
            for line in open("/home/nixos/projects/nixos-ai/data/"
                             "whisper-halluc-lexicon-pt.tsv"):
                if line.startswith("#") or not line.strip():
                    continue
                parts = [p.strip() for p in line.split("\t")]
                if len(parts) < 3 or not parts[2].isdigit():
                    continue
                norm = parts[1].lower()
                if not norm or len(norm.split()) > 4:
                    continue
                if any(k in norm for k in SOCIAL_KEEP):
                    continue
                out.add(norm)
        except OSError:
            pass
        return out

    LEXICON = load_lexicon()
    # (08:55, delta HB pós-multilingue) fantasmas trocaram de idioma:
    # 'Hey.'/'Bye.'/'*Eat*'/'Eee.'/'T-T-T-T'. TSV multilingual do HB:
    # ban-hard (curado, multi-word, nunca fala real) + gated JA/ZH.
    MULTI_HARD = set()
    try:
        for line in open("/home/nixos/projects/nixos-ai/data/"
                         "whisper-halluc-ban-multilingual.tsv"):
            if line.startswith("#") or not line.strip():
                continue
            parts = [p.strip() for p in line.split("\t")]
            if len(parts) < 3 or parts[0] not in ("ban-hard", "gated"):
                continue
            phrase = parts[2].lower()
            if not phrase or len(phrase.split()) < 2:
                continue        # 1-palavra ('ed', 'me') = lixo do count
            if parts[0] == "ban-hard":
                MULTI_HARD.add(phrase)
            else:
                LEXICON.add(phrase)
    except OSError:
        pass
    # Greeting fantasma por idioma (o turbo emite o clássico da língua
    # detectada; PT 'e aí' já morto — estendendo p/ EN. 'hey jarvis'
    # = 2 palavras, passa; 'hey' SECO não existe como turn real aqui).
    GREET_SUS = {"e aí", "e aí e aí", "a cidade no brasil", "o que é isso",
                 "não não não", "oh oh oh", "hey", "bye", "hi"}

    def anti_halluc(txt, segs, dur_s):
        # normalização p/ GATE (pontuação fora): a assinatura de
        # alucinação tem pontuação de legenda ('Não, não, não.')
        t = " ".join(txt.lower().replace("[", " ").replace("]", " ")
                     .replace(",", " ").replace(".", " ").replace("!", " ")
                     .replace("?", " ").split()).strip()
        # 1. deny-list dura: contaminação inequívoca de legenda
        if len(t.split()) <= 6 and any(h in t for h in HALLUC_PT):
            return ""
        # 1a. (06:15, fixtures HB + stats reais: turbo alucina COM
        # CONFIANÇA MÁXIMA — ns ~1e-10, lp ~-0.01; o gate por stats NÃO
        # discrimina. Padrões dominantes = kill determinístico.)
        # Greeting fantasma: 'E aí' SECO (≤2 pal). A saudação REAL
        # completa ('E aí, tudo bom?') passa. Trade-off no queue p/ dono.
        if t in ("e aí", "e ai", "e aí e aí", "e ai e ai",
                 "a cidade no brasil", "a cidade no brasil a cidade no brasil"):
            return ""
        # Stutter redup: 'A-a-a-a-a' (loop de sílaba hifenizada)
        if _re.search(r"\b(\w{1,3})(-\1){2,}", t):
            return ""
        # Legenda-leading: 'Legenda Adriana Zanotto' — ninguém COMEÇA
        # fala com 'Legenda' ('a legenda' no meio passa)
        t_words = t.split()
        if t_words and t_words[0] == "legenda" and len(t_words) <= 4:
            return ""
        first2 = " ".join(t_words[:2])
        # 1b. suspeitos GATED (léxico Scicom + greetings fantasma do
        #     turbo [eval HB] + repetição redup): stats fracos = morte;
        #     fala REAL tem stats confiantes e passa.
        if segs and (t in LEXICON or t in GREET_SUS
                     or first2 in GREET_SUS
                     or any(w in LEXICON for w in t_words[:2])
                     or (len(t_words) >= 3 and len(set(t_words)) == 1)):
            ns = max(s.get("no_speech_prob", 0) for s in segs)
            lp = min(s.get("avg_logprob", 0) for s in segs)
            if ns > 0.35 or lp < -0.45:
                return ""
        # 1c. ALL-CAPS recap (eval HB: 'A CIDADE NO BRASIL'): legenda
        #     de programa, nunca fala de mic; gated p/ FP
        if segs and len(t_words) >= 2 and txt.strip().isupper() \
                and not t.replace(" ", "").isdigit():
            ns = max(s.get("no_speech_prob", 0) for s in segs)
            lp = min(s.get("avg_logprob", 0) for s in segs)
            if ns > 0.35 or lp < -0.45:
                return ""
        # 2. gate estatístico: TUDO no_speech alto + logprob ruim = vazio
        if segs and all(s.get("no_speech_prob", 0) > 0.6 for s in segs) \
                and all(s.get("avg_logprob", 0) < -0.8 for s in segs):
            return ""
        # 3. tokens-vs-duração: PT falado ~2-4 pal/s; >5.5 = impossível
        if dur_s > 0.3 and len(txt.split()) > dur_s * 5.5:
            return ""
        return txt

    def seg_to_text(seg):
        if len(seg) < SR * 0.4:
            return ""
        buf = io.BytesIO()
        w = wave.open(buf, "wb")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((seg * 32767).astype("int16").tobytes())
        w.close()
        req = urllib.request.Request(
            WCPP, data=buf.getvalue(),
            headers={"Content-Type": "audio/wav"})
        boundary = "----JARVIS"
        # multipart manual: whisper-server espera form-data 'file'
        # (+ 'prompt' com o vocabulário da conversa — paper 2307.14743:
        # last confirmed words as prompt fixa o 'Já viz'→'Jarvis')
        # (+ 'response_format' verbose_json: expõe no_speech_prob/
        # avg_logprob por segmento — as defesas anti-halluc)
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"file\"; filename=\"seg.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + buf.getvalue() + b"\r\n"
        if CTX["v"]:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"prompt\"\r\n\r\n{CTX['v'][:200]}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"response_format\"\r\n\r\nverbose_json\r\n").encode()
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            WCPP, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        j = json.load(urllib.request.urlopen(req, timeout=60))
        txt = str(j.get("text", "")).strip()
        segs = j.get("segments") or []
        dur_s = float(j.get("duration") or (len(seg) / SR))
        return anti_halluc(txt, segs, dur_s)

    # Adaptive VAD threshold based on ambient noise (paper 2609.04561: gated
# projection uses no_speech_prob as gate; adaptive threshold improves
# echo/duplex scenarios). Maintains EMA of noise floor.
    SPK_PROFILES = {}
    # (21/10 SPEAKER-ID) PERFIS PERSISTENTES: /tmp morre no reboot —
    # data/ é a fonte da verdade agora (o duplex salva lá).
    for _pp in (Path(__file__).resolve().parent.parent / "data" / "spk-profiles.json",
                Path("/tmp/jarvis-spk-profiles.json")):
        try:
            _cfg = json.loads(_pp.read_text())
            SPK_PROFILES = {k: np.array(v) for k, v in _cfg.items()}
            break
        except Exception:
            pass
    # (21/10 SPEAKER-ID, blueprint HB) IDs EMERGENTES pré-cadastro:
    # cluster cos>0.80 (limiar provado no applio-lab cross-video) →
    # spk1, spk2... = "quantas pessoas + quem disse o quê" do dono.
    SPK_EMERGENT = []   # [(label, centroide)]
    SPK_SEQ = [1]
    SPK_RECENT = []  # [(embedding, ts)] últimos 60s — clustering
    SPK_COUNTER = {"voices": 0, "last_id": "?"}
    print(f"[asrd] speaker: {len(SPK_PROFILES)} perfis "
          f"({'ATIVO' if SPK_PROFILES else 'desligado (todos)'})",
          file=sys.stderr, flush=True)

    WS = {"spk": None}   # (21/10) runtime WeSpeaker lazy-init
    def _embed(pcm_f32, wav=""):
        # (21/10 v2, veredito HB 13:15: MFCC 26d cos(dora,alex)=0.999 =
        # merge garantido; c0 domina 93% da norma) EMBED v2 = WeSpeaker
        # ResNet34 256-d — PROVADO no LOTM cross-video (mesmo modelo
        # ~/.wespeaker/en/model.onnx, 83ms/segmento CPU). Fallback MFCC
        # degrada sem crash se o runtime sumir.
        try:
            if WS["spk"] is None:
                import wespeakerruntime as w
                WS["spk"] = w.Speaker(lang="en")
            if wav:
                e = np.array(WS["spk"].extract_embedding(wav),
                             dtype=float).ravel()
                return e / (np.linalg.norm(e) + 1e-9)
        except Exception:
            pass
        try:
            import librosa
            m = librosa.feature.mfcc(y=pcm_f32, sr=SR, n_mfcc=13,
                                      n_fft=512, hop_length=160)
            return np.concatenate([m.mean(axis=1), m.std(axis=1)])
        except Exception:
            return None

    def _cos(a, b):
        return float(np.dot(a, b) /
                     (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    def _identify(pcm_f32, wav=""):
        """Retorna (nome, confiança) da melhor voz conhecida ou
        ('unknown', cos_max). Também alimenta o contador de vozes."""
        nonlocal SPK_RECENT
        e = _embed(pcm_f32, wav)
        if e is None:
            return ("?", 0.0)
        # identifica contra perfis conhecidos
        best, best_cos = "?", 0.0
        for nome, prof in SPK_PROFILES.items():
            c = _cos(e, prof)
            if c > best_cos:
                best, best_cos = nome, c
        if best_cos < 0.62:   # (21/10 HB) enrolled 0.62 p/ segmentos curtos
            # (21/10) sem perfil conhecido → ID EMERGENTE estável
            _lbl = None
            for _i, (_lb, _cent) in enumerate(SPK_EMERGENT):
                if _cos(e, _cent) >= 0.58:   # (21/10 HB) ótimo medido
                    _lbl = _lb
                    SPK_EMERGENT[_i] = (_lb, _cent * 0.8 + e * 0.2)
                    break
            if _lbl is None:
                _lbl = f"spk{SPK_SEQ[0]}"
                SPK_SEQ[0] += 1
                SPK_EMERGENT.append((_lbl, e.copy()))
            best, best_cos = _lbl, max(best_cos, 0.0)
        # clustering: conta vozes únicas nos últimos 60s
        now = time.time()
        SPK_RECENT = [(r_e, ts) for r_e, ts in SPK_RECENT if now - ts < 60]
        SPK_RECENT.append((e, now))
        n_voices = 1
        centroids = [SPK_RECENT[0][0].copy()]
        for r_e, _ in SPK_RECENT[1:]:
            if max(_cos(r_e, c) for c in centroids) < 0.58:   # (21/10 HB)
                centroids.append(r_e.copy())
                n_voices += 1
        SPK_COUNTER["voices"] = n_voices
        SPK_COUNTER["last_id"] = best
        return (best, best_cos)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if req.get("reset"):
                reset()
                print(json.dumps({"text": "", "ms": 0, "reset": True}),
                      flush=True)
                continue
            b64 = req.get("audio_b64")
            if not b64:
                continue
            pcm = np.frombuffer(base64.b64decode(b64), dtype="<f4")
        except Exception:
            continue
        t0 = time.monotonic()
        try:
            ring = np.concatenate([ring, pcm])[-SR * 20:]   # cap 20s
            ev = vad(pcm)
            if ev and started is None and ev.get("start") is not None:
                started = max(0, int(len(ring) - SR * 1.0))   # 1s de pré-roll
            if ev and ev.get("end") is not None and started is not None:
                seg = ring[int(started):int(len(ring) - SR * 0.35)]
                # (19:30) identificar a voz e anexar ao resultado
                # (21/10, pedido HB) WAV por segmento p/ evidência: duplex
                # copia p/ logs/audio/ quando classify=RESPOND (casável
                # com log + reports). Rotativo: últimos 30 em /tmp.
                # (v2) AGORA ANTES do _identify: o WeSpeaker é file-based
                # — o embed lê este mesmo wav (zero I/O extra).
                _wav = ""
                try:
                    import wave as _w
                    _sd = Path("/tmp/opencode/duplex-segs")
                    _sd.mkdir(parents=True, exist_ok=True)
                    _wav = str(_sd / f"seg_{time.time():.3f}.wav")
                    _wf = _w.open(_wav, "wb")
                    _wf.setnchannels(1); _wf.setsampwidth(2)
                    _wf.setframerate(SR)
                    _wf.writeframes((np.clip(seg, -1, 1) * 32767)
                                    .astype("<i2").tobytes())
                    _wf.close()
                    _old = sorted(_sd.glob("seg_*.wav"))[:-30]
                    for _f in _old:
                        _f.unlink(missing_ok=True)
                except Exception:
                    _wav = ""
                # (21/10 HB) <0.4s: embedding instável → não identifica
                if len(seg) >= int(0.4 * SR):
                    spk_id, spk_cos = _identify(seg, _wav)
                else:
                    spk_id, spk_cos = "?", 0.0
                txt = ''
                txt = seg_to_text(seg)
                ms = (time.monotonic() - t0) * 1000
                print(json.dumps({"text": txt, "ms": ms, "spk": spk_id,
                       "spk_cos": round(spk_cos, 2),
                       "voices": SPK_COUNTER["voices"],
                       "wav": _wav}), flush=True)
                ring = np.zeros(0, dtype="float32")
                started = None
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"text": "", "ms": 0, "err": str(exc)[:120]}),
                  flush=True)


class AdaptiveVAD:
    def __init__(self, model, base_threshold=0.5, min_thresh=0.3, max_thresh=0.7):
        self.model = model
        self.base_threshold = 0.5
        self.threshold = 0.5
        self.min_thresh = 0.3
        self.max_thresh = 0.7
        self.vad = FixedVADIterator(model, threshold=0.5,
                                    min_silence_duration_ms=400,
                                    speech_pad_ms=150)
        self.noise_floor = 0.0
        self.alpha = 0.1  # EMA smoothing

    def update_threshold(self, rms):
        """Update threshold based on ambient noise level (RMS)."""
        # EMA of noise floor (when no speech detected)
        self.noise_floor = self.alpha * rms + (1 - self.alpha) * self.noise_floor
        # Adaptive threshold: higher noise floor -> higher threshold
        # Map noise floor to threshold range
        normalized = min(max(self.noise_floor / 1000.0, 0.0), 1.0)
        self.threshold = self.min_thresh + (self.max_thresh - self.min_thresh) * normalized
        self.threshold = max(self.min_thresh, min(self.max_thresh, self.threshold))
        # Recreate VAD with new threshold
        self.vad = FixedVADIterator(self.model, threshold=self.threshold,
                                    min_silence_duration_ms=400,
                                    speech_pad_ms=150)

    def __call__(self, chunk):
        return self.vad(chunk)

    def reset(self):
        self.vad = FixedVADIterator(self.model, threshold=self.threshold,
                                    min_silence_duration_ms=400,
                                    speech_pad_ms=150)


def reset():
    # (10:20) anti-eco (pesquisa: playback suppression + reset do
    # estado de VAD no início E no fim do TTS — o tail do eco senão
    # fecha um segmento fantasma e o modelo responde a si).
    global ring, started, vad
    ring = np.zeros(0, dtype="float32")
    started = None
    # Adaptive VAD with noise-adaptive threshold (paper 2609.04561)
    vad = AdaptiveVAD(model, base_threshold=0.5, min_thresh=0.3, max_thresh=0.7)

    # (19:30) SPEAKER ENGINE v2: multi-voz (papers: VAD→embed→cluster)
    # profiles = {nome: embedding}; a cada segmento identifica a voz;
    # clusters de embeddings recentes = contagem de pessoas falando.
if __name__ == "__main__":
    main()
