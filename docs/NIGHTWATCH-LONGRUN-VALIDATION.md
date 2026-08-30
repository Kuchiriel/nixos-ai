# Nightwatch Long-Run Validation

## 2026-08-29 — Validação Real

### Protocolo Executado

1. **Dry-run** (`use_llm=False, use_scripted=True, max_tasks=10`)
   - 10 tasks descobertas via scanner scripted
   - 10 skipadas (dry-run)
   - Duração: 21.5s
   - ✅ Discovery funciona

2. **Real run** (`use_llm=False, use_scripted=True, max_tasks=3, max_minutes=5`)
   - 3 tasks executadas
   - 3 falharam (LLM offline — sem patches)
   - 0 commits
   - Duração: 8.7s
   - ✅ Pipeline funciona (fail correctly when LLM unavailable)

### Estado do Task Queue

```
READY:          27
ABANDONED:      10
IN_PROGRESS:     2
FAILED:          1
Stuck (>1h):     0
```

### Correções Aplicadas

1. **`_fail_task()`** — persiste estado imediatamente no disco
2. **`recover_stuck_tasks()`** — chamado no `__init__` do Harness
3. **LoopDetector** — inicializado corretamente (bug fix anterior)

### Limitações Conhecidas

1. **LLM offline** — tasks scripted que precisam de patches falham corretamente
2. **Sem validação >30min** — requer LLM rodando
3. **LoopDetector state** — in-memory only, perdido no restart

### Próximos Passos

1. Rodar com LLM online por 30+ minutos
2. Validar context budget auto-detect
3. Validar checkpoint/recovery após crash simulado
4. Integrar LoopDetector ao task_queue persistente

### Critérios de Sucesso

| Critério | Status |
|----------|--------|
| Discovery gera tasks | ✅ |
| Pipeline executa (fail gracefully) | ✅ |
| State persiste no disco | ✅ |
| Stuck tasks recuperados | ✅ |
| Loop detection funcional | ✅ |
| >30min sem intervenção | ⏳ Requer LLM |
| Context budget auto-detect | ⏳ Requer LLM |
