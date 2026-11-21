# LittleBit-2: ganho de compressão em SLM/LLM (21/11)

Consolida `LITTLEBIT2-RESEARCH`, `LITTLEBIT2-QAT-COMPRESSION` e as medições
feitas depois da autorização do dono para usar chaves/rebuild.

## Compressão medida (Qwen3-0.6B, 196 lineares)

Baseline FP32: **1761,6 MB** nos lineares.

| `eff_bit` | residual | tamanho quantizado | compressão |
|---:|---|---:|---:|
| 1,0 | não | 54,6 MB | 32,25× |
| 1,0 | sim | 54,1 MB | 32,53× |
| 0,55 | não | 29,8 MB | 59,04× |
| **0,1** | não | **5,2 MB** | **340,12×** |

Esse é o ganho original do paper e ele é real e reproduzível: a fatoração de
baixo rank com fatores binarizados reduz o modelo a ~0,3% do tamanho FP32 a
0,1 bpp. O `--use_itq` **não altera compressão** — ele só melhora a
inicialização antes do QAT.

## Latência de inferência (medida, sem kernel customizado)

| cenário | CPU (seq 256) | GPU (seq 256) |
|---|---:|---:|
| modelo original | 1059,4 ms | 28,88 ms |
| LittleBit 1,0 bpp | 1534,7 ms | 52,52 ms |
| LittleBit 0,1 bpp | 994,6 ms | 39,19 ms |

O repo oficial entrega scripts de **QAT e avaliação**, não um kernel de
servição. Com PyTorch genérico a fatoração é *mais lenta* que o Linear
original; os ganhos de 11,6×/2,46× do paper dependem do kernel MatMul-free
com bitwise ops, que não está neste repo. Portanto **não há ganho de速度 de
inferência disponível no nosso stack hoje** — só ganho de tamanho.

## A/B de QAT e por que não fechamos o PPL

- CPU, 30 passos, AdamW, residual=False: ITQ reduziu o loss inicial de 17,30
  para 15,42 (como o paper prevê), mas com 30 passos terminou pior
  (PPL 247.783 vs 16.394).
- GPU com residente, whisper e embeddings pausados: RTX 4050 6 GB ainda
  estoura VRAM (5,24–5,69 GB só no processo) mesmo com seq 128, SGD sem
  estado e `expandable_segments`. O protocolo completo (teacher, 5 épocas,
  `residual=True`) não cabe.
- Serviços devolvidos: `llama-uncensored-4b`, `duplex-voice`, `whisper-server`
  e `llama-cpp-embeddings` active; hub 200; opencode vivo.

## Decisão final

**Adoção para compressão: tecnicamente válida e de alto impacto** (340× a
0,1 bpp), mas exigiria (a) treino QAT completo em GPU ≥16 GB e (b) um kernel
de inferência bitwise — nenhum dos dois existe hoje no stack. Mantemos como
pesquisa documentada, sem mudar modelos de produção.

Critério objetivo para reavaliar: rodar `main.py --use_itq True` com o
protocolo do README em GPU dedicada, medir PPL WikiText-2 e tokens/s, e só
então trocar o modelo servido.
