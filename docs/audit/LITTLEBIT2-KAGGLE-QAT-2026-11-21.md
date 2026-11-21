# A/B completo do LittleBit-2 no Kaggle T4 x2 (21/11)

Kernel: `kuchiriel/littlebit-2-qat-a-b-qwen3-0-6b`, status `COMPLETE`.
Configuração: Qwen3-0.6B, 300 passos, seq 256, `residual=True`, professor
(destilação de logits, λ=10), AdamW lr 4e-5, semente 42, `eff_bit=1.0`.

| variante | loss inicial | loss final | PPL WikiText-2 (12 janelas) | tempo init |
|---|---:|---:|---:|---:|
| baseline (`use_itq=False`) | 280,57 | 74,09 | **1803,64** | 39,1 s |
| LittleBit-2 (`--use_itq`) | **210,00** | **69,11** | 2424,87 | 333,1 s |

Pico de VRAM: 10031 MiB em ambos (T4 x2, 16 GB por GPU).

## Interpretação

- O ITQ**melhora o ponto de partida** (loss inicial 280→210) e termina com
  **menor loss de treino** (74,1→69,1), exatamente o mecanismo descrito no
  paper (menos oscilação de sinal, convergência mais rápida).
- Porém, com apenas 300 passos, o **PPL de validação é pior** (1804→2425).
  O protocolo do paper usa 5 épocas completas (~45k passos nesta config),
  então 300 passos ainda estão no regime de subtreino — o que importa é o
  PPL, não a loss de treino.
- Custo único da inicialização ITQ foi **8,5× maior** (39 s → 333 s),
  compatível com a afirmação do paper de que é um passo offline caro.

## Decisão

Ainda **sem adoção**: o A/B completo reproduziu o mecanismo de convergência,
mas não o resultado de PPL. Antes de qualquer mudança é preciso o protocolo
completo (5 épocas) ou, no mínimo, um regime intermediário (~2000 passos)
para ver se o cruzamento ocorre. Nenhum modelo de produção foi alterado.

## Tentativa de 2000 passos (bloqueio)

Kernel `kuchiriel/littlebit2-qat-long-2000` foi enviado com o mesmo protocolo
e 2000 passos, mas permaneceu `KernelWorkerStatus.QUEUED` por 46 verificações
(~92 minutos) após o kernel de 300 passos ter terminado. Sem GPU adicional
disponível no momento, a reprodução completa (5 épocas) fica pendente —
tarefa devolvida à fila com o bloqueio registrado. Nada em produção foi
alterado.
