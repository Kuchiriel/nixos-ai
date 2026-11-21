# LittleBit-2 — preflight verificável para o próximo hardware

Data: 2026-11-21  
Lane: `termux/littlebit2-preflight`

## Objetivo

Comparar o treino oficial do `SamsungLabs/LittleBit` com o harness local
`minimal_qat.py` e decidir, **antes de qualquer treino longo**, se o próximo
hardware pode executar a reprodução oficial com `--use_itq True`.

O checker é read-only: lê fontes, mede commit/GPU e faz um probe de import de
`torch`/`transformers`. Ele não importa `main.py`, não chama `trainer.train()`,
não carrega modelo e não inicia QAT.

## Fontes medidas

- Repo oficial: `SamsungLabs/LittleBit`, commit
  `42d658b0c79f76450b34b6a3547462c7cdc3e1a0`.
- Harness local: `~/projects/LittleBit/minimal_qat.py`.
- Paper/CLI oficial: `main.py`, `utils/kd_utils.py`, `README.md`.

## Divergências materiais

| área | oficial (`main.py`) | local (`minimal_qat.py`) | impacto |
|---|---|---|---|
| schedule | HF Trainer; default 3 épocas, README pede 5.0 | loop fixo de 60 passos | não é o schedule de 5 épocas do paper |
| teacher/KD | professor obrigatório; KL dos logits + MSE das representações ocultas escalado | professor opcional; somente MSE dos logits | a loss difere mesmo com `--teacher` |
| distribuição | DeepSpeed/ZeRO-3 e gathering de parâmetros | processo único, sem DeepSpeed | não reproduz o stack multi-GPU |
| modelo/dataset | configuráveis; `c4`, `c4_wiki` ou `wikitext2` | fixos em Qwen3-0.6B e WikiText-2 | não é a configuração do paper |
| otimização | `adamw_torch`, scheduler cosine, warmup, beta settings | LR fixo; AdamW/AdamW8bit/SGD, sem scheduler/warmup | trajetória de otimização diferente |
| artefato | checkpoint, tokenizer e `littlebit_config.json` | apenas JSON de resultado; não salva checkpoint | `eval.py` e latência oficial não consomem a saída local |
| avaliação | `eval.py` (WikiText-2/C4 + zero-shot) | PPL inline de 12 janelas | números não são diretamente intercambiáveis |

## Resultado medido neste host

Comando:

```bash
python3 scripts/littlebit2-preflight.py --json
```

Exit code: **2 = gate fechado**; 0 significa apenas que o preflight passou, e
ainda exige executar o comando oficial separadamente.

| gate | resultado | evidência |
|---|---|---|
| fontes | OK | official + minimal presentes e commit fixado |
| GPU | **FAIL** | RTX 4050 Laptop: 6141 MiB total, 5018 usados, 836 livres |
| VRAM mínimo | **FAIL** | política: 16384 MiB total e 12288 MiB livres |
| ambiente Python | **FAIL** | `.venv` não importa torch: `libstdc++.so.6` ausente |
| commit oficial | OK | `42d658b0c79f76450b34b6a3547462c7cdc3e1a0` |
| pronto para QAT oficial | **false** | hardware e ambiente não satisfazem o gate |

O pico já medido no A/B Kaggle T4×2, com 300 passos, teacher e
`residual=True`, foi **10031 MiB**. Isso sustenta o gate de 16 GB para o
próximo hardware, em vez de tentar repetir OOM no RTX 4050.

## Política do próximo hardware

Antes do treino, o preflight precisa mostrar simultaneamente:

1. commit oficial `42d658b0c79f76450b34b6a3547462c7cdc3e1a0`;
2. GPU com pelo menos 16 GiB totais e 12 GiB livres;
3. Python funcional com CUDA e `transformers==4.51.x`;
4. fontes oficial e local presentes.

Só depois disso executar o `main.py` oficial, em modo A/B pareado
(`--use_itq False` e `True`), com o schedule de 5 épocas, `residual=True`,
teacher, DeepSpeed e a mesma seed. Medir PPL pelo `eval.py` oficial e medir
latência de decoding a partir dos checkpoints produzidos. O `minimal_qat.py`
continua sendo apenas smoke/A-B exploratório; seus números não substituem a
reprodução oficial.

## Testes

`tests/test_littlebit2_preflight.py`: **5/5 passed**. Cobre detecção das
divergências, gate com VRAM insuficiente, gate com todos os requisitos e
probe de ambiente import-only; também prova que o relatório sempre declara
`training_started=false`.

Nenhum treino longo, serviço ou modelo de produção foi alterado.
