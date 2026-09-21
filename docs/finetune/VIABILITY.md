# FINETUNE VIABILITY — Bonsai 8B ternary (21/09, verificado, não achismo)

## Fatos verificados
- Base treinável existe: `prism-ml/Ternary-Bonsai-8B-unpacked` (safetensors
  FP, arq Qwen3, Apache-2.0). GGUF Q2_0_g128 é só inferência.
- Deploy de adapter: `llama-server --lora adapter.gguf` sobre base ternary
  (precedente UlukaDev bitnet-MoE). Sem re-quantizar a base.
- LoRA-em-ternary é 2026-ativo (QVAC Fabric edge-GPU, BitLoRA, HF blog
  1.58-bit). Não é teoria.
- VRAM (pesquisa, não chute): QLoRA-8B r8 + grad-checkpoint + paged-8bit
  AdamW + batch1 + seq2048 ≈ 6.2GB+ (paper 2509.12229, RTX 4060 8GB).
  4050-6GB = borderline/lento; T4-16GB confortável; 2×T4 headroom.
- Kaggle: 2 GPUs + 30h/semana (playbook applio-lab). Quota NÃO gasta ainda.
- Comunidade: nenhum fork 8B melhorado (só clone). Estamos na fronteira.

## Dados próprios (organizado em docs/finetune/)
- successes.jsonl: 113 trajetórias SFT-chosen.
- failures.jsonl: 74 classificadas (49 wrong-value, 21 no-output,
  3 harness-error, 1 syntax-retry).
- outputs.jsonl: 91 arquivos, 38 errados (35 wrong-number — cópia de
  números do prompt: 42/13/10/3; 3 prompt-word-guess).
- Correção honesta ao plano inicial: sintaxe pura é MINORIA (~5-10%
  c/ casos de transcript: python-repr, quoting, mold). Maioria =
  number-attraction + no-output (grounding/seleção) — mais difícil de
  ensinar via SFT; pede pares de preferência ou RL/harness.
- Gap: pares chosen↔rejected (só temos rejected soltos + chosen soltos;
  emparelhar por task = P1 antes de treinar).

## Trade-offs (usuário exigiu; registrar)
- LoRA-formato pode degradar chat geral (forgetting): exigir eval
  antes/depois = nossa KB-suite + 1 geral (ex: GSM8K sample).
- Melhorar fidelidade pode piorar verbosidade/criatividade: medir ambos.
- Adapter maior (r16+) = mais capacidade + mais VRAM + mais risco.
- Ternário + LoRA-FP16: inferência mais pesada (precedente ok em 2B;
  validar latência em 8B antes de declarar vitória).

## Opções ranqueadas
1. **Kaggle T4, QLoRA r8, SFT em format-slice** (alvo: JSON válido,
   tool-calls, sem prosa): custo 0, 1 fim de semana, quota intacta.
   Go/no-go por eval.
2. **2×T4 ou 1×P100, r16 + pares preferência** (após P1 emparelhar):
   ataca number-attraction (DPO/KTO). Custo 0, mais tempo.
3. **4050-6GB local**: possível (paper), 3-5× mais lento, trava a
   máquina p/ inferência. Só se Kaggle falhar.
4. **Aluguel 24GB**: só se 1-2 falharem por VRAM. US$2-5/teste.
5. **Full FT / nova quant**: NÃO (custo + risco, sem necessidade).

## Regra de parada
Qualquer eval-regressão (KB-suite ou geral) → reverte adapter, publica
números. Sem teatro.
