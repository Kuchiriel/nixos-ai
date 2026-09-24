# LOOP PROMPT — eu escrevi, eu leio, eu obedeço (ciclo a ciclo)

Estado: /tmp/overnight/LOOP-STATE.md · Fila: /tmp/overnight/LOOP-QUEUE.md

## Ciclo (repita até a fila acabar, usuário pedir parar, ou contexto esticar)
1. LEIA LOOP-STATE.md e CLAIMS.md. Se STATE não existir, crie com timestamp.
2. PEGUE a PRIMEIRA tarefa pendente da fila. Sem tarefa? Encerre o ciclo com relatório.
3. FAÇA a tarefa até o FIM. Terminar = verificação real executada (comando rodado,
   output colado no STATE). "Vou tentar" não existe. Promessa sem ação = falha.
4. REGISTRE no STATE: o que fez, evidência (comando+output), próximo passo exato.
5. ATUALIZE a fila (status + aprendizado).
6. Se o contexto diluir: escreva STATE compacto — o próximo ciclo/sessão lê e continua.
7. Volte ao passo 1. NÃO despeça, NÃO resuma, NÃO faça meta — só o próximo passo.

## Fila inicial (24/09 noite)
- T1: Ler os transcripts Codacus JÁ baixados (done.txt + onde Muse os puser)
  → extrair truques aplicáveis ao RTX 4050 6GB (flags, modelos, números)
  → escrever ~/Books/codacus/FINDINGS.md (por vídeo: truque+flags+prioridade)
- T2: Do FINDINGS, escolher o truque de maior ganho potencial → BENCHAR
  (mesmo protocolo do bench-spec.sh: antes/depois, 3 reps, evidência no STATE)
- T3: Se bench vencer (>1.3x ou ganho claro): aplicar em models.nix + commit.
  Se perder: registrar veredito no models.nix comment (anti-regressão).
- T4: Próximos da fila: Qwen3-4B+draft (regime DFlash), A3B -n-cpu-moe.

## REGRAS ADICIONADAS 24/09 (erros da noite → protocolo)
R1. BINÁRIO CERTO (BINARIES.md + matriz models.nix): path+--version NA evidência;
    sem isso o veredito é inválido. Prism p/ ternário; upstream/ik p/ MoE/dense.
R2. LAYOUT DO GGUF também valida: Bonsai 27B Q2_0 padrão = ILEGÍVEL; usar PQ2_0
    (kernels PTQ novos, "2x prefill") ou Q2_g64 (como o 8B). O erro do loader
    ENSINA o formato certo — leia a mensagem do binário, ela é o doc.
R3. git status ANTES de commit (não varrer staging de outro agente).
R4. NORTE (dono 24/09): t/s por CONFIGURAÇÃO ("água de pedra"), não "melhor modelo";
    teto REAL medido antes de trocar modelo (n preguiça/n harness ruim); comparar
    vs literatura em ~/Books (RAG) e web; SEM HARDCODING — ctx/tokens dinâmicos
    pela flag ctx do models.nix; sistema escala Termux→este PC→datacenter NPU/TPU;
    erros são ATIVOS: registrar rag/memory/vault/md e não repetir.
R5. Ordem dos gates: base da pilha consolidada → gates do harness + harbor do
    modelo MAIS FRACO pro mais forte (fraco força harness melhor).

## R6. CANAL REMOTO DO DONO (24/09, dono na rua no 4G)
O dono comanda à distância por **@jarvis_lab_bot** (serviço jarvis-telegram,
ativo desde 21/09): /ask /agent /status /remember /vault + botões [Sim]/[Não].
TODO ciclo: recall (memory) + vault + /tmp/overnight/COMMANDS.md — comando
remoto do dono TEM PRIORIDADE sobre a fila. Responder via... o próprio
telegram (o service roteia; ou escrever no vault que ele lê pelo /vault).
ntfy = só alertas (one-way p/ o celular dele). Sunshine: NUNCA configurado
(sem /etc/sunshine) — pendência: setup+pairing em casa p/ Moonlight.

## R7. COMMITS MULTI-AGENTE (2º incidente)
JAMAIS `git commit` bare quando outro agente está ativo — SEMPRE path-limited:
`git commit <arquivo1> <arquivo2> -m "msg"`. Staging alheio é intocável.
Incidentes: 79cdb75, ceb5079 (misturados, preservados, msg não-reflete-tudo).
