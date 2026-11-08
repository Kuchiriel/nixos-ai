# Melhorar ferramentas e datasets do Applio

- **sessão:** `ses_f4f25c654ffeYDezRr1imUYob0`
- **quando:** 2026-09-17 19:31 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 108 (exportadas: 34)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

~/projects/applio-labs ler toda docs desse repo, depois usar jarvis recall e outras features do jarvis para reaver dados do projeto, já deve ter mapeado no projeto, mas arquivos necessários em ~/Audio ~/Books e ~/Models, objetivo, melhorar todas ferramentas, para que tenhamos datasets mais limpos, sem intrusos ou artefatos, melhorar tagueamento automático de personagens, melhorar verificação automática de arquivos wavs para cruzar com o timbre dos modelos de voz, enfim, leia tudo que der que você vai entender, e pesquise na internet na dúvida, se tiver algo sendo feito de errado ou alguma dica na internet, teste a hipótese, deve estar lá, mas é utilizado kokoro onnx, fish, xtts, applio, rvc, perfis de personagens, sistema de stt/tts, diarize, fatiamento, se achar que ta bagunçado demais pode criar uma documentação que explica melhor, ou melhorar as existentes

---

## · ?

~/projects/applio-labs ler toda docs desse repo, depois usar jarvis recall e outras features do jarvis para reaver dados do projeto, já deve ter mapeado no projeto, mas arquivos necessários em ~/Audio ~/Books e ~/Models, objetivo, melhorar todas ferramentas, para que tenhamos datasets mais limpos, sem intrusos ou artefatos, melhorar tagueamento automático de personagens, melhorar verificação automática de arquivos wavs para cruzar com o timbre dos modelos de voz, enfim, leia tudo que der que você vai entender, e pesquise na internet na dúvida, se tiver algo sendo feito de errado ou alguma dica na internet, teste a hipótese, deve estar lá, mas é utilizado kokoro onnx, fish, xtts, applio, rvc, perfis de personagens, sistema de stt/tts, diarize, fatiamento, se achar que ta bagunçado demais pode criar uma documentação que explica melhor, ou melhorar as existentes

---

## · ?

Tenho o quadro completo. Resumo do que encontrei e do plano:

**Estado (verificado no disco + recall):**
- Pipeline: parse → `attrib-llm` (proposta) → `review-grounded` → **loop nunca fecha** (28 caps têm `-llm.json`, só 1 tem `-rev.json` e está vazio `{}`; nada aplica vereditos grounded nos caps)
- `dataset-audit.py` é **auto-referencial** (centróide do próprio dataset) — não cruza com as refs reais de timbre que já existem (`~/models/timbre-refs/`: audrey, azik, benson, derek, melissa)
- Não existe ferramenta de **verificação por-wav ↔ timbre** (timbre-matrix precisa de um dir e imprime matriz, sem veredito PASS/FAIL por personagem)
- Bug menor: `nightly-audit.sh` diz "timer 03:30" mas o timer real é 01:00

---

## · ?

Agora as melhorias no `dataset-audit.py`:

---

## · ?

Agora o `apply-llm.py` — fecha o loop de atribuição (vereditos grounded só entram com evidência verbatim verificada por código):

---

## · ?

O dry-run funcionou e expõe valor real: **63 candidatas grounded** (evidência verbatim) vs **231 rejeitadas** (anti-alucinação pegando de verdade). Mas notei um problema: o LLM propõe KLEIN com evidência de **narração 3ª pessoa** ("Klein acenou em afirmação") — violando a própria regra 3 do prompt. Vou adicionar o gate de verbo de fala no apply-llm antes de testar. Primeiro deixa eu ver como o render trata UNKNOWN:

---

## · ?

continue

---

## · ?

UNKNOWN renderiza com voz fallback (lotm-audiobook.py:451) — então aplicar vereditos corretos melhora, mas aplicar KLEIN em narração piora. Adicionando o gate de verbo de fala:

---

## · ?

O gate está correto segundo a doutrina (atribuição explícita DECIDE; resto fica na review-queue p/ ouvido do dono). Deixa eu ver o quadro completo, incluindo NARRADOR:

---

## · ?

O gate pegou problemas nos NARRADOR: o LLM propõe NARRADOR para DIÁLOGOS ("Haha, Klein, você é realmente bem-humorado" — 2ª pessoa). Deixa eu verificar os dados antes de fechar o design:

---

## · ?

Achei o furo: o LLM propõe NARRADOR para diálogos entre aspas ("Nada mal." / "Haha, Klein, você é...") e o gate atual deixaria passar. Fechando o design com 3 gates: adjacência verbo+nome, gate de 1ª/2ª pessoa para NARRADOR, e mínimo de 4 palavras na evidência:

---

## · ?

Bug achado: `_TOKEN` divide só em pontuação, não em espaço. Corrigindo:

---

## · ?

9 candidatas sólidas, todas com atribuição explícita. Verificando a única não-óbvia (cap22 [45]) antes de aplicar:

---

## · ?

Legítima ("disse Rozanne"). Aplicando os 9 com backup + validação:

---

## · ?

`validate-caps.py` tem VALID_SPK dessincronizado com o elenco do attrib-llm (CARTOMANTE existe desde ep1 — cartomante-chefe). Corrigindo:

---

## · ?

ERROS: 0 — os 10 aplicados são válidos. Agora testando `timbre-check.py` em dados reais:

---

## · ?

Os hunts são wavs mistos (personagem + entrevistador) — a ref é do cluster puro, então wav inteiro dá cos baixo (esperado). O alvo da ferramenta são **clips**. Testando em clips do dataset benson-v1:

---

## · ?

**Achado importante**: TODOS os clips benson-v1 falham contra a ref do hunt (cos 0.26-0.45) — confirmando o aviso do ROADMAP (dominância do hunt pode ser o entrevistador). Testando com a ref **verificada por ouvido** (melissa pick 1 = 230Hz) p/ calibrar o limiar:

---

## · ?

Mais um bug exposto: `timbre-ref.py` com `--pick` salva o .npy do cluster escolhido mas **não atualiza o F0 top-level** (melissa ficou 149Hz = cluster errado; o pick 1 verificado = 230Hz). Corrigindo os dois:

---

## · ?

Com a banda corrigida, a ref verificada discrimina direitinho (5 PASS com cos 0.71-0.82 + F0 na banda). Agora o `dataset-audit.py` melhorado — testando com `--fresh` em melissa-v1 (exercita o cruzamento com ref real) e christina-v1:

---

## · ?

O detector de duplicados pegou 4 reais (os `ref-*.wav` são aliases dos `ep*.wav` — o audit velho nunca pegou). Mas `keep_minutes` é calculado antes da passada de duplicados — corrigindo a ordem:

---

## · ?

Minutos corrigidos (duplicados fora da contagem). Agora o fix do `nightly-audit.sh` e a documentação:

---

## · ?

Checagem final de sintaxe em tudo que foi tocado + nota de sessão:

---

## · ?

Feito. Resumo da sessão:

## Lido + reavado
- Toda a docs do repo (AGENTS, ROADMAP, PENDENCIAS-AGORA, MAPA-VOZES, APRENDIZADOS, AUDIOBOOK-ARCH, DELEGACAO, BACKLOG...) + `jarvis recall` (8 fatos, incluindo auditoria 48/48 datasets e o gate FALANTE de ontem)
- Estado do disco: `~/Audio` (23G, 48 datasets), `~/models` (timbre-refs, merges, fish-s2, rvc-assets), `~/Books` (9 vols LotM)

## Ferramentas novas (testadas em dados reais)
1. **`scripts/timbre-check.py`** — verificação por-wav ↔ timbre real do personagem: `--char benson` → PASS/FAIL-F0/FAIL-TIMBRE com cos + banda F0; `--best` taggeia wav desconhecido contra o vault de refs. Exit 1 = integrável no nightly. Testado: melissa (ref verificada) discrimina 5 PASS cos 0.71-0.82.
2. **`scripts/apply-llm.py`** — fecha o loop de atribuição que estava aberto (28 caps com propostas, nada aplicava). 3 gates: evidência verbatim byte-a-byte, verbo de fala + nome **adjacentes**, NARRADOR só em narração pura. Medido: **10 aplicados / 384 rejeitadas** (anti-alucinação pegando de verdade), `validate-caps` 0 erros, backup automático.

## Melhorias nas existentes
- **`dataset-audit.py`**: cruza agora com refs reais (`timbre-refs`), detecta **clipping**, **duplicados** (pegou 4 reais — `ref-*.wav` eram aliases de `ep*.wav` que o audit velho nunca pegou) e escreve relatório global datado. Backup dos 48 audits antigos feito.
- **`timbre-ref.py`**: F0 top-level agora segue o `--pick` (bug: melissa guardava 149Hz do cluster errado; corrigido p/ 230Hz — seu veredito).
- **`validate-caps.py`**: +CARTOMANTE/VENN/WENDY/ANNIE (flaggiava atribuições válidas como corrupção).
- **`docs/TOOLING.md` novo** — mapa único: o que cada ferramenta faz, evidência, quando usar, armadilhas provadas. AGENTS.md aponta pra ele.

## Achados que exigem você 🎧
1. **Refs de timbre suspeitas**: benson (109Hz) falha 100% nos próprios clips do dataset; derek 242Hz é F0 feminino p/ personagem masculino; azik 220Hz. Rodar `timbre-check` + decidir `--pick` por ouvido.
2. 5 duplicados novos marcados (melissa-v1 ×3, christina-v1 ×2) — confirmar expulso.
3. Kaggle: dunn-rvc-train **RUNNING** na O2 — quando COMPLETE, rodar `kaggle-dunn-fetch.sh`.

Nada commitado (mudanças no git index para você revisar).

---

## · ?

vc viu a bagunça que tá tudo isso, todos diretorios e arquivos envolvidos, consegue organizar, consolidar e testar tudo?

---

## · ?

Vou mapear tudo primeiro (o que referencia o quê), classificar ativo × obsoleto, organizar e testar. Inventário completo:

---

## · ?

Tenho o mapa de dependências. Plano: limpar lixo, arquivar relatórios pontuais em `docs/arquivo/`, mover one-offs para `scripts/`, consolidar BACKLOG→PENDENCIAS-AGORA, atualizar AGENTS.md e testar tudo. Executando:

---

## · ?

Agora consolidando BACKLOG → PENDENCIAS-AGORA (fila única de verdade):

---

## · ?

Índice do arquivo + AGENTS.md atualizado:

---

## · ?

Sem referências quebradas. Agora a bateria de testes completa:

---

## · ?

Contrato lido. Rodando o smoke test oficial do contrato (caminho Edge, rápido) + testes funcionais:

---

## · ?

Tudo organizado e testado. Registrando na SESSAO e na memória:

---

## · ?

Organizado, consolidado e testado. Resumo:

## Antes → Depois
```
Raiz: 44 itens → 16 itens (só ativo)
```

**Lixo removido**: `&&`, `>`, `echo/`, `key=value/` (vazios, criados por comandos quebrados) + `__pycache__/`

**Arquivado em `docs/arquivo/`** (12 docs, com INDEX.md dizendo o que era cada um — nada perdido):
- Relatórios pontuais: FASE2, MISSAO-CHATGPT, RELATORIO-MISSAO-15/09, P0-RECONSTRUCAO
- GLM: PEDIDO-GLM-DUNN, RECADO-GLM, RECOMECAR-GLM
- Planos: MODEL-CHOICE-PLAN (testes A/B/C nunca rodaram), SPECIALIST-MODELS, RECEITA-JARVIS
- **BACKLOG.md → consolidado dentro de `PENDENCIAS-AGORA.md`** (fila única de verdade; original salvo como `BACKLOG-consolidado.md`)
- `dataset-metadata.json` (stray do Kaggle)

**One-offs → `scripts/`**: kaggle_cell1/2/3, pureza-pools, verify_patches, chain-cap01, loop-klein-only

**Raiz final** = só o ativo e referenciado: AGENTS, PENDENCIAS-AGORA, ROADMAP, AUDIOBOOK-ARCH, LOTM-MAPA-VOZES, SESSAO + lab-env.sh, lotm-pipeline.py, lotm-audiobook.py, lotm-voices-pool.json — verifiquei as dependências absolutas antes de mover, zero referências quebradas (grep confirmou).

## Testes (todos verdes)
| Teste | Resultado |
|---|---|
| Smoke do contrato (Edge E2E) | WAV 419KB > 100KB ✓ |
| `validate-caps.py` | 0 erros / 60 avisos (fila) |
| `apply-llm.py` idempotência | 0 novas candidatas; 140 fora = 130 + 10 já aplicados ✓ |
| `dataset-audit.py` resume | "nada a fazer" (48/48 auditados) ✓ |
| `timbre-check.py` melissa | 5 PASS / 7 FAIL (igual pré-org) ✓ |
| Sintaxe | 61 .py compilam + todos .sh passam `bash -n` |

## Não tocado (doutrina)
- `personagens/`, `lotm-voices.json`, `presets/` (docs vivos do dono)
- `Applio/` (repo próprio, stack RVC persistente), `hd-import/sound_effects.json` (consumido pelo sfx-scan)
- `pool-gate.py` não rodou completo (já validado no pool v5, e1caa7c; demora ~10min de síntese)

Renomeações estão em stage (`git mv`) — commit quando você pedir. AGENTS.md e SESSAO atualizados com o novo mapa.

---

## · ?

também temos ~/Audio ~/Books e ~/Models pra organizar, só não toque nos models gguf, esses dir não são repos, então cuidado na organização e consolidação, sem delete, só archive com mv e justificativa, espero que tenha atualizado a documentação do repo applio-lab e usado jarvis remember e vault, e espero q faça o mesmo com esses tres dir que mencionei envolvidos no projeto de audiobook

---

