# Auditoria 03/11/2026 — GATE do duplex + Laya fine-tuned

Duas perguntas do dono:
1. *"o gate on do duplex faz o jarvis ignorar quase tudo e raramente ele responde"*
2. *"também precisamos testar o Laya que foi fine-tuned pra ele usar"*

Resposta curta: o gate atual é um **heurístico de string** que exige a palavra
"Jarvis" — recall de **15,4%** (11 de 13 pedidos legítimos descartados). A
Laya fine-tuned **funciona** (acc 83,3% vs 33,3% do regex) e está no closure do
pacote, mas é o classificador de **dificuldade** (qual tier atende), não o
gate de endereçamento — e o classificador semântico que serviria ao gate
(`classify_intent`, GBNF) **existe no código e nunca é chamado**.

Reprodução: `benchmarks/voice/bench_gate.py` e `benchmarks/laya/bench_laya.py`
(importam o código real do duplex e o Laya de produção — nada reimplementado).

---

## 1. O gate: por que o JARVIS ignora quase tudo

### 1.1 O caminho real (scripts/duplex-voice.py)

```
STT → classify_turn()  [LoRA micro-turn, 4B:8092]  → RESPOND/WAIT/SILENCE/BARGE
        ↓ se RESPOND
     GATE_MODE=="on" and not _addressed(heard)  →  DESCARTA (linha 2160)
        ↓
     _addressed()  (linha 247) = "jarvis" (fuzzy difflib ≥ 0,62)  e NADA MAIS
```

`_addressed` hoje (linhas 247-256):

```python
tl = txt.lower()
if "jarvis" in tl:
    return True
return any(difflib.SequenceMatcher(None, w, "jarvis").ratio() >= 0.62
           for w in tl.replace(",", " ").split())
```

O comentário no arquivo conta a regressão: em 10/55 a TV disse *"where's the
one?"* e o JARVIS respondeu → tiraram o "?" como gatilho → sobrou **só
"Jarvis"**. O preço: todo pedido falado sem a palavra-mágica morre.

`classify_intent()` (linha 304, 4B + GBNF, ~400 ms) classifica
QUESTION/COMMAND/MUTE/UNMUTE/STOP/BACKCHANNEL/SOCIAL/NONE — está **pronto e
morto**: nenhuma call site no arquivo (`rg classify_intent` → só a def).

### 1.2 Medição (n=27, PT-BR de voz, código real)

Dataset: 13 falas do dono que merecem resposta (12 **sem** a palavra "Jarvis"),
11 de TV/sala/backchannel, 3 frases incompletas (WAIT).

| gate | TP | FN | FP | precision | recall | F1 |
|---|---|---|---|---|---|---|
| `_addressed` (atual, GATE_MODE=on) | 2 | **11** | 0 | 1,000 | **0,154** | 0,267 |
| `classify_turn` == RESPOND (LoRA) | 13 | 0 | 7 | 0,650 | 1,000 | 0,788 |
| `classify_intent` ∈ {QUESTION, COMMAND} | 12 | 1 | 3 | 0,800 | 0,923 | 0,857 |
| addr **OR** intent | 12 | 1 | 3 | 0,800 | 0,923 | 0,857 |
| LoRA **AND** (addr OR intent) | 12 | 1 | **2** | **0,857** | **0,923** | **0,889** |

Leitura:
- **o gate atual perde 11/13 pedidos do dono** (recall 15,4%) → é exatamente
  o sintoma reportado ("ignora quase tudo, raramente responde");
- o LoRA sozinho é **permissivo demais** (7 FP: TV, auto-fala, "obrigado");
- o classificador de intenção é o melhor sinal único (F1 0,857) e **custa
  ~400 ms**;
- a combinação LoRA AND (addr OR intent) chega a **F1 0,889** com recall 92,3%.

FP que sobram (2): *"where's the one?"* (TV) e *"vamos embora"* (auto-fala) —
os dois são falas completas sem "Jarvis" → o conserto definitivo é o **gate de
áudio** (wakeword recalibrado, pendência 4 ainda aberta), não mais heurística
de string.

### 1.3 Latência (4B:8092, aquecido)

| chamada | mean | max |
|---|---|---|
| `classify_turn` (LoRA, + toggle /lora-adapters) | 348 ms | 389 ms |
| `classify_intent` (GBNF) | 398 ms | 416 ms |

Sequencial = 746 ms por segmento (apertado contra o merge deadline de 1,5 s).
**Em paralelo (thread) = max(348, 398) ≈ 400 ms** → o custo real do gate
semântico é ~+50 ms sobre o LoRA, não o dobro.

### 1.4 Proposta de patch (para quem owns `scripts/duplex-voice.py`)

```python
# 1) gate semântico: o "Jarvis" deixa de ser obrigatório
def _addressed(txt, intent=None):
    tl = txt.lower()
    if "jarvis" in tl:
        return True
    import difflib as _dl
    if any(_dl.SequenceMatcher(None, w, "jarvis").ratio() >= 0.62
           for w in tl.replace(",", " ").split()):
        return True
    return intent in ("QUESTION", "COMMAND")     # ← o que faltava

# 2) chamar o classificador de intenção EM PARALELO com o LoRA
lab, intent = _classify_parallel(base, heard)   # threads: LoRA + GBNF

# 3) usar no ponto do gate (linha ~2160)
if GATE_MODE == "on" and not _addressed(heard, intent):
    ...ignora...
```

Ordem de implantação sugerida (medida, do menor para o maior risco):
1. `_addressed OR intent` — recall 15,4% → 92,3% com 1 FN e 3 FP;
2. LoRA AND (addr OR intent) — F1 0,889, F1 mais alto;
3. **depois**: wakeword/áudio como gate primário (pend. 4) para matar os 2 FP
   restantes — sem heurística de string.

Fallback: se o `classify_intent` falhar (None), o comportamento é o de
hoje (gate antigo) → nunca piora o que já funciona.

---

## 2. Laya fine-tuned: teste do modelo

### 2.1 O que é

`~/models/laya-ft/` — `model.onnx` (1,6 GB, ModernBERT-large 421M),
`tokenizer/`, `rl_agent_config.json` (`model_name: laya-jarvis-difficulty`,
`fine_tuned: true`, 7313 updates, 1,96 h de treino). Fine-tune de
**dificuldade** (`simple|moderate|hard`) — usado por
`core/model_policy.py:classify_difficulty` (Laya primário, regex fallback) para
escolher o tier do LLM. **Não é** o gate de endereçamento.

### 2.2 Medição (dataset PT-BR de voz, 24 exemplos, 8 por classe)

```
LAYA_BENCH n=24 acc=0.833 macro_f1=0.822 regex_acc=0.333 agree=0.5 none=0
             load=3.02s ms(mean/p95/max)=149.9/165.7/166.5
  simple    acc=1.000 p=0.667 r=1.000 f1=0.800
  moderate  acc=0.500 p=1.000 r=0.500 f1=0.667
  hard      acc=1.000 p=1.000 r=1.000 f1=1.000
```

- **acc 83,3% / macro-F1 0,822** — bate o card do checkpoint (95,6% no
  dataset de treino, 83,3% em PT-BR de voz: a diferença é a língua e o
  estilo falado);
- o **regex fallback acerta 33,3%** → a Laya vale 2,5× o fallback ✓;
- latência: **150 ms mean / 166 ms p95** (CPU, load 3,0 s a frio) → cabe no
  caminho de decisão do LLM, **mas** somada ao classificador de turno/inteção
  (348+398 ms) já estoura o merge deadline de 1,5 s → a Laya deve ficar no
  **roteamento do chat** (onde já está), não no hot path do gate de voz;
- classe `moderate` tem recall 50% (precision 100%): quando a Laya diz
  "moderate" ela acerta, mas erra many → "simple"/"hard"; no 3 tiers
  (bonsai/forte/nuvem) o efeito prático é rotear "moderate" para o tier
  errado às vezes — para o caso de uso (routing) é aceitável, para gate não.

### 2.3 Fragilidade encontrada (e corrigida)

`onnxruntime` chegava ao pacote só **por acaso** (fechamento do
faster-whisper); `core/laya_classifier.py` engole a exceção e devolve `None`
→ a Laya cairia no regex **em silêncio** se o faster-whisper mudasse. Agora
`onnxruntime` é dependência **explícita** de `modules/ai/package.nix` ✓
(sem download novo: o store path já estava no closure).

Também: a Laya só funciona no ambiente do pacote (`jarvis-env.sh` → PYTHONPATH
com 195 paths). Rodando com o `python3` do sistema ela nem carrega
(`LAYA INDISPONIVEL`) — por isso os benches usam `"$JARVIS_PY"`.

---

## 3. Veredito

| pergunta | resposta |
|---|---|
| por que ignora quase tudo? | `_addressed` exige "Jarvis" → recall 15,4% (medido) |
| a Laya serve de gate? | não — ela classifica **dificuldade**; o gate semântico que falta é `classify_intent` (morto no código) |
| a Laya fine-tuned está boa? | sim: acc 83,3% (regex 33,3%), 150 ms CPU — já está no caminho de routing |
| próximo passo | aplicar §1.4 (gate semântico, LoRA+intent em paralelo) e depois o gate de áudio (pend. 4) |

Reproduzir:
```bash
. modules/ai/jarvis/jarvis-env.sh
"$JARVIS_PY" benchmarks/voice/bench_gate.py --base http://127.0.0.1:8092
"$JARVIS_PY" benchmarks/laya/bench_laya.py
```
