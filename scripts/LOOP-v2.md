# LOOP v2 — melhorias contínuas enquanto o dono dorme

> Substitui o LOOP v1 (dois agentes). Aqui é UM agente, método fechado,
> e a pergunta que responde a cada ciclo: **o que falhou é o modelo ou é
> o harness?** Nunca decide por palpite.

## Por que este loop existe (contexto medido)

- Harness está **saturado** para o bonsai: **12/12** em easy+medium+hard+ptbr
  (commit 7afc804, evidência `scripts/overnight-24-09/`). Não dá para
  "melhorar o harness" medindo no mesmo conjunto: o instrumento perdeu
  resolução.
- Então o ciclo é: **endurecer o instrumento até o modelo fraco falhar**,
  medir *por que* falhou, e **trocar o modelo** no MESMO conjunto para
  separar as causas.

## Método por ciclo (obrigatório nesta ordem)

1. **Teto do modelo pequeno.** `bonsai` (ternário, 72 t/s, 0.0 temp) é o
   kleinste model. Rodar o harness completo. Se ele passa tudo: o harness
   saturou → passo 2.
2. **Endurecer (gates novos).** Adicionar 1 challenge por vez que o bonsai
   **deve** falhar segundo a doutrina, e que o harness **deve** pegar
   mecanicamente (world-state verificável, sem juiz de LLM). Prioridades
  Known, por evidência:
   - contexto longo dentro do REPL (o modelo tem que degradar e o harness
     tem que compactar/avisar — sem quebrar)
   - `search_then_read` (achar o arquivo certo antes de ler)
   - *fato vs opinião* (o CRPS virou métrica de ML quando o system prompt
     ficou sem perfil: isso é falha de FRAMING, harness)
   - tarefa multi-arquivo com estado (criar, alterar, reexecutar)
   - recusa indevida (over-refusal) — já existe `legit`, falta放宽
3. **Atribuir.** Para cada falha nova, rodar a MESMA task em:
   - `bonsai` (ternário, 0.0) — floor
   - `Qwen3-4B` (denso, 0.7) — meio
   - `moe` (35B MoE, 0.7) — teto
   Regra de leitura: **falha só no pequeno = modelo**. **Falha nos três =
   harness**. **Falha só no grande = prompt/framing**.
4. **Corrigir a camada certa.** Preferência mecânica antes de prompt
   (L8: "texto não contém, mecanismo sim"). Cada fix vai em commit
   path-limited com o número do challenge na mensagem.
5. **Medir de novo** e registrar em `docs/benchmarks/MODEL-HARNESS-MATRIX.md`.
6. **Literatura** (arXiv + `~/Books` + web) quando o sintoma tiver nome
   conhecido: `lost in the middle`, `instruction stacking`, `persona
   drift`, `sycophancy`. Registrar o que muda no prompt/harness, com a
   citação.

## Regras do loop (inegociáveis)

- **Nunca** alterar binário do modelo sem medir antes e depois
  (`scripts/bench-llm.sh`).
- **Nunca** declarar "o harness está ótimo" sem o nome do modelo no veredito.
- **Nunca** contar score com infra caída: o `preflight` aborta; se ele
  abortar, é incidente de infra, não resultado.
- 1 LLM por vez na 6GB (guard do `jarvis space serve`).
- Commit por ciclo, com o número do challenge e o antes/depois.
- Se um ciclo não produzir mudança no harness ou no registro, o ciclo
  parou — não encher commit.

## Fila que o loop herda (25/09)

- [ ] gates novos (passo 2) — o instrumento precisa voltar a ter resolução
- [ ] modelo×harness matrix com `moe` (35B) nos gates atuais
- [ ] `--rounds 2` já é o padrão do verifier-in-the-loop; medir se 3 ajuda
- [ ] `nvidia-smi` + RAM 24/31 com o MoE: OOM killer matando chromium
      (não é o loop, mas é risco de freezer —TL;DR no STATE)
- [ ] purge do `code_index` (604 pts pessoais) — **SÓ** depois da perícia
      (28/09), com o comando `jarvis space purge`

## Como o loop continua sozinho

`scripts/loop-runner.sh <N> <modelo>` executa N ciclos do passo 1-3,
registrando em `scripts/overnight-24-09/loop-STATE.md` e
`loop-<modelo>-<ts>.json`. Só mexe em `scripts/` e `docs/benchmarks/`.
Nada de serviço, nada de rede sem OK, nada de push sem commit local.
