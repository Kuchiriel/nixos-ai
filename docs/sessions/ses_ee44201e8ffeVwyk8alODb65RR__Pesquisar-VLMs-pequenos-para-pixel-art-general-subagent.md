# Pesquisar VLMs pequenos para pixel art (@general subagent)

- **sessão:** `ses_ee44201e8ffeVwyk8alODb65RR`
- **quando:** 2026-10-08 13:39 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 19 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Preciso de uma pesquisa técnica focada em modelos de visão-linguagem (VLM) PEQUENOS para uma tarefa específica e difícil.

CONTEXTO DA TAREFA REAL (medido, não Suppõe):
- Classificar sprites de videogame 32x32 pixels (Tibia 13.x / OpenTibiaBR), arte pixelada MUITO pequena.
- Hardware: RTX 4050 Laptop, apenas 6 GB de VRAM total (já com outros LLM ocupando ~3.2 GB).
- O que já foi medido no host:
  - Moondream2 (1.86B, F16 3.5GB, rodando em transformers na rev 2024-08-26): acerta MATERIAL/COR das bordas (~60%), erra TODO detalhe de forma (0%). Cruzamento com medição de pixel: 52% concorda material.
  - SigLIP base-patch16-224 (775MB): carrega mas escores ±0.02, não discrimina.
  - Q8 do Moondream via llama.cpp: DEGENERADO (dá resposta errada em factual simples).
- Pergunta real do dono: "pesquisar slp/moondream/llava e outros vlms, tem uns que são bem pequenos 1gb e dizem que é bom, pra ver se os benchs dizem algo sobre imagem pequena, velocidade ou no geral mesmo. Às vezes só estamos usando o modelo errado."

O QUE PRECISO QUE VOCÊ PESQUISE E ME ENTREGUE:

1. **Candidatos VLM pequenos viáveis em 6 GB VRAM** (idealmente <2 GB, GGUF ou safetensors). Considere explicitamente: SmolVLM / SmolVLM2 / SmolVLM3, InternVL3-1B, MiniCPM-V 2.0/2.5/2.6, Moondream2/3, LLaVA-1.5/1.6/NeXT em tamanhos pequenos, Qwen2.5-VL-3B, Qwen3-VL-2B, Florence-2, PaliGemma, moondream na versao nova (vikhyatk/moondream2 "2024-08-26" e superiores), TinyLLaVA, PaliGemma2, e qualquer outro que pareça relevante para pixel art.

2. **BENCHMARKS que digam algo sobre IMAGEM PEQUENA / LOW-RES / pixel art.** Isto é o ponto central: procurar especificamente por avaliação em tarefas de imagem pequena, thumbnail, sprite, game asset, "low resolution", "small object", SVG/pixel art, e benchmarks de contagem/localização de objeto pequeno. Se algum paper/report menciona degradação em baixa resolução ou diz explicitamente que funciona bem em sprites/pixel art, isso é OURO — cite.

3. **Eficiência medida**: velocidade (tokens/s ou imagens/s), VRAM em bf16/fp16, e se existe suporte oficial a llama.cpp (GGUF) e/ou transformers.

4. **Uma recomendação final ranqueada**: qual(is) modelo(s) vale testar AGORA neste hardware para esta tarefa específica, com o porquê. Seja honesto se a resposta for "nenhum é bom para 32x32 pixel art e o gargalo é a tarefa, não o modelo".

REGRAS:
- Cite URLs. Distinga fato medido de paper de opinião de forum/blog.
- Se um benchmark não cobre pixel art, diga isso explicitamente — não invente cobertura.
- Priorize informação de 2025-2026.
- NÃO recomende modelo que não caiba em 6 GB VRAM junto com um LLM de texto já residente.

Entregue em português, texto corrido e tabelas, sem enrolação. Máximo ~800 palavras.

---

## · ?

I'll research this. Starting with a batch of targeted searches.

---

## · ?

Good hits. Now targeting pixel art/sprite benchmarks and efficiency data.

---

## · ?

FineSightBench is exactly the gold source. Let me extract model-level numbers from it.

---

## · ?

GameTileNet is the key find. Extracting its VLM-vs-CNN comparison.

---

## · ?

##1. O que os benchmarks dizem sobre imagem pequena

**FineSightBench** ([arXiv 2606.07861](https://arxiv.org/html/2606.07861v1), jun/2026) é o benchmark mais direto que existe hoje: canvas 448×448, alvo em 4/8/12/16/24/32/**48 px**, perception vs. reasoning, 21 modelos. **Não contém pixel art** — são letras, formas, animais e color blocks sintéticos. Resultado medido:

| Modelo | AUC-size ↑ | RT₅₀ (px, menor melhor) | Halluc@4px |
|---|---|---|---|
| Gemma-4-31B | 78.8 | **7.3** | 13.4 |
| Qwen3-VL-4B | 65.8 | 21.3 | 5.0 |
| InternVL3.5-2B | 60.1 | 22.0 | 0.0 |
| **Qwen3-VL-2B** | **60.0** | 24.8 | 0.0 |
| Gemma-4-E2B | 59.2 | 22.9 | 0.0 |
| **InternVL3.5-1B** | **55.0** | 22.8 | 0.0 |

Achado central: *perception satura em ~12 px*. Taxa de misclassification por tamanho: 22.9% @4px → 6.4% @12px → 2.1% @24px → 0.6% @48px. **Modelos de 1–2B precisam de alvo ≥22 px para 50% de acerto — 3× pior que o frontier (7.3 px).** Isso é medida, não opinião.

Complementares: **RC-Bench** ([arXiv 2506.12776](https://arxiv.org/html/2506.12776v1)) mostra que分辨率 alta só ajuda tarefas *resolution-centric* (OCR, chart) — MMStar/MMBench são *semantic-centric* e ficam cegos a detalhe fino. Ou seja: benchmark "geral" não mede sua tarefa. **InspectVLM** ([ICCVW 2025](https://www.openaccess.thecvf.com/content/ICCV2025W/VISION'25/papers/Wallace_InspectVLM_Unified_in_Theory_Unreliable_in_Practice_ICCVW_2025_paper.pdf)) mediu Florence-2 (VLM minúscula)_vs. Faster R-CNN em inspeção: "lacks the resolution to localize small cracks", bbox muito pior — detector pequeno bate VLM.

**O paper mais relevante é GameTileNet** ([arXiv 2507.02941](https://arxiv.org/html/2507.02941), tiles32×32 de OpenGameArt, CC). Mediu **exatamente** sua tarefa:

| Método (32×32 tiles) | Resultado |
|---|---|
| **CLIP ViT-B/32 + MLP** (fine-tuned) | micro-F1 **0.92**, macro-F1 0.86; Characters 0.98, Items 0.95, Terrain 0.92 |
| **ResNet18 fine-tuned** (64×64) | **92.2%** acc |
| YOLOv5s (COCO) | **0 matches** com os labels |
| BLIP (VLM zero-shot) | só alinhamento *aproximado*; **upscaling (Real-ESRGAN/SwinIR) melhora o match** |

## 2. Candidatos que cabem em ~2.8 GB livres

| Modelo | GGUF (medido HF hoje) | mmproj | FineSightBench | Nota |
|---|---|---|---|---|
| **Qwen3-VL-2B** | 1.83 GB (Q8) | 0.45 Q8 / 0.82 F16 | AUC 60.0 | Res. nativa (min/max_pixels); **use mmproj F16** — Q8 tem *rep-fail* em greedy ([relato](https://huggingface.co/steampunque/Qwen3-VL-2B-Instruct-MP-GGUF)) |
| **InternVL3-1B** | 0.68 GB (Q8) / 1.27 (F16) | 0.33 / 0.62 | AUC 55.0 (pior) | CHR = 0.0 (ordenar/mudar = morto) |
| SmolVLM-500M | 0.44 GB | 0.11 / 0.20 | **não existe** | OCR/doc; GGUF worse que transformers ([PR 13050](https://github.com/ggml-org/llama.cpp/pull/13050)) |
| Florence-2-base-ft | **sem GGUF oficial** | ~0.9 GB bf16 (transformers) | **não existe** | Único com bbox/mask; mas degradou em objeto pequeno (InspectVLM) |

**SmolVLM3 não existe.** O último oficial é SmolVLM2 (2.2B). **Moondream3-preview** são 9B MoE — o próprio vLLM marca `min_gb=48` (~18 GiB/instância): descartado. **SmolVLM2-2.2B** (Q4_K_M 1.11 + 0.59) cabe, mas a família Smol é oriented a doc/OCR.

VRAM bf16 (medido, [SmolVLM paper](https://arxiv.org/html/2504.05299v1)): 256M = 0.8 GB · 500M = 1.2 GB · 2.2B = 4.9 GB. Nenhum benchmark desses papers cobre pixel art ou 32×32 — **não inventei cobertura**.

Velocidade: Qwen3-VL-2B Q8 faz ~185 t/s em RTX 4070 (medido por terceiro); num4050 espere60–150 t/s, mas **o gargalo é TTFT** (visão): 3.2 s num celular flagship, ~0.5–1 s no seu4050.

## 3. Recomendação ranqueada

1. **Qwen3-VL-2B (Q8 + mmproj F16, ~2.6 GB)** — teste agora. Melhor AUC entre <2B e o mais *image-leaning* da família Qwen3-VL ([auditoria](https://harvey-fin.github.io/seeing-is-not-reasoning/)). Já cabe nos 2.8 GB livres.
2. **Pipeline CLIP/SigLIP + MLP fine-tuned** — **maior EV, e o paper que valida é GameTileNet**: 0.92 micro-F1 em tiles 32×32 *de verdade*. Seu SigLIP já carrega; o problema é que ele é **zero-shot**, eíScores ±0.02 é exatamente isso. Com ~200 sprites rotulados você provavelmente bate qualquer VLM generativo.
3. **InternVL3-1B** — só como baseline barato (1.3 GB total); AUC 55 sugere ganho mínimo sobre Moondream.
4. **Descartar:** Moondream3, Qwen3-VL-4B (não cabe), SmolVLM 256M/500M.

**Honestamente:** 0% de acerto em *forma* não é limitação de resolução — 32×32 upscaleado 14× passa folgado do limite de 12 px do FineSightBench. É (a) viés de domínio (VLM nunca viu Tibia) e (b) pergunta aberta demais. Faça duas mudanças antes de trocar de modelo: **upscale nearest-neighbor 448²** (GameTileNet mediu ganho), e **feche o label space** ("qual destes 12 nomes?") em vez de caption livre.

Quer que eu monte o harness CLIP+MLP com GameTileNet como pré-treino, ou o teste do Qwen3-VL-2B primeiro?

---

