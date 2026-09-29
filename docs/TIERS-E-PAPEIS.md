# Papel por tier — parar de comparar coisas diferentes

> 29/09. Correção epistêmica do dono que invalidou metade de uma tabela
> minha. Registrada porque o erro é estrutural, não pontual.

## O erro

Eu montei um placar único (byte / bin / line) e tratei "nota" como
"capacidade". Isso compara **papéis diferentes**:

| Modelo | Papel | Como deve ser julgado |
|---|---|---|
| bonsai 8B ternary | **executor** — poda ternária (g64) de um modelo maior | throughput e aderência a instrução; ganha de "modelos melhores" é **esperado** quando a poda preservou a capacidade e o prompt é EN |
| Qwen3-4B fast | executor denso | idem, sem poda |
| Qwen3.6-35B-A3B (MoE) | **estrategista / preparação** — raciocínio, 3.6B ativos de 35B | qualidade da *decisão* (diagnóstico, plano, escolha de ferramenta), não velocidade |
| DeepSeek-R1/v4.1 (API) | **executor forte** | throughput + acerto |

Comparar MoE com DeepSeek como "quem acerta mais na task" é injusticez:
são camadas diferentes do mesmo sistema. O MoE é o orquestrador; o
DeepSeek é a mão.

## Regra

**Nota por tier só compara tier com tier.** E o placar muda de métrica
conforme o papel:

- executor → taxa de conclusão em N tentativas (a lite battery)
- estrategista → qualidade do diagnóstico em missão multi-etapas, com
  métricas próprias:Steps até a decisão certa? Escolheu a ferramenta
  certa? Identificou a causa raiz? (Hoje: medido por 1 missão, n=1.)

## O que muda na prática

O experimento certo não é "MoE vs DeepSeek na task de cópia". É:

1. **MoE diagnostica, DeepSeek executa** — a bateria de 5 tasks vira
   pipeline: o MoE produz o plano/hipótese, o executor executa. Se a
   entrega final melhorar, a camada funcionou. Isso é composição, não
   competição.
2. O bonsai **não** é frowned upon por perder do Qwen3-4B. Ele é
   poda de um modelo maior, e o ponto de poda é entregar mais tokens
   por segundo com capacidade preservada. O critério dele é
   latência + aderência, não nota bruta.

## E o bonsai em prompt EN

O dono está certo: em EN o bonsai rende melhor (é um modelo base
treinado majoritariamente em EN, com poda). Todo o A/B de hoje roda em
PT-BR porque é a língua do dono — o que **subestima** o bonsai
sistematicamente. Comparação honesta exige o mesmo idioma nos dois
lados, e o idioma nativo do modelo é o critério.
