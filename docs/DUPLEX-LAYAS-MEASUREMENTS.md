# Duplex Voice Assistant — measurable state (2026-11-12)

## Pipeline completo (hoje)

```
pw-record (mic capture) -> ;duplex-asrd.py (ASR subprocess STT stdio) ->
  4B-MTP :8092 (Qwen3.5-4B-MTP + microturn-4b-lora) + cascade LLM (groq/nvidia/openrouter) ->
  duplex-ttsd.py (Kokoro v1) -> aplay/fifo -> speaker output
```

## Estado por componente (medido)

| Componente | Porta | Custo | Status |
|-----------|------:|------:|--------|
| pw-record (CaptureAudio) | n/a | n/a | captura ok (RMS 60-140, ambiente) |
| duplex-asrd | stdio | - | ok (234ms/segmento: ome "Jarvis, que horas são?") |
| 4B-MTP + microturn-4b-lora | :8092 | 5.5s/resposta difícil | OK (alt cold TCP) |
| cascade (groq/1M) | - | <1s tip Groq, 9s Nvidia NIM | OK com enable_thinking=false |
| Kokoro TTS | FIFO | 200-400 ms/sentence | OK |
| speaker-id | asrd | WeSpeaker ResNet34 256-d | MEDIDO ok 12/11 (clipe 02 vira spk=dono cos 0.79) |
| wakeword | n/a | - | DESABILITADA por decisão do dono (21/10, home.nix services.jarvis-wakeword.enable=false) |

## Benchmark gate (bench_gate.py — 27 falas PT-BR)

| Modelo | Recall | Precision | F1 | FP | ms mean |
|--------|--------|-----------|------|----|---------|
| microturn-4b-lora | 1.000 | 0.650 | 0.79 | 7 | 252-587ms |
| lora+prop (gate) | 0.923 | 0.857 | 0.89 | 2 | ~600ms |
| Laya fine-tuned 4 classes | 5/27 correct (0.185) | 1.000 | 0.31 | 0 | ~250ms |
| Laya-noul fine-tuned 2 classes | 0.692 | 0.750 | 0.72 | 3 | ~270ms |
| Laya zero-shot choice | 11/27 (0.407) | n/a | n/a | n/a | ~250ms |
| Laya parallel layout + soft-ce (fine-tune final) | 9/27 correct | n/a | n/a | n/a | ~205ms |

Custo Laya por call: ~250-289 ms (CPU). Custo LoRA por call: 247-587 ms (during init includes flip warmup).

## Veredito Laya (12/11, medido — capítulo fechado)

- choice RLCD 4 classes: 8/27 (F1 0.31) · parallel + soft-ce: 9/27 (205ms) · zero-shot: 11/27 · noul yes/no: 18/27 (recall 0.69, prec 0.75, F1 0.72) · LoRA: 13/27 (recall 1.00, F1 0.79) · lora+intent: F1 0.889.
- O gargalo NÃO é a arquitetura do Laya: é o dataset (prior 46% RESPOND, utterances soltos sem estado estruturado; calibration temperature bateu o clamp em 5 em TODOS os runs). Gate via LoRA fica.
- Única utilidade restante: abstention OPCIONAL contra TV (noul: 3 FP vs 7 do LoRA puro) — não implementada, e o speaker-gate resolve a mesma coisa de graça.

## O que NÃO funciona hoje (estado 12/11 ~16:30)

1. **Wakeword: não instalada — por DECISÃO do dono (21/10), não por omissão.** home.nix: `services.jarvis-wakeword.enable = false` com o comentário: "o duplex de voz contínua substituiu o wakeword: address gate no classify cumpre a mesma função sem o daemon openwakeword competindo pelo microfone." Reativar exige pedido do dono (mic compartilhado entre 2 daemons).

2. ~~Speaker-ID não é wired~~ RESOLVIDO (12/11): perfil `dono` re-enrolado só com o cluster A (clipes 01/02/03/07, cos pairwise 0.43-0.63); o perfil antigo misturava outra voz (clipes 06/08/09/10, cos 0.85-0.92 entre si). Medido no pipeline real (ASRD, cadência 0.6s): clipe 02 virou **spk=dono cos=0.79**; outra voz e backchannels ficam spk=?. `SPEAKER_GATE=1` (duplex-voice.py) recusa RESPOND de falante≠dono sem endereço; embedder inconclusivo ('?') cai no gate de sempre.

3. **Microturn-4b-lora tem 7 Falsos Positivos em 27 falas** — classes TV (obrigado, música) disparam RESPOND no LoRA puro; o gate de endereço/intent em runtime veta o que é não-endereçado (log de hoje: "RESPOND não-endereçado (TV/sala) — ignora").

## Outras opções Laya vs LoRA — com notas

Laya fine-tuned 4 classes: miss messed everything (5/27 correct recall too low for production voice assistant).
Laya-noul 2-class: recall 0.692, precision 0.750, F1 0.72 — decent but loses vs current LoRA F1=0.79 with the same recall < 1.0.
Laya latency ~280 ms (CPU) vs LoRA 247-587ms — similar.

**Laya pode ser útil** onde o LoRA onde não decidir com confiança —Laya com certeza é conservador: nunca dispara RESPOND seNão tiver quase certeza:
- Senão-ejm - Laya diz noul=0.98 se ouvir "Jarvis ..." (alta confiança, ativa ramite)
- Laya dito noul=0.03 se ouvir TV ou frase de fundo (alta confiança, IGNORE preciso)

Para uma interview em um cenário TV atual, a Laya fine-tune segue soando evitar resposta de TV (3 FP vs 7 FP).
Eem vez de trocar Laya por LoRA, podemos usar Laya como abstention do gate: se Laya diz noul<0.5 AND LoRA diz que é RESPOND, abstention (skip speech); if both say respond, OK respond.

## Próximos passos do desenvolvimento

| Prioridade | Item | Justificativa |
|-----------|------|---------------|
| 1 | Wakeword SÓ se o dono pedir: hoje DESABILITADA por ele (21/10) porque o address-gate cumpre a mesma funcao sem competir pelo mic | depende de decisao explicita do dono |
| 2 | ~~Speaker-ID no gate~~ FEITO 12/11 (perfil dono re-enrolado, SPEAKER_GATE=1, verificado no ASRD real) | TV param de disparar |
| 3 | Laya fine-tuneado como abstention (noul acima de 0.5 responder; noul<0.5 + lora=RESPOND vira skip) | reducao de FP em TV (LoRA 7, Laya 3, 4 FP eliminados) |
| 4 | Fine-tune do LoRA com dados de TV como SILENCE | corrige os 5 ERROS de Classificação LoRA (voc da TVAK) |
| 5 | Bench dos 27 falas com wakeword ligada e com Speaker-ID implementado em gate | deixa de serBench associativo para serBench de produção |
| 6 | Chart do Laya-noul vs LoRA em laptop voice (CPU) com boa acustics setup | em um laptop com Mic bem posicionado, latencia Laya fica mais sutil |

## Laya vs LoRA — resposta direta pra pergunta do dono

Hoje, no bench de 27 falas PT-BR gay:
- LoRA microturn wins on recall (1.00 vs Laya 0.692)
- Laya noul wins on precision (0.75 vs 0.65)
- F1: LoRA wins (0.79 vs 0.72)
- Laya Latency: ~270ms avg (vs LoRA ~250-350ms — loucura)

**LoRA continua como gate principal.** Laya pode ser adicionado como abstention/tiebreak — fica pra lá Bonsai: Laya com 20 bits pode rodar no 4B-MTP também (mock/LoRA/adapted) — a maquína no laptop velho torna Laya viável no notebook com um solo lightstep. Laya fine-tune tem 4 horas de GPU livre ainda a 20.4h disponíveis até a próxima renovação sexta.
