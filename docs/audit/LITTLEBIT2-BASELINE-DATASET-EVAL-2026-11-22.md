# Baseline LittleBit-2 oficial — dataset privado e kernel de avaliação

Data: 2026-11-22

## Baseline preservado

O baseline oficial de 5 epochs foi concluído antes do OOM no `eval.py` e está preservado no host:

```text
/home/nixos/work/littlebit2-official-baseline-20261123/baseline
model.safetensors: 678826904 bytes
train-wall-time.json: elapsed_seconds=29094.5
```

## Dataset privado

O checkpoint foi publicado como dataset privado:

```text
kuchiriel/littlebit2-official-baseline-qwen3-0-6b
```

Arquivos Kaggle medidos:

- `checkpoint/model.safetensors`;
- `checkpoint/config.json`;
- `checkpoint/littlebit_config.json`;
- tokenizer;
- `checkpoint/train-wall-time.json`;
- eventos TensorBoard.

A primeira criação do dataset mostrou apenas o metadata; a versão seguinte foi publicada com `-r zip` e continte o diretório `checkpoint/` completo.

## Kernel de avaliação sem novo treino

Novo kernel:

```text
kuchiriel/littlebit2-official-eval-baseline-qwen3-0-6b
```

Ele usa o dataset acima, fixa `LB_BASELINE_PATH=/kaggle/input/littlebit2-official-baseline-qwen3-0-6b/checkpoint` e chama o script oficial com `ppl_seqlen=2048`. Não executa treino; apenas PPL oficial e decode.

O caminho canônico também reconhece `LB_BASELINE_PATH`/`LITTLEBIT2_BASELINE_PATH` e grava `training_reused=true` no resultado.

## Testes

`test_littlebit2_official_kernel_contract.py`: 14/14, incluindo reuso do checkpoint, metadata/dataset do kernel e sequência fixa de PPL.

Nenhum modelo de produção foi alterado.
