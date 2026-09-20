# Teto de modelo no L8 — todos os GGUFs do ~/models (2026-09-20)

> Evidência LEVEL 4 (E2E executado). Questão: trocar o modelo resolve o L8?
> Resposta medida: **não** — cada modelo falha numa camada distinta; nenhum
> passa. Bonsai segue o único runner viável (harness-first confirmado com
> números, cf. literatura: constraints > tamanho).

## 1. Método (idêntico por modelo)

| Item | Valor |
|------|-------|
| Task/prompt | `/tmp/l8v-prompt.txt` (variante CWD, mesma da API 3/3) |
| Harness | HEAD 94d8ed1+ (gates atuais), `JARVIS_AGENT_MAX_TURNS=18`, `TIME_S=400` |
| Checks | `/tmp/l8v-check.py` (orig) + `/tmp/l8hard-check.py` (semântico) |
| Hardware | RTX 4050 6GB; embeddings/rerank em CPU |
| n | 1 por modelo (campanha de teto, não de variância) |

## 2. Resultados

| Modelo | Arquivo | Serve | Resultado | Camada da falha |
|--------|---------|-------|-----------|-----------------|
| Bonsai 8B Q2_0 (ternário) | nix store | router :8080 | 0/54 L8 hard (2 VERIFIED, 0 WORLD OK; 1 weak-pass d3 desmascarado) | L0 precisão de geração sob variância |
| Qwen3-4B Q4_K_M | ~/models | router alias jarvis-fast | STUCK 18t/247s, detector escrito nunca executado, zero guards | L0 alocação/passividade (lento, limpo, inerte) |
| Gemma-3-4B Q4_K_M | ~/models | standalone :8091 (ctx 2048, 12 camadas GPU) | UNVERIFIED 1t: pseudo-tools em texto, zero tool_calls | L3 interface (não emite tool_calls OpenAI) |
| Phi-4-mini Q4_K_M | ~/models | standalone :8091 (idem) | 2× timeout 120s na 1ª inferência | ENV latência (offload parcial lento p/ prompt full) |
| Llama-xLAM-2-8B | ~/models | — | EXCLUÍDO (dono: tool-call only) | — |

Notas:
- Qwen com thinking ligado estoura 120s (2×); com `JARVIS_LLM_DISABLE_THINKING=1`
  roda e falha como acima (config de experimento, não produção).
- Gemma responde chat OK (`GEMMA-OK`), mas não faz tool-calling → harness
  sem tools = sem L8. Falha de contrato, não de inteligência.
- Phi responde `PHI-OK` em prompt curto; prompt full + tools > 120s em
  offload parcial. VRAM impede full-offload com produção no ar (OOM medido:
  3.7GB residente + 2.5GB pesos + KV > 6GB).
- Produção restaurada após a campanha: bonsai loaded, router ok.

## 3. Conclusão

Trocar o modelo **não resolve** — e cada candidato falha *antes* ou *igual*:
interface (Gemma), latência (Phi), mesma muralha de geração (Qwen, STUCK
limpo). A insistência em tier-switch está encerrada com evidência. O caminho
segue harness-first: compressão de observações (msgs = 51% do payload),
oráculo de evidência, variância.
