# PAINS — incidentes e erros medidos

> Entradas manuais dos agentes; o scanner de erros (`agents-watcher` scan-apply)
> acrescenta assinaturas automaticamente. Formato: data · lane · sintoma · causa ·
> fix · verificação.


## 2026-11-12 · duplex (lane direta do dono) · 4B OOM sob geração em massa

- **Sintoma:** `llama-uncensored-4b.service` (jarvis-mtp-lora :8092) morto pelo OOM
  killer (`status=9 KILL`, `failed with result 'oom-kill'`), 17:10. O duplex
  (scripts/duplex-voice.py) passou ~4 min sem gate: `classify()` retornava None,
  o turno caía no fallback (`intent=None`, `gate=False`) e o JARVIS ficou mudo.
- **Causa medida:** esta sessão disparou geração em massa de corpus PT-BR contra
  o :8092 (4 processos no pico, cada um com `n_predict=1400`, `temperature=1.0`),
  sem verificar `is_processing` no `/slots` antes de enfileirar. O servidor é
  single-slot (`--parallel 1`) + MTP speculative + LoRA, memory cap real; o
  pico registrado pelo próprio unit foi 5.9G (> MemoryHigh) e o cgroup-swap (2G).
  A contribuição da sessão: dezenas de gerações de ~1-2 min seguidas +
  retry-storm de 503 no caminho (cada retry ocupava o slot de novo).
- **Fix imediato:** kill dos geradores; server auto-restart ok (is-active active,
  porta 8092 OK às ~17:14); corpus passou a ser gerado por expansão combinatória
  determinística (zero carga no servidor) + arquivo de clips reais já rotulados.
- **Fix definitivo:** nenhuma geração em massa contra o :8092 nem contra o :8080.
  Lotes contra servidor LLM local single-slot só com (a) /slots com
  is_processing=false antes de enfileirar, (b) n_predict ≤ 420,
  (c) sleep ≥ 1s entre lotes, (d) no máximo 1 instância, (e) monitorar
  `systemctl is-active` + `VmRSS` do unit; abortar ao primeiro sinal de pressão.
- **Verificação:** unidade ativa + porta 8092 aberta + duplex classify respondendo
  (ver log do duplex 2026-11-12). Lição operacional reforçada: 4G/6G do duplex já
  é apertado; o whisper + LoRA + MTP não deixam margem para 1 token a mais.
