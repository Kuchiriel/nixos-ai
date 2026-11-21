# LittleBit-2: compressão e QAT no Qwen3-0.6B (21/11)

Continuação de `LITTLEBIT2-RESEARCH-2026-11-21.md`. Agora a pergunta é o uso
original do paper: **compressão de SLM/LLM**, não RAG.

## Ambiente e método

- Repo oficial `SamsungLabs/LittleBit` clonado em `~/projects/LittleBit`.
- venv Python 3.12, torch 2.6.0+cu124, transformers 4.51.3, bitsandbytes 0.50.2.
- Modelo em cache: `Qwen/Qwen3-0.6B`.
- GPU RTX 4050 (6 GB) com 3 processos residentes: mesmo após `llm-swap takeover`
  e pausa do `whisper-server.service`, o QAT estourava a VRAM (5,25 GB só no
  processo). **Mudei para CPU** (30 passos, seq 256, sem `residual`, AdamW),
  com seed 42 idêntica nas duas variantes.
- Implementação oficial usada diretamente (`apply_littlebit_patch`);三次
  correções de harness: escalas SVD float32 → dtype do modelo, `dev` passado
  explícito à função de PPL e `pgrep` com colchetes (auto-match).

## Compressão (medida, não estimada)

Nos 196 lineares do Qwen3-0.6B com `eff_bit=1.0`:

| | MB |
|---|---:|
| pesos FP16 originais | 880,8 |
| fatores LittleBit | 54,6 |
| **compressão** | **16,13×** |

Essa compressão vem da arquitetura LittleBit (fatoração + binarização) e
**não** do Joint-ITQ — o ITQ só muda a inicialização.

## A/B de QAT (30 passos, CPU, mesmas condições)

| variante | loss inicial | loss final | PPL após |
|---|---:|---:|---:|
| baseline (`use_itq=False`) | 17,30 | 9,46 | 16.394 |
| LittleBit-2 (`--use_itq`) | **15,42** | 12,69 | 247.783 |
| tempo de inicialização | 15 s | 478 s | — |

O ITQ**melhora o ponto de partida** (exatamente o que o paper descreve: menos
oscilação de sinal), mas com apenas 30 passos **não convergiu** e terminou pior.
Os números absolutos de PPL são ruins porque 30 passos não são um QAT — o
paper usa 5 épocas com destilação do professor e `residual=True`.

## Decisão

**Não há evidência para adotar `--use_itq` no nosso stack ainda.** O que ficou
provado aqui é (a) a compressão de 16× e (b) o ganho de inicialização; o ganho
de PPL do paper exige o protocolo completo de treino, que não foi reproduzido.

Para reproduzir de verdade: GPU dedicada, `residual=True`, destilação do
professor, `wikitext2`, 5 épocas e `--use_itq True` — comparar PPL e velocidade
de decoding. Isso vira uma tarefa separada, não uma conclusão deste teste.

Serviços devolvidos ao estado original: residente `llama-uncensored-4b`
active, `duplex-voice` active, `whisper-server` active, hub 200, opencode vivo,
`git staged=0`. Nenhum dado de produção escrito.
