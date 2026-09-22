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

## Medições locais 21/09 (4050-6GB, venv ~/.venvs/finetune, env.sh)
- Stack OK: torch-cu126 + bnb0.50 + peft + trl1.13 + paged-8bit OK.
  Shims NixOS: /sbin/ldconfig stub, CC=gcc-wrapper, cuda.h symlink,
  Python.h via CPATH, bf16 (não fp16), loss_type=nll (TRL×offload).
- 0.6B probe: 20 steps, 5 steps/s, pico 1.24GB, loss ↓. Stack válida.
- 8B: carrega c/ spill (23 GPU/17 CPU, 3.64GB repouso) mas TREINO
  BLOQUEADO em 3 camadas independentes: bnb exige tudo-na-GPU →
  fp32-prep OOM (2.31GB transient) → TRL-chunked vs offload →
  bnb meta-tensor em módulos CPU. VEREDITO: local insuficiente p/ 8B.
- Base 16GB baixada em 27min (~10MB/s) p/ ~/.cache/bonsai-unpacked.
  Upload p/ Kaggle inviável (3-70kB/s); baixar DIRETO no Kaggle do HF.
- Estimativa T4 (literatura, confirmar): 0.5-1.5 steps/s → 500 steps
  ≈ 1-2h. Cabe folgado em 30h/semana.
- Serviços religados e verificados (chat ok) após a janela de treino.

## Kaggle run 21/09 (T4, em andamento)
- Kernel `kuchiriel/bonsai-qlora-r8` v4 RUNNING: QLoRA r8, SFT 77 pares,
  holdout 15%, 500 steps, eval 250, bf16, paged-8bit, loss nll.
- Falhas v1-v3: dataset_sources não monta (embed 77 pares no script),
  TRL-chunked vs PEFT (loss_type=nll).
- Adapter sai em /kaggle/working (baixar + converter p/ GGUF-LoRA +
  servir com --lora quando COMPLETE).

## Eval adapter r8 21/09 — NÃO PROMOVIDO
- Treino: 500/500 T4, loss 3.43→0.011, acc 99.5% (overfit: só 77 pares).
- GGUF-LoRA 7.7MB servido em :8091 (porta separada; produção intacta).
- Base × LoRA (mesmos probes n=3): E1 ambos erram (base tab→@, LoRA
  tab→","; resto igual); T8-short ambos trocam 02↔03 igual; T-fact 3/3
  ambos. NENHUMA melhora mensurável; suspeita de memorização.
- Incidente: 2ª instância derrubou :8080 (500, VRAM) — evals 8B SEMPRE
  sequenciais nesta máquina (parar prod ou aceitar contenção).
- DECISÃO: arquivar números, reverter. Re-teste exige dataset maior e
  diverso (P2) + DPO, não mais epochs no mesmo.

## Eval DPO-77 21/09 — TAMBÉM NÃO MOVE (base×DPO iguais)
- E1: base tab→@, DPO tab→@ (idêntico). T-fact 3/3 ambos. T8-short:
  ambos trocam 02↔03 igual. Margem DPO 0.3→8.3 no treino, zero
  transferência. DPO-77 = SFT-77: memoriza, não generaliza.
- DPO-synth400 no ar (400 pares diversos, 600 steps): testa se
  VARIEDADE quebra o teto. Se também zerar → veredito preliminar:
  LoRA-r8 não move fidelidade/byte (alvo errado ou capacidade).

## Mismatch base treino×inferência (achado 21/09, verificar no próximo)
- Unpacked = denso FP (q_proj 425 valores únicos em slice — NÃO ternário).
- LoRA treina contra ativações DENSAS, mas inferência roda TERNÁRIO
  (Q2_0) + adapter → mismatch calibração→aplicação. Explica parte do
  zero-efeito (além de overfit/dados).
- Fix principista: base de treino = GGUF ternário DEQUANTIZADO p/ FP
  (valores idênticos à inferência) + LoRA em cima. Conversão exata,
  custo zero. Próximo round usa essa base.
