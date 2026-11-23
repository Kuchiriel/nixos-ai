# LittleBit-2 oficial — baseline 5 epochs concluído; eval.py OOM corrigido

Data: 2026-11-22

## Execução medida

Kernel: `kuchiriel/littlebit2-official-qat-5epoch-qwen3-0-6b`

O baseline oficial de 5 epochs concluiu:

```text
variant_complete=baseline elapsed_seconds=29094.5
```

Artefatos preservados no host:

```text
/home/nixos/work/littlebit2-official-baseline-20261123/baseline
model.safetensors: 678826904 bytes
train-wall-time.json: elapsed_seconds=29094.5
```

O protocolo medido foi: 1.229 exemplos, sequência 2.048, batch global 4 e 1.540 optimizer steps.

## Falha exata

O kernel terminou `ERROR` durante `official_ppl`, não durante o treino:

```text
torch.OutOfMemoryError: CUDA out of memory.
Tried to allocate 100.00 GiB.
GPU 0 total 14.56 GiB, 2.90 GiB livres;
processo 11.66 GiB em uso.
```

Causa: `eval.py` autodetecta `seqlen` pelo `max_position_embeddings=40960` do Qwen3. O treino e o dataset usam 2.048, mas o eval automático usava 40.960 e não cabia na T4.

## Correção

- o contrato passa a fixar `evaluation.ppl_seqlen=2048`;
- `official_ppl` passa `--seqlen 2048` ao `eval.py` oficial;
- `LB_VARIANT` permite executar baseline ou LittleBit-2 isoladamente, pois cada variante mediu cerca de 8h e o par sequencial excede a sessão Kaggle de 12h;
- novo kernel `kuchiriel/littlebit2-official-qat-5epoch-qwen3-0-6b-itq` executa somente a variante LittleBit-2;
- o baseline já concluído foi preservado para avaliação separada, sem repetir 8h de treino.

## Testes

`test_littlebit2_official_kernel_contract.py`: 8/8, incluindo sequência de PPL, seleção de variante e metadata do kernel ITQ separado.

Nenhum modelo de produção foi alterado.
