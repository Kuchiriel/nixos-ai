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

## A/B de idioma, medido (29/09)

Mesma task (extrair 2ª linha), mesmo modelo (bonsai), mesmo sampling,
só muda o idioma do prompt:

| Prompt | Resultado | Bytes entregues |
|---|---|---|
| EN | RC 0 (declarado sucesso) | **0 — arquivo vazio** |
| PT-BR | RC 1 (declarado fracasso) | **8 — conteúdo correto** |

Duas coisas, nenhuma é "o inglês é melhor":

1. **O hypothesis se confirma por um caminho inesperado**: em EN o
   modelo para mais cedo — cumpre o *shape* da tarefa (cria o arquivo)
   sem cumprir o *conteúdo*. Não é dificuldade de inglés, é adherence
   literal ao verbo: "write ... to out.txt" mapeia para criar o
   arquivo. Em PT-BR ("escreva SÓ a segunda linha em") o "SÓ" força
   atenção ao conteúdo.
2. **Achado de harness (mais importante que o idioma)**: o verificador
   deu **VERIFIED para 0 bytes** — "arquivo existe". Falso positivo
   puro, exatamente o que a gente disse querer evitar. Corrigido:
   deliverable vazio é UNVERIFIED, com exceção quando a task pede
   vazio explicitamente.

### O que isso diz sobre medir
O EN "ganhou" o RC e perdeu a entrega. RC honesto e entrega real são
coisas diferentes, e só a segunda importa. Um A/B medido só por RC
teria dado "EN 1×0, PT 0×1" — leitura totalmente invertida.

Ação de prompt (barata, geral): pedir o conteúdo **explicitamente** em
EN ("write ONLY the second line, no headers") em vez de confiar no
verbo. Isso é hipótese, ainda não medida.

## A/B de prompt, 4 variantes (29/09) — RESULTADO NEGATIVO

`scripts/ab-prompt.py bonsai --runs 1`, mesma fixture, 4 prompts:

| Variante | Conteúdo entregue | RC |
|---|---|---|
| en-plain | `<second line from data.txt>` | 1 |
| en-ONLY | `Linha 2` | **0** ← falso positivo |
| en-then-verify | `` (vazio) | 1 |
| pt-plain | `Linha da data.txt` | 1 |

**Nenhuma entrega. O bonsai fabrica em 4/4.** E a hipótese do "ONLY"
— que eu apresentei como a变量的 promising — **não se sustenta**: a
variante `en-ONLY` foi a única com RC 0 e ela está errada.

### Correção do que eu disse antes
Eu li o A/B anterior como "o hypothesis se confirma, em EN o modelo
cumpre o shape e o PT-BR entrega certo". Com n=1 por braço isso era
**variância, não efeito**. Rodando 4 variantes: o PT-BR também
fabrica (`Linha da data.txt`). O único acerto real que vimos foi
`beta two` num braço PT isolado — e sumiu na repetição.

Lição de método: **n=1 por braço não é A/B, é anedota.** O `--runs 2`
que eu pus no script é o piso, e ainda assim o piso honesto é 3+.

### Falso positivo novo (o que o harness ainda não pega)
`en-ONLY` escreveu `Linha 2` (7 bytes, não vazio) e ganhou RC 0.
O check de "arquivo vazio" que acabei de añadir cobre 0 bytes, mas
**conteúdo errado e não-vazio é indistinguível sem verifier**. Isso é
o argumento definitivo para o Harbor: verificador externo é o único
que separa "entregou" de "parece que entregou".

### O que isso significa
- A task de extração está **acima do bonsai** em qualquer idioma ou
  phrasing. Não é prompt, não é sampling, não é idioma.
- A variável livre é **capacidade** (o 120B faz 5/5 nisso), não
  calibration de prompt.
- Logo: o próximo unlock é achar o que o bonsai *é bom*, não tentar
  torná-lo bom no que ele não é. Isso é a versão honesta do "role".

## mission-kit: bateria que discrimina (29/09)

`scripts/mission-kit.py` — 4 capacidades distintas, verifier externo
(hash do conteúdo que o agente não escreve), distratores com
canário. Substitui a lite battery como sinal, porque a lite mede
transferência (bash-first resolve 4/5 para qualquer um).

| Task | mede | bonsai | fast |
|---|---|---|---|
| T1-diagnose | achar linha defeituosa + não só executar | 1/2 | 1/2 |
| T2-search | precisão de busca em 200 linhas c/ ruído | 0/2 | 0/2 |
| T3-synthesis | combinar dois arquivos | 0/2 | 0/2 |
| T4-robustness | instrução válida cercada de distrator | **2/2** | 1/2 |
| **TOTAL** | | **3/8** | **2/8** |

### O achado: o bonsai é bom em robustez, não emraciocínio
T4-robustness **2/2** — o bonsai ignorou todos os canários (BANANA,
PWNED, 42) e computou certo. O Qwen3-4B, "melhor modelo" em paper,
perde. Isso é a tese do dono confirmada com número: **poda ternária
preserva disciplina de instrução**, e disciplina é o que a maioria
das tasks de agente mede.

Onde ele não é bom: T2-search (0/2) e T3-synthesis (0/2) — precisão de
busca e combinação multi-arquivo. Números plausíveis mas errados
("34" em vez de 137, "123" em vez de 378). Não é alucinação —
é incapacidade de contagem/varredura nesse tamanho. **Esse é o
gargalo mensurável, e ele é de capacidade, não de harness.**

### O bug de raiz que a bateria expôs
Primeira execução: **0/16, e rc=0 com nada entregue.** Causa: o filtro
de artefato em `dev.py` casava só strings PT ("não existe"), mas o
`completion.py` emite em inglês ("doesn't exist yet"). Em prompt EN o
nudge **nunca** disparava — o modelo lia, calculava certo, escrevia em
prosa, e o mundo ficava sem arquivo, sem reopen, com RC 0.
**A segurança do harness estava desligada justamente quando o dono
fala inglês.** Corrigido → 0/8 vira 3/8 e 2/8 sem tocar no modelo.

Esse é o achado mais importante do dia: uma fronteira entre dois
módulos, cada um speakando uma língua, e o dono falando a língua que
ninguém dos dois testou. Silencioso. Falso. Caríssimo.
