# Moondream2 local — a receita que funciona (medido 08/10/2026)

> Para visão de sprites do TIBIA. Medido nesta máquina (RTX 4050 Laptop,
> **6 GB de VRAM**). Detalhe por projeto em
> `canary-official/dataset/maps/MODELS-VISION.md`.

Este doc mora aqui porque o indexador RAG tem **jail de path**: só lê
arquivos sob `/home/nixos/projects/nixos-ai` (`devtools._safe_path`). Doc de
visão que fica só no canary não é recuperável por `jarvis rag`.

## TL;DR

| Caminho | Funciona |
|---|---|
| **transformers, revision `2024-08-26`** | ✅ **4120 MB**, 1.4 sprites/s |
| llama-server + GGUF | ❌ 400 / Q8 degenerado |
| `llama-mtmd-cli` + GGUF | ✅ mas 1 processo por imagem (11–18 h) |
| SigLIP 775 MB | ⚠️ carrega, não discrimina |

**Não é problema de VRAM.** O modelo ocupa 4.1 GB e cabe. O que quebrava
eram três bugs, não falta de memória.

## Os três bugs (e a ordem em que aparecem)

1. **400 "Failed to tokenize prompt"** — o GGUF local tem
   `chat_template: "vicuna"`, e o mtmd do llama.cpp injeta um
   `media_marker` **aleatório por start** que o tokenizer do Moondream não
   conhece. `curl /props` mostra o marcador e o template (a prova).
   Bug upstream conhecido: llama.cpp [#27249](https://github.com/ggml-org/llama.cpp/issues/27249), [#21955](https://github.com/ggml-org/llama.cpp/issues/21955).
2. **Q8 degenerado** — o GGUF "certo"
   (`cjpais/moondream2-llamafile`, Q8 1440 MB, o único que cabe folgado)
   passa a tokenizar, mas nesse build responde `"What is the capital of
   France?"` → `"London"` e ecoa o prompt. Toda imagem volta vazia.
   `llama-mtmd-cli` ainda faz **core dump** nele.
3. **pesos e código de revisões diferentes** — baixar `model.safetensors`
   do `main` e o `.py` do SHA `5d6c926` (que não é o `main`) produz saída
   corrompida (eco com caracteres perdidos) e estouro de contexto em 2048.

## A receita

O próprio repo avisa em `hf_moondream.py`:
*"or alternately pin to `revision=2024-08-26`"*. O par casado:

```bash
SHA=92d3d73b6fd61ab84d9fe093a9c7fd8c04bf2c0d   # == tag 2024-08-26
BASE=https://huggingface.co/vikhyatk/moondream2/resolve/$SHA
# .py + .json + model.safetensors (3736040266 bytes) TODOS desta rev
```

Conferir o byte-count do safetensors é como se pega o par errado.

```bash
python3 -m venv /tmp/mdenv
/tmp/mdenv/bin/pip install "transformers==4.45.2" torch torchvision einops pillow accelerate
```

- `transformers==4.45.2` — o 5.5.4 do nixpkgs quebra a geração deste
  `trust_remote_code`.
- `torch` do venv **tem CUDA**; o do nixpkgs é CPU-only.
- `einops` e `torchvision` são exigidos por `vision_encoder.py`.

```python
import os, torch
os.environ["HF_HUB_OFFLINE"] = "1"        # senão o repo tenta a rede no __init__
from transformers import AutoModelForCausalLM, AutoTokenizer
M = "/home/nixos/models/moondream2-0826"
tok  = AutoTokenizer.from_pretrained(M, trust_remote_code=True, local_files_only=True)
# torch_dtype NO from_pretrained: em fp32 estoura os 6 GB antes de converter
m = AutoModelForCausalLM.from_pretrained(
    M, trust_remote_code=True, local_files_only=True,
    torch_dtype=torch.bfloat16).to("cuda").eval()
with torch.no_grad():
    ans = m.answer_question(m.encode_image(img), PROMPT, tok, max_new_tokens=48)
```

`max_new_tokens`, não `max_tokens` (o outro é ignorado e levanta erro).

### Duas armadilhas do `trust_remote_code`

1. O transformers copia os arquivos para
   `~/.cache/huggingface/modules/transformers_modules/<dir>/` e **não
   acha `fourier_features.py` / `layers.py`**. Workaround: rodar um
   `AutoConfig.from_pretrained()` (falha), `cp *.py` para dentro do cache,
   e só então carregar o modelo.
2. Na revisão nova, `moondream.py` faz
   `Tokenizer.from_pretrained("moondream/starmie-v1")` **dentro do
   `__init__`** → quebra offline e devolve 401. A `2024-08-26` não tem
   isso — mais um motivo para a revisão antiga.

## Prompt: curto e POSITIVO

Bake-off de 4 prompts, 5 sprites com tag conhecida → **3/5 cada**.
Prompt não move o needle. E o bloco `DO NOT:` do `PROMPTS-VISION.md` §3
faz o modelo **colapsar para a palavra `"Grass"`** em 5 de 6 sprites.

> Negative constraints ajudam VLM grande (NIM 90b) e **prejudicam** VLM
> pequeno. Regra da casa: Moondream = curto e positivo.

## Precisão real

Cruzamento VLM × medição de pixel em 150 sprites de terreno:
**52% concorda** material, **42% conflita**.

Nas 46 tags do dono acerta **material/cor** (4543 "stone wall", 4726
"snow-like texture", 4727/4728 "white line") e erra **todo detalhe de
forma** (rastros → "pink flower", galhos → "four soldiers").

→ **Complemento, nunca fonte autoritativa de texto.** A base que cobre
tudo é medir o pixel (máscara alpha + cor) e usar o **nome do item** como
verdade semântica.

## Serviço systemd

```nix
services.vision-moondream.enable = true;   # porta 8098 (8094 é MyAAC)
```

Não sobe no boot (VRAM 6 GB = 1 LLM por vez). `Conflicts` com
`llama-cpp-upstream` + `vram-guard-cshin` faz o swap sozinho: subir a visão
derruba o jarvis-fast; derrubar a visão devolve.

```bash
sudo systemctl start vision-moondream
curl localhost:8098/health
curl localhost:8098/props
curl -XPOST localhost:8098/tag -d '{"path":"/tmp/sprite-cenas/4531.png"}'
```

## Outras armadilhas desta sessão

- `HF_TOKEN` da máquina ("Jarvis2") está **expirado**: download de arquivo
  pequeno do HF volta `Entry not found` mascarado, e o traceback aponta
  `main` quando existe uma tag/revision que funciona.
- No `items.xml` deste projeto a descrição é
  `<attribute key="description" value="..."/>`, **não** `<description>`.
- 2961 itens são `<item fromid=… toid=…>` (faixa, sem id individual).
- Placeholders internos (`RESERVED SPRITE`, `DEPRECATED item`, `void`,
  `unknown`) **não** recebem descrição — vira lixo no servidor.
- LoRA de pixel art do projeto é de **Flux** (988 tensores
  `single_transformer_blocks`): serve para **gerar**, não para taguear.
  Moondream tem LoRA nativo (`lora.py`) para calibrar com as 46 tags.