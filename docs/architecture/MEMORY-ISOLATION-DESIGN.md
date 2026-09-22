# MEMORY ISOLATION DESIGN (P1 — evidência 22/09: isolada 3/3 vs 0/3)

Problema: coleção `memories` compartilhada acumula junk multi-task;
recall top-k mistura episódios irrelevantes; lessons boas afogam.
Evidência: mesma task B3 → 0/3 compartilhada, 3/3 isolada.

Opções:
A. Coleção por task/domínio (routing por prefixo): isolamento total,
   custo = N coleções + routing rule. Simples, testável.
B. Poda por idade/uso (forget_task estendido): TTL +contador de uso;
   recall pondera recência×uso. Mantém 1 coleção.
C. Híbrido (recomendado): namespaces lógicos (payload.tenant) +
   filtro obrigatório por tenant no recall + poda de registros antigos.
   Sem migração: filtro default = tudo (compat), opt-in por task.

Experimento p/ validar antes de implementar: A/B recall-precision em
compartilhada vs isolada (n=20 queries, P/R manual) — CPU-only, sem GPU.
Não mudar runtime antes disso.
