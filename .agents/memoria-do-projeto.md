# Memória do projeto (CARREGUE SÓ SE O GATILHO CASAR)

Gatilhos: já quebrou, antes de mexer, armadilha, por que, decisão.

## Princípios que já custaram caro
1. **Regra em prosa não protege.** Escrevi "nunca apagar" no AGENTS.md e
   quebrei a minha própria regra no mesmo dia. Mecanismo + ponto de
   entrada é o que protege.
2. **Instrumento que não desconfia de si mede a coisa errada com
   confiança.** Três vezes hoje: VRAM "medida" com outro modelo no ar;
   veredito de "inglês" aceitando texto em português; sweep medindo com
   contenção. Antes de aceitar número, teste que ele **reprova** o que
   deve reprovar.
3. **Filename é hipótese, metadata é fato, bench é veredito.** O
   `PQ2_0` em disco era v1 (arquitetura `qwen35`).
4. **Mede antes de trocar de modelo.** Toda vez que ganhei hoje, o ganho
   foi de bug de harness, não de modelo.
5. **Só troque de tier ao bater teto real.** O teto aqui é VRAM, não
   parametrização: o 8B ternário (72 t/s) ganha do 4B (61) e do MoE (40).

## Decisões do dono
- Nunca apagar: verificar → consolidar → **arquivar** com veredito em
  commit. `archive/<assunto>-AAAA-MM-DD/`, sempre com data.
- "Decisões minhas sempre viram pesquisas na web/academia e padrões de
  mercado; eu não decido essas coisas."
- Toda descoberta nova: registrar em **memória** (o que muda decisão) e
  **vault/`docs/`** (o que é referência).
