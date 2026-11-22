# LittleBit-2 official QAT — Kaggle T4×2, 5 epochs

Este kernel executa o protocolo **oficial** do upstream `SamsungLabs/LittleBit`; ele não usa `minimal_qat.py` como prova.

## Contrato

- upstream pinado: `42d658b0c79f76450b34b6a3547462c7cdc3e1a0`;
- modelo: `Qwen/Qwen3-0.6B`;
- dataset: `wikitext2`;
- variantes emparelhadas: baseline (`use_itq=False`) e LittleBit-2 (`use_itq=True`);
- 5 epochs, seed 42, residual `True`, professor obrigatório;
- KD oficial: KL dos logits + MSE das representações ocultas, escala 10;
- scheduler cosine + warmup, AdamW, DeepSpeed ZeRO-3;
- T4×2, micro-batch 1, accumulação 2, batch global 4;
- avaliação oficial por `eval.py` e medição de decoding dos checkpoints.

O dataset tokenizado foi medido em **1.229 exemplos × 2.048 tokens**. Em 2 GPUs, micro-batch 1 e accumulação 2, são **1.540 optimizer steps por variante** nas 5 epochs.

## Por que é executável no limite de sessão

O A/B anterior de 2.000 passos do harness minimal levou cerca de 2.035 s por variante, mas **não** reproduzia o trainer oficial. O contrato oficial tem 1.540 steps por variante e usa apenas ~1.229 exemplos. A documentação oficial do Kaggle permite **12 horas por sessão CPU/GPU**:

<https://www.kaggle.com/docs/notebooks>

O script ainda aborta se commit, GPUs, VRAM, contagem do dataset, steps, trainer, checkpoint ou PPL oficial divergirem.

## Artefatos

- `official-output/baseline/`: checkpoint, tokenizer, `littlebit_config.json`, eval e latency;
- `official-output/littlebit2/`: idem para `use_itq=True`;
- `official-output/protocol-measurement.json`;
- `official-output/results.json` com PPL oficial e tokens/s por variante.

## Proveniência

- contrato: `contract.json`;
- metadata Kaggle: `kernel-metadata.json`;
- fonte upstream: <https://github.com/SamsungLabs/LittleBit>;
- execuções anteriores minimal/Kaggle: `docs/audit/LITTLEBIT2-KAGGLE-QAT-2026-11-21.md`.

Nenhum serviço ou modelo de produção é alterado. O kernel é privado e só escreve no diretório de output do próprio job.
