# HANDOFF — laboratório A/B (atualizado 17/11, 07:00 -03)

> **Para quem chega agora (humano ou modelo):** leia esta página inteira,
> depois rode `scripts/lab.sh status` e `scripts/lab.sh doctor`. Não invente
> um caminho novo antes de fechar o diagnóstico. O histórico completo do dia
> está em `docs/agentes/ab-lab-17-11.md`.

## 1. O que está rodando agora

- `scripts/ab_loop.sh` (PID no `~/.local/state/jarvis/nightwatch/ab_loop.pid`)
  mede 3 braços × 3 níveis, em ciclo: **bonsai**, **mtp**, **api** (remoto).
- `agent-hub.service` (user, porta 8091) serve o mission control; a aba
  **laboratório A/B** tem matriz modelo × nível, VRAM ao vivo e botões.
- O residente da casa (`llama-uncensored-4b.service`, `:8092`) é **emprestado**
  ao laboratório por ciclo e devolvido no fim (`llm-swap.sh takeover|release`).
  Se houver cliente falando com ele, o ciclo é **adiado**.

## 2. O que foi consertado hoje (não desfazer)

1. O checker L3 exigia o impossível (parede fechava o mapa) → passagem em
   `(5,8)` + `test_mapa_tem_passagem`.
2. O checker L2 tinha o alvo dentro da parede → `(6,6)`.
3. GPU: takeover do unit de sistema + pausa do `jarvis-heal`.
4. `task_id` constante → `Recovering` eterno; agora tem nível + timestamp.
5. Modelo fraco não aplica hunk → `_whole_file_retry` no harness.
6. Escada L1/L2/L3 + `"nivel"` e `"ck":"v3"` nos resultados.
7. `api`: deepseek morreu (EOL); agora `nvidia/nemotron-3-ultra-550b-a55b`.
8. Hub: só `ck=v3` conta; `N failed>0` reprova; erro de infra é categoria
   própria.
9. `checkpoint.py` tinha fallback legado para o `checkpoint.json` global
   (`fail-test` de 04/set, projeto `test-repo`) → todo run começava em
   `Recovering: This will fail`. Agora o `ab_loop.sh` exporta
   **`JARVIS_STATE_DIR` por braço** (`~/.local/state/jarvis/nightwatch/ab-<braço>`),
   limpo a cada ciclo. Nenhum estado compartilhado contamina a medição.

## 3. Números honestos (o que já se sabe)

| braço | L1 (método) | L2 (desvio) | L3 (pathfinding) |
|---|---|---|---|
| baseline (sem agente) | 0/5 | 1/5 | 4/5 |
| bonsai 8B Q2 | **5/5** (85–119 s, 661–665 B) | **0/1** (patch cosmético, revisor certo) | **0/1** (2/5, 3003 B — pior que baseline) |
| mtp 4B | **4/4** (82–92 s, 495 B) | **0/1** (2/5, 819 B) | **0/1** (1/5, 1650 B — bug de unpack) |
| api (nemotron ultra) | **1/1** (216 s, 495 B) | **0/1** (guloso oscila, 1471 B) | **1/1** (5/5, 3461 B, 241 s, A*) |

Leitura (1 amostra por braço em L2/L3; o loop segue para 3):

1. **L1 é o piso**: os três passam, patch mínimo. Não discrimina mais nada.
2. **L3 prova o instrumento**: o `api` implementou A* com `heapq` e fechou
   5/5. O harness, o checker e o patch funcionam. O teto dos locais é real:
   mtp fez BFS com `path` misturando int e tupla (quebra no unpack); bonsai
   mexeu 3 KB e **regrediu** para 2/5 (baseline é 4/5).
3. **L2 não é degrau monotônico — é armadilha de guloso.** O `api` falhou L2
   porque ordenou as 4 direções por distância e oscilou entre (1,1) e (2,1);
   passou L3 porque usou A*. Quem sabe BFS/A* passa L3 e pode falhar L2; quem
   tenta "regra local" ingênua oscila. Decidir se L2 fica como teste de
   estratégia (documentado) ou ganha um hint explícito de estado/memória.

## 4. Como verificar que o instrumento é honesto (60 s)

```bash
cd ~/projects/nixos-ai
scripts/lab.sh doctor
```

Ele (a) roda `prova_checkers.py` — referência BFS tem de aprovar 5/5 nos três
níveis; (b) confere loop vivo; (c) conta `ck=v3`; (d) confere o hub na 8091.

Se `doctor` falhar, **pare**: medir com checker quebrado é pior que não medir.

## 5. Próximo passo decidido

Rodar até ter **3 medições por braço por nível** (matriz estável) e então:

- Se o `api` passa L3 e os locais não: o teto local é real; documentar a curva
  e escolher o especialista por tarefa (não o modelo geral).
- Se o `api` **também** falha em L3: o problema é o harness (contexto, patch,
  timeout), não o modelo. Aí o próximo item é instrumentar o harness
  (tokens de prompt, motivo do corte), não trocar modelo.

## 6. Comandos que salvam (copiar e colar)

```bash
# estado + GPU + matriz
scripts/lab.sh status
# forçar um degrau no próximo ciclo
scripts/lab.sh level L2
# só um braço, agora
scripts/lab.sh arm api
# parar tudo e devolver a GPU
scripts/lab.sh stop
# reiniciar o loop (não usa pgrep na linha do SSH)
bash scripts/restart-ab.sh
# ver o que o harness fez no último braço
tail -40 ~/logs/ab_loop/run-mtp.log
# patch que o modelo escreveu
ls -t ~/logs/ab_loop/patch-*.diff | head -1 | xargs cat
```

## 7. Limites conhecidos (para um modelo com contexto maior resolver)

- O `results.jsonl` **não** guarda tokens de prompt nem motivo de corte: não
  dá para dizer *por que* o L3 falhou (contexto? patch? timeout?) só olhando
  a linha. Melhorar o schema é o próximo item de instrumentação.
- `run-<braço>.log` é sobrescrito a cada ciclo: histórico de falha detalhada
  se perde. Guardar por timestamp é uma melhoria barata.
- O `api` passa pelo `nv-gate` (`:8095`, 8 rpm): rajada de retries pode dar
  429 e virar "erro de infra" em vez de medida.
- A escada só tem tarefa de código (dungeon). Generalizar para "checker por
  comportamento" em outros projetos é trabalho futuro.

## 8. Paridade celular ↔ Linux

O laboratório roda **todo** no Linux. O celular (`~/work/hub`) é espelho de
leitura + os wrappers `lab` e `lab-sync`. A paridade é medida por hash, não
lembrada:

```bash
lab-sync check    # 13 arquivos canônicos: local vs host (hash)
lab-sync pull     # baixa os canônicos para ~/work/hub
lab-sync local    # o que existe SÓ no celular (candidato a subir)
lab-sync host     # canônicos que faltam no espelho
```

Estado em 17/11: **paridade OK nos 13**. Ficam de propósito só no Linux:
`scripts/yt-insights.py`, `yt-channels.json`, `yt-push-phone.sh` (precisam de
`yt-dlp` + RAG do host) e `scripts/dungeon-lab*.sh` (histórico).

## 9. Onde a verdade mora

| assunto | arquivo |
|---|---|
| este handoff | `docs/lab/HANDOFF.md` |
| mapa + contrato + armadilhas | `docs/lab/README.md` |
| relato do dia (com provas) | `docs/agentes/ab-lab-17-11.md` |
| dados brutos | `~/logs/ab_loop/results.jsonl` |
| código | `scripts/*`, `modules/ai/jarvis/src/nightwatch/{dungeon,harness}.py` |

## 10. Auditar patch rejeitado (o revisor pode errar)

Quando o resultado é `patch=0B` + `Review failed`, o diff do modelo **não se
perdeu**: ele está no `git stash` da lane.

```bash
cd ~/projects/dungeon-<braço>
git stash list                 # nightwatch-autosave-uncommitted
git stash show -p stash@{0}    # o patch rejeitado
# teste objetivo contra o checker fixo, sem tocar na lane:
cp -a . /tmp/audit-<braço> && cd /tmp/audit-<braço>
git stash apply stash@{0} --index 2>/dev/null || git stash show -p stash@{0} | git apply
python3 -m pytest -q checker.py
```

Regra: **o veredito é do checker fixo**, o revisor é só um porteiro. Se o
checker aprovar um patch que o revisor rejeitou, a medição vale e o porteiro
está errado (17/11: no bonsai L2 o revisor estava certo).
