# Flag-Sweep Plan — RTX 4050 6GB (matriz binário × modelo × flags)

> 24/09, extraído dos --help reais (prism b10660 + upstream 0.4.0 nix store).
> Padrão do doc irmão `ncmoe-sweep.md` (26/08: ncmoe=35 ótimo p/ 35B).
> Coordenação: agente A (benches) + agente B (insights dos transcripts/FINDINGS).
> Cada braço = protocolo da casa: warmup 2, 3-5 reps, router-stop/start, evidência
> no results + veredito em models.nix (anti-regressão).

## Matriz binário-por-modelo (MEDIDA — não repetir erros)
| Modelo | Binário | Estado |
|---|---|---|
| Bonsai ternário 8B/27B | **prism** | 8B: 72 t/s (dc8b7dc). 27B: pendente |
| Qwen MoE 35B/30B-A3B | **upstream** | 35B: 32 pico/19 sust (ngl45+ncmoe35). prism=2-3 t/s (10x pior!) |
| Dense Q4 (Qwen3-4B etc.) | upstream | 60 t/s; spec-decode zero (2 bins, 9bfe8a5) |
| ik_llama | experimento | CPU-MoE especialista; meta bater 19 sust |

## Flags-chave (dos --help; diferenças entre bins)
- **Só upstream**: `--n-cpu-ffn N` (FFN denso→CPU por layer: p/ ternary-27B denso!),
  `--kv-unified-per-slot`, `--spec-synth-len/rates`, `--lazy-mode`, `--video-*`
- **Só prism**: `--kv-mean-center`, `--rpc` (distribuído)
- Comuns e subutilizados: `--override-tensor` (-ot regex por tensor = granular),
  `--cpu-range/--cpu-mask/--cpu-strict` (pinning P/E cores i7-13620H),
  `--prio/--poll` (prioridade de thread), `--cache-reuse`, `--cache-ram`,
  `--ubatch-size`, `--swa-full`, `--fit-ctx`
- Spec (referência, LINHA FECHADA 2x): --spec-draft-model/-md, --draft-max/min,
  --spec-ngram-* (mod/simple/map-k/k4v), --spec-draft-{cpu-range,prio,threads,ncmoe}

## Fila de braços (prioridade)
1. **Ternary-Bonsai-27B** (~/models, 7.17GB ✓): (a) prism -ngl ~34-38 resto-CPU;
   (b) upstream `--n-cpu-ffn` variante. Régua: 22 t/s no 3060 inteiro; meta >=12.
2. **Strong 35B sustentado**: `--cpu-range` P-cores (6P+4E do 13620H) + `--prio 2`
   no caminho CPU-experts → bater 19 t/s pós-throttle; depois `-ot` fino vs ncmoe.
3. **bonsai-8B micro**: -ub 1024 vs 512; `--cache-reuse`; `--kv-mean-center` (prism).
4. A3B-30B com flags da casa (upstream) — secundário.
5. ik_llama build + bench 35B CPU-MoE — se 2 falhar.

## Insights externos a cruzar (agente B)
FINDINGS.md (Codacus) + web: tudo que citar flag/binário/modelo vira braço aqui.

## Braço 6 (novo, resolve discrepância BINARIES.md)
6. **ik_llama vs upstream no 35B-A3B** (mesmas flags ngl45+ncmoe35): Muse aponta ik como binário MoE; sweep casa + meu 32 t/s = upstream. 3 reps cada; quem vencer atualiza BINARIES.md (regra: dado decide, não autoria).

## Braços EVIDENCE-BASED (FINDINGS Muse + papers, 24/09)
7. **P1 [IH8XmxiwliQ]: threads = físicos** — i7-13620H = 6P+4E → '-t 6' (usei -t 8 = errado;
   vídeo: +48% no 3060 MoE). RE-BENCH strong c/ -t 6 AGORA.
8. **P0 [8F_5pdcD3HY, GXT1060-6GB]: --no-mmap --mlock** no MoE offload (meu A3B
   sofreu do mmap frio). Progressive: 3→10→13.5→17 t/s; ctx 64K→256K @17.
9. KV 'turbo' (turbo4/turbo3): fork comunitário — checar se prism-b10735 aceita
   (--cache-type list); se não, braço futuro.
10. LRU expert-cache (hot experts em VRAM): fork, 25-26 t/s no P1 — futuro.
11. Contexto: paper 'Prompts→Harnesses' (RAG ~/Books): stable-prefix split p/ o
    ring-context do dono; caveman-skill: -65% tokens (docs/HONEST-NUMBERS.md).
