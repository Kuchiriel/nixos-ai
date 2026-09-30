# Prompt de reidratação (pode colar após compactar)

> Salvei no repo pra ele também sobreviver. Copie o bloco abaixo.

---

```
Reidrata o JARVIS. Não preciso explicar nada — lê em disco, é rápido.

1. Estado da sessão (lê antes de agir):
   nix develop --command python3 scripts/session-primer.py

2. Método e regras que valem (ler, não inventar):
   .agents/harbor-e-harness.md   # como rodar Harbor/trials
   AGENTS.md                    # regras da casa (nunca apagar, fontes de verdade)

3. O que aprendemos ontem (30/09) — 8 lições, a mais importante é a #1:
   docs/LESSONS-2026-09-30.md

4. Placar vivo do harness (por modelo/task):
   docs/harbor/INDEX.md

5. Onde o projeto está agora:
   docs/TIERS-E-PAPEIS.md    # tier ≠ nota bruta; pipeline refutado
   docs/harbor/INDEX.md      # nightwatch: 0/3, falha 2 em pé
   docs/LESSONS-2026-09-30.md # checkpoint + pendências abertas

Próximo passo técnico combinado: **falha 2 do patcher** (old_text não
casa com o arquivo real) — é o que destrava o nightwatch a se
auto-corrigir de verdade (loop RHO, arXiv 2606.06324).

Duas regras que eu pedi e valem pra qualquer coisa que você fizer:
- **Verifier primeiro**: todo expected numérico é derivado do fixture
  por código, nunca escrito à mão (já quebrei isso 3×).
- **Não adaptar o runtime pra passar numa task**: otimizar o
  instrumento é a forma mais eficiente de mentir pra si mesmo.

Roda o primer, me confirma o que achou, e seguimos pela falha 2.
```

---

## Notas

- **Se eu não conseguir ler** (sem rede, path errado), diga só:
  `cd ~/projects/nixos-ai && nix develop --command python3 scripts/session-primer.py`
- **Se preferir ainda mais curto**, o mínimo que me localiza:
  `cd ~/projects/nixos-ai && leia AGENTS.md + docs/LESSONS-2026-09-30.md e siga o checkpoint.`
- O `session-primer.py` é idempotente e rápido (sem LLM, só disco),
  então pode rodar quantas vezes quiser — mas o prompt acima já me faz
  rodar sozinho, sem você tocar em nada.