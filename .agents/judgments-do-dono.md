# Julgments do dono (a trilha da renda)

> O modelo responde **por procuração do dono**: ele julga como o dono
> julga. Esta regra é o que **não** se quebra na trilha.
> Volte para [AGENTS.md](../AGENTS.md).

## 1. O caminho (cada peça existe e foi provada)

| peça | o que é | onde |
|---|---|---|
| **captura** | o item real da tela vira texto exato (clipboard primeiro, OCR da janela como reserva) | `scripts/uhrs-capture.py` |
| **voz** | o item de prática vira o veredito falado ("muito relevante") | `scripts/uhrs-practice.py --from-duplex` |
| **registro único** | os dois caminhos no **mesmo** arquivo, com o **mesmo** contrato | `data/judgments/labels.jsonl` (id · context · answer · key · why_dono · source · via · ts) |
| **id estável** | derivado do **conteúdo** (sha256 normalizado, 12 chars) | `scripts/uhrs-capture.py:item_id_de` |
| **seletor** | qual item julgar primeiro, com o porquê | `scripts/seletor-fracas.py` |
| **dataset** | o formato Laya, com o raciocínio do dono no `state` | `scripts/judgment-dataset.py` |
| **bench** | acerto por classe, F1 por nível, teto de repetibilidade | `scripts/judgment-bench.py` |
| **held-out** | o conjunto limpo (o v2 está **contaminado**) | `benchmarks/voice/heldout3.py` |

## 2. Os invariantes (cada um já custou um bug)

1. **O `answer` é a resposta do DONO**, nunca o gabarito. O gabarito fica
   no `key`, só para diagnóstico.
2. **O `context` NÃO carrega a resposta.** Medido: com a resposta no
   contexto, o bench dava **91,7 %**; com o contexto limpo, **58,3 %** — o
   número que decide a delegação.
3. **O `key` e o `why` DE QUEM ESCREVEU o item não entram no `state` do
   dataset** — senao o modelo aprende a copiar a resposta da casa (reward
   hacking por rubric, arXiv 2607.28802). O que entra é o **`why_dono`**.
4. **O id repetido é o teto da delegação**: o limiar é a **repetibilidade do
   dono**, não 100 % (arXiv 2510.07978). Por isso o id é estável.
5. **O `heldout2` está contaminado** (6/24 com fala de treino, 19/24 com
   quase-duplicata): **nunca** comparar versões nele; use o `heldout3`.
6. **Um timeout que corta o rótulo produz veredito inválido.** O
   `classify_turn` devolve `TIMEOUT` (distinto de `None`) e o caller/log
   separam *"demorou"* de *"respondeu errado"*.
7. **Concordância baixa não é evidência de dado ruim** (arXiv 2603.06865): é
   ambiguidade de instrução. O `why_dono` existe para tornar a divergência
   diagnosticável.

## 3. Quando o dono diz "não estou vendo acontecer"

A máquina está pronta; **o gargalo é o dado humano**. Verifique, nesta
ordem, sem refazer trabalho:

```bash
ls -la data/judgments/labels.jsonl     # o registro existe? (sem ele, nada mede)
python3 scripts/seletor-fracas.py      # qual item julgar primeiro
python3 scripts/judgment-bench.py --data data/judgments/labels.jsonl
```

O dono precisa de **~50 labels**: os **20 itens de prática** já existem
(`data/judgments/uhrs-practice-items.jsonl`, ids `p01..p20`, com 6 da classe
que o gate erra) e o resto vem da **qualificação do UHRS** (que ele já tem
que fazer, e paga). Depois das labels, o fluxo é o **runbook**:
[`docs/auditoria/RUNBOOK-DELEGACAO-2026-11-25.md`](../docs/auditoria/RUNBOOK-DELEGACAO-2026-11-25.md)
(judigar por voz, `--make-heldout`, dataset, treino, bench, e o que fazer com
o número).

## 4. O que NÃO se faz aqui

- Não se automatiza clique ou resposta em conta de terceiro.
- Não se treina no gabarito (ver 2.3).
- Não se publica o `key` do gabarito no `state` do treino.
- Não se compara kernels no `heldout2`.
