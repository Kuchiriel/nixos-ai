# O Heretic no gate: o plano medido (e por que não foi rodado sozinho)

(24/11/2026, coord-naming) O `quality-ab-local.py` (outra lane) comparou o
**Qwen3.8-4B Heretic** contra o Qwen3.5-4B em **red-team/CTF** (4 prompts
conceituais). Essa é uma comparação útil, mas **não é a da minha trilha**:
a pergunta aqui é se o Heretic **classifica melhor o gate de voz** do que o
MTP com o LoRA v9.

## O que já está medido (e o que falta)

| pergunta | estado |
|---|---|
| gate no **texto**, MTP + LoRA v9 | **29/39 (74,4 %)** (bench_heldout3) |
| gate na **voz**, MTP + LoRA v9 | **24/39 (61,5 %)** (bench-gate-voz, 23/11) |
| gate no texto, Heretic **sem** LoRA | **impossível por construção**: o gate é o LoRA micro-turn; sem ele o classificador não é o gate (o 8B denso medido deu 0 a 1 de 39) |
| gate na voz, **Heretic + LoRA v9** | **FALTA** — e é esta que decide qual modelo serve o dono |

## Por que não foi rodada de madrugada

**VRAM.** Medido nesta máquina: o MTP (com o LoRA v9) segura **3.836 MiB**,
o whisper **932 MiB**, os embeddings **182 MiB** ⇒ **884 MiB livres**. O
Heretic Q4_K_M tem **2.660 MiB** ⇒ **não cabe** ao lado do MTP.

Subir o Heretic **derruba o MTP**, e o MTP é **o cérebro do duplex** (a voz
do dono). Ou seja: a medição justa custa **a voz muda durante o tempo do
ciclo** — e a regra da casa é que a GPU é emprestada ao lab A/B e que nada
de GPU é pega sem coordenação.

## O caminho (3 comandos, ~8 min de voz muda)

```bash
# 1) o perfil 'code' (o MTP SEM o LoRA, na :8096) e' o que o lab usa.
#    O --free larga a VRAM (derruba o MTP: a voz fica muda durante o ciclo).
bash scripts/llama-swap.sh --free
bash scripts/llama-swap.sh --start-mtp code      # :8096, sem LoRA
# 2) o Heretic COM o LoRA v9 na :8092 (a unit do SISTEMA):
#    MEDIDO na unit: ela tem um ExecStartPre de vram-guard com 4200 MiB
#    exigidos — sem o --free acima ela nao sobe (e o guard e' o que impediu
#    o OOM, o mesmo guard que ja salvou a casa de um crash de VRAM).
#    ACHADO (24/11): o perfil 'uncensored-4b' do registry AINDA aponta
#    para o Qwen3.5-4B-MTP (url = .../Qwen3.5-4B-MTP-Q4_K_M...), e nao
#    para o Heretic que esta baixado em disco (Qwen3.8-4B-Distill-Heretic-
#    Abliterated-Q4_K_M.gguf, 2.660 MiB, 23/11). Portanto a unit do
#    'llama-uncensored-4b.service' ainda serve o MTP, e o Heretic so
#    entra depois de o registry apontar para ele (e' da lane do registry).
sudo systemctl start llama-uncensored-4b.service   # alias jarvis-uncensored
# 3) o bench, nas DUAS condicoes, com a base apontada:
python3 benchmarks/voice/bench-gate-voz.py --base http://127.0.0.1:8092 \
    --json /tmp/opencode/gate-voz-heretic.json
```

E no fim, **devolver a voz**: `bash scripts/llama-swap.sh --start-mtp lora`
(perfil `lora`, na :8092, com o LoRA v9).

## O que a comparação dirá (e a decisão)

- **Se o Heretic com LoRA ficar acima de 74,4 % no texto** ou **acima de
  61,5 % na voz**: o Heretic passa a ser o candidato do gate — e o número
  da voz é o que vale, porque é o canal real.
- **Se ficar igual**: fica o MTP (que tem o MTP/NextN, o draft Speculative
  e o `lora-init-without-apply` que a casa já mediu como estável).
- **Em qualquer caso**, o número da **voz** é o que decide, e ele é
  **~13 pontos mais baixo** que o do texto (medido em 23/11): o gate colapsa
  para SILENCE no canal de voz.

## Limites

O Heretic é **abliterated** (sem recusa): serve como **gate de voz** (que
classifica turnos), **não** como alvo de jailbreak nem como judge de recusa
(regra já escrita no registry e no AGENTS.md). O áudio do bench é
**sintetizado** (piper), não a voz do dono — o mesmo limite do bench de voz
de 23/11.
