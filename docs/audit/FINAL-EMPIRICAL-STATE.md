# FINAL EMPIRICAL STATE — RED TEAM CYCLE 2 (20/09)

Model: bonsai (PrismML ternary 8B) via :8080 salvo menção. n por braço
anotado. Método: EvalHarness world_check externo; paths únicos + rmtree
pré-run; exemplos neutros. Coleções de memória isoladas (`exp_*`), a
compartilhada `memories` intocada. Sem push (27+ ahead local).

## 1. PROVEN (VERIFIED, replicado)
- RAG→behavior: C2 3/3 e replicado n=5 5/5; controles 0/16 em 3 docs ×
  3 formulações × 3 formatos (EXP-A + R1). Generalização: NÃO
  memorização de benchmark.
- Entropia MCP, não capacidade: E2-only 9/9 (git/vault/recall), E1/E3
  falham quando read_file no menu (EXP-E2/D2).
- Lessons com valores episódicos prejudicam: B2 1/5 vs value-free 3/3
  (EXP-C + R2). Mecanismo H-C8 (números lidos como atuais).
- Lessons/RAG com números no contexto PUXAM o modelo (EXP-C, F8).

## 2. STRONGLY INDICATED
- Menor-condição: F0 0/3, +lesson 1/3, +lesson+RAG-exemplo 0/3 — mais
  contexto ≠ melhor; cada substrato injeta seus números.
- Self-knowledge: grounding (ler arquivo) funciona (Gb 2/3); sem leitura
  = adivinha plausível (Ga 0/3) e materializa (criou hybrid_search.py).

## 3. INCONCLUSIVE
- H two-loop: code-verified (dev loop rc=0 em texto, sem completion
  gate), sem experimento comportamental destrutivo (jail de repo).
- Replicação n=5 parcial (variância em task D).
- Lesson creation: não sistemática (só shell exit!=0).

## 4. FAILED
- Lessons value-heavy (1/5), RAG-exemplo em chain (0/3), F8 interação.
- Vault/Git quando read_file disponível (0/6).

## 5. FIXED (executável + teste)
- Provider sem choices → STUCK honesto (não IndexError).
- Lessons outage → `lessons_unavailable` JSONL (não "" silencioso).
- stale-artifact flag em run_task (EXP-C falso-verde).
- Testes herméticos sandbox (rebuild Layer5 verde).

## 6. FIXED IN HARNESS
- Rerank fallback silencioso (documentado), completion evidence-gated,
  approval gap MCP (documentado como boundary, NÃO afrouxado).

## 7. MODEL-LIMITED
- Alucinação sem grounding (0/16 controles), atração por números,
  read-first bias, variância (0/9 world-exact histórico), scaffold
  collapse em JSON (paper not-the-size).

## 8. KNOWLEDGE-LIMITED
- Lessons value-free (representação), RAG discovery→filesystem truth.

## 9. MCP/TOOL-TAXONOMY-LIMITED
- Confusão recall↔lessons (verbo-dependente), entropia read_file.
  Restrição/divulgação progressiva = alavanca real.

## 10. CONTEXT-LIMITED
- Cada substrato adiciona números (F); mais ≠ melhor.

## 11. EVALUATOR-LIMITED
- stale-artifact (fixed); variante/wording decide (anti-gaming:
  variar é obrigatório); n=1 não decide (H1).

## 12. GENERALIZA BEYOND L8
- Lesson value-free, MCP entropia→disclosure, outage≠nada, grounding
  auto-verificação, mais-contexto≠melhor.

## 13. NÃO GENERALIZA
- Fato único em doc (depende do doc existir/indexado).

## 14. REGRESSION TESTS
- empty-choices STUCK, lessons-outage, stale-artifact (adicionados).
  Próximos: value-free lesson lint, MCP disclosure p/ bonsai.

## 15. NÃO MUDAR AINDA
- Implementar disclosure automática (testar E6 1º); rewriting loops
  (provar divergência 1º); finetune/Qwen/MoE (dono).

## 16. PRÓXIMA FRONTEIRA
- Progressive disclosure (E6) + plano-âncora explícito (not-the-size:
  plan/recover ~50% ganho SLM) + lessons value-free por construção.

## PERGUNTA FINAL — capacidades novas demonstradas (world-observable)
1. Pega um fato ausente do contexto/pesos e o USA para acertar ação no
   mundo (0→3/3; replicado) — SE o conhecimento for entregue
   (RAG/prompt). NÃO o faz sozinho no loop.
2. Escrita guiada por grounding (Gb) em vez de palpite, quando lê.
3. Falha legível em outage/crash (STUCK honesto, lessons_unavailable)
   em vez de "" / exceção crua — ANTES este sistema crashava ou mentia.
4. Verificação por evidência (world_check) que o agente-por-texto não
   tinha — valor do harness, não do modelo.
Conclusão honesta: a maior parte do ganho ainda é HARNESS
(verificação/representação/entropia/outage), NÃO o modelo; o
conhecimento (RAG/lesson) só move comportamento quando representado e
entregue sem números parasitas. Isso é a descoberta central.