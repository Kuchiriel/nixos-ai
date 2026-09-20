# ARCHITECTURE FINDINGS (20/09 — §56: correto também se registra)

F1. Agent.run não chama RAG (VERIFIED código): conhecimento chega via
lessons auto-inject + aumento de prompt router/dev + CLI/MCP. "RAG
funciona" ≠ "RAG usado" — EXP-A prova o elo presentation→behavior.
F2. Lessons auto-inject é o mecanismo primário (VERIFIED código+EXP-C):
delivery funciona; conteúdo com números episódicos prejudica (B2 1/3 vs
B3 3/3) — regra value-free (§15).
F3. "MANDATORY recall" é advisory (VERIFIED EXP-E): modelo não distingue
recall↔lessons na seleção (0/3 sistemático).
F4. Dois loops divergem em garantias (VERIFIED código): core evidencia,
dev retorna texto sem verdict. Correto por desenho; risco documentado.
F5. Completion/world_check veta texto (VERIFIED código+testes): barreira
anti-false-green real; furo era stale pré-setup (FIXED com flag).
F6. Três esquemas de tools + approval gap MCP (VERIFIED código): boundary
a classificar, não afrouxar (§51).
F7. Modelo pequeno: atração por números + read-first + variância
(VERIFIED exps): teto de presentation; resto é harness (F2-regra, F5).
F8. approval_callback construtor morto (VERIFIED código): remover ou ligar.
F9. Correto e NÃO mexer: strict-tier, killpg, quarantine gate, registry
hard-fail capabilities, shlex-no-shell, STUCK honesto.
