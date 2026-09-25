# Loop e benchmark (CARREGUE SÓ SE O GATILHO CASAR)

Gatilhos: loop, overnight, harness, bench, sweep, cmoe, t/s, ngl, tokens.

## Método
`scripts/LOOP-v2.md` é a fonte. Ordem: modelo pequeno até o teto →
endurecer o instrumento (gate novo) → **atribuir** (mesma task em
bonsai/Qwen4B/MoE: só no pequeno = modelo; nos três = framework) →
corrigir a camada certa (mecânica antes de prompt) → medir → literatura.

## Ferramentas
- `scripts/loop-runner.sh <ciclos> <modelo> [tier] [rounds]`
- `scripts/harness-suite.py` (preflight, verifier, rounds)
- `scripts/vram-split-sweep.py` — **recusa medir** se houver outro
  `llama-server` vivo. Contenção já custou uma investigação de um
  "bimodal" que não existia.
- `scripts/memory-arena-lite.py` — uso ativo, veredito mecânico.
  Veredito tem que **reprovar** o que deve reprovar: um check frouxo
  infla o número sem reclamar.
- `scripts/bench-llm.sh` — canônico (os legados estão em `scripts/archive/`).

## Regras de veredito
- Score sempre **por modelo + binário + flags + harness**.
- n=1 não decide; n alto com poucos itens mede repetição, não mecanismo.
- Nunca afirmar "rodando" sem `pgrep` + log + evidência `TOTAL`.
- Falha de atributo vai na **primeira causa causal**, não no sintoma.
- O `--mlock` nos perfis MoE **não tem ganho medido** (as runs estouraram
  timeout). Está por coerência, não por evidência.

## Medido nesta máquina (25/09)
`8B Q2_0 72,3 t/s` · `4B denso GPU 61,0` · `MoE 35B cmoe41 40,3`.
Threads: `-t6 16,4` · `-t8 14,1` · `-t10 10,4` · `-t12 7,9` (denso CPU).
