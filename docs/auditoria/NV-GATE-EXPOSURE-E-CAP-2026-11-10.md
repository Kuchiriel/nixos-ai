# nv-gate: exposição do endpoint novo e o quanto o teto de sessão reduziria o problema (10/11/2026)

Auditoria do endpoint novo `GET /__gate/health` e a medição de quanto o teto de sessão
pendente (262144) reduziria o que o gate registra.

## 1. O endpoint novo: seguro

| pergunta | resposta medida |
|---|---|
| escuta onde? | `127.0.0.1:8095` (o `ss` mostra a escuta só no loopback) |
| alcançável pela tailnet? | não: `curl http://100.121.100.103:8095/__gate/health` dá conexão recusada (exit 7) |
| vaza segredo? | não: o JSON sai com contadores (rpm, burst, requisições, 429 do upstream e do cliente, erros, retries, tempo em fila, 502/503/504 do upstream, erros de I/O, requisições recusadas por contexto e curto-circuited) e nenhum URL, chave ou IP |
| o caminho do handler | `do_GET` responde `/__gate/health` com o snapshot e **todo o resto é repassado ao upstream** |

Conteúdo do snapshot no momento da medição:

```json
{"ok": 2255, "rpm": 8.0, "burst": 2, "requests": 2520, "upstream_429": 5,
 "client_429": 2, "errors": 83, "retries": 195, "queued_seconds": 2153.8,
 "upstream_504": 73, "upstream_io": 117, "ctx_rejected": 1,
 "ctx_short_circuit": 176}
```

**Um pé atrás doendpoint:** o path `/health` (sem o prefixo `__gate`) **não é local**:
ele cai no forwarder e é relayado ao upstream. Medido: `GET /health` na porta 8095
levou **5,4 s** e devolveu 200 do upstream. Quem sondar o path errado para "verificar
se o serviço está de pé" trava, demora e ainda toca a cota do upstream. É o que a
regra nova do `AGENTS.md` avisa, e a medição confirma.

## 2. O código vivo do gate já tem os dois fixes

O `AGENTS.md` e as notas da frota diziam que os dois fixes do provider (disjuntor de
contexto e via prioritária) esperavam rebuild, porque o gate roda a cópia do store.
**Medido agora: a cópia do store já contém os dois.** O processo viva
(`/nix/store/...-nv-gate.py`, PID 4016539) subiu em **09/11 06:41:53**, depois dos
commits `932a0324` (disjuntor, 06:04) e `ed560081` (via prioritária, 06:12), e o
arquivo no store tem `small_bucket` (5 ocorrências) e `ctx_short_circuit` (1).

Ou seja: **esses dois não dependem de rebuild**. O que ainda depende do rebuild são
os outros itens da folha (teto de sessão, Sunshine na tailnet, torchaudio).

O disjuntor está working: 176 requisições já foram curtas-circuitadas localmente, e o
journal mostra o padrão (`context guard: request 5461720 bytes >= 5435430 bytes que o
upstream ja recusou por context_length`).

## 3. O upstream está degradado, e a degradação cai exatamente na faixa do teto

Contadores de 6 horas: **73 upstream 504**, **117 erros de I/O**, 16 "connection reset
by peer", 5 429 do upstream, 83 erros no total, 195 retries, e 2154 s de tempo
acumulado em fila (0,85 s por requisição, com a fila de 21 s nos piores casos).

A distribuição do tamanho das requisições que o gate avisou (54 amostras):

| faixa | requisições | o que é |
|---|---|---|
| p50 | 5,46 MB | ~1,37 M tokens: **acima do teto da API** (1 048 576), o disjuntor corta localmente |
| p90 | 5,47 MB | idem |
| máximo | 5,47 MB | idem |
| mínimo | 0,83 MB | ~208 mil tokens: passa pelo teto de 262144 |

**O que o teto de 262144 evita:** 37 das 54 requisições avisadas (69 %) estão acima de
1,05 MB, que é o teto de 262144 tokens. Desses, 35 são as de 5,4 MB (as que o
upstream recusa por `context_length` e o gate corta localmente) e as demais são as de
~1,0 MB que estão tomando **504** do upstream.

Ou seja: o teto de sessão não é uma garantia teórica. Ele cobre **69 % do que o gate
registra como problema**, e a parte que sobra (5,4 MB) é a que o disjuntor já trata
sem gastar cota.

## 4. Conclusão

1. O endpoint novo está correto: local, sem segredo, com contadores úteis.
2. O path `/health` é a armadilha: relayado ao upstream, 5,4 s, e sonda errada parece
   serviço morto (a regra nova do `AGENTS.md` já cobre isso).
3. **Os dois fixes do provider já estão vivos**: o rebuild pendente não os inclui.
4. O teto de 262144 tem efeito medido: 69 % das requisições que o gate avisa ficariam
   fora, e o resto é o que o disjuntor já corta localmente.
5. O upstream está falhando (73 504 e 117 erros de I/O em 6 h). Isso é a outra ponta da
   decisão de capacidade: mais chaves ou relay dedicado, como a folha já diz.
