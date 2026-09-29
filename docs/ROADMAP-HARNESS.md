# Roadmap harness 29/09 → paridade local

> Onde estamos e o que dá o próximo passo, com o critério de sucesso de
> cada item. Derivado de ~40 trials Harbor + 1 missão multi-etapas.

## Onde estamos (medido, não opinado)

| Eixo | Estado |
|---|---|
| Lite battery (bonsai/fast) | 4/5 |
| Lite battery (DeepSeek-NVIDIA) | 5/5 |
| Lite battery (R1-distill-7B local) | 3/5 — **não promovido** |
| Missão multi-etapas (MoE local) | diagnóstico+fix perfeitos, falta o último passo |
| Testes | 1417 verdes |
| Gates de honestidade | RC verificado no mundo, claim-checker, verdict display |

## Tese confirmada

Dois eixos independentes, e **o harness responde por ~27pp** nos
modelos pequenos (Claw-SWE-Bench, arXiv 2606.12344 — o mesmo número que
a gente mediu por conta própria: text-fight 0/25+ → bash-first 4/4).

O eixo do **cérebro** responde pelo resto. Raciocínio converte na
decisão (MoE acertou o diagnóstico e o fix) mas não no último passo
— e isso era harness, não modelo.

## Próximos passos (em ordem de retorno)

### 1. Fechar a missão multi-etapas com o MoE — ALTA
Único item onde um modelo **local** chega perto do 120B. Falta o
deliverable final. Hipóteses já implementadas (nudge de resposta
vazia, zero-width). Medir: `total.txt == 550` e CSV com `5,50`.
**Se fechar, é a prova de que a paridade local é alcançável.**

### 2. Bateria que diferencia modelo, não harness — ALTA
A lite battery é dominada por transferência bash (bash-first resolve
tudo). C discriminate só nos 27% restantes. Adicionar tasks de
*inspeção* (encontrar o defeito num dataset), não de *cópia*.
Sem isso, todo modelo parece igual e medimos o harness, não o cérebro.

### 3. Ritual de read-back como default — MÉDIA
O DeepSeek-NVIDIA faz read-back espontâneo (`od -c` no output) e é o
único 5/5 estável. Os locais param depois do write. Tornar o read-back
padrão do harness = codificar o que o melhor modelo faz por instinto.
Custo: 1 tool call. Ganho esperado: converte o "acerta e sobrescreve".

### 4. Calibrador de teto — MÉDIA
`scripts/hwprofile.py` já tem perfis. Falta medir **por tier** em que
tarefa o modelo deixa de convergir, e guardar isso como dado consultável
pelo modelo_policy (escolher tier pelo tipo de tarefa, não só por
capacidade declarada). É o que transforma "o MoE é bom" em política.

### 5. Hardware como upgrade — BAIXA (mas é o unlock)
Achados de hoje: R1-7B a 16k **não cabe** na VRAM 6GB com KV fp16
(precisa RAM). Com 16GB+ de VRAM, o mesmo distill sobe de 8k → 16k
ou mais, e missões longas deixam de bater em janela. A criação é útil
mesmo se o hardware atual não acompanha — é o que o dono pediu.

## O que NÃO fazer (aprendido na marra)

- **Não adaptar o runtime para passar numa task.** Otimizar o
  instrumento é a forma mais eficiente de mentir para si mesmo.
- **Não promover modelo por impressão.** R1 "parece" reasoning e
  perdeu do bonsai na bateria. Critério primeiro, achar depois.
- **Não medir com outro processo na máquina.** VRAM suja já custou
  uma investigação inteira.
- **Não tratar reasoning como plano.** Raciocínio sem enforcement de
  ação vira prosa bonita (R1: 8× o mesmo comando).
- **Não escrever flag nova no `models.nix` sem o dono decidir — flags
  são decisão de sistema, não de harness (AGENTS.md). O resto do
  método está em `.agents/harbor-e-harness.md`.

## Como cada item é validado

Rodar `scripts/harbor-lite.sh <modelo>` antes e depois, com o **mesmo**
conjunto. N=1 não decide nada; duas execuções divergentes é o piso.
Placar datado em `docs/harbor/INDEX.md`.
