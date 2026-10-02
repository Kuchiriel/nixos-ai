# Diagnóstico das chaves de visão (2026-10-02)

Cascata em `core/vision.py`: local (llama 8080) → **NVIDIA NIM** → Gemini →
Groq → OpenRouter → OCR. Ordem por diagnóstico, não por otimização.

## Estado das chaves (auth testada de verdade, 1 request cada)

| provider | env | resultado | diagnóstico |
|---|---|---|---|
| **NVIDIA NIM** | `NVIDIA_API_KEY` | ✅ **funciona** | chave `nvapi-…` válida, `meta/llama-3.2-11b-vision-instruct` responde (~3s) |
| llama local | — | ❌ 500 | router em 8080 não tem modelo de visão |
| Gemini | `GEMINI_API_KEY` | ❌ 401 | **o valor não é chave do Google** — len 53, prefixo `AQ.Ab8RN`; Gemini exige `AIza…` |
| Groq | `GROQ_API_KEY` | ❌ 403 | Cloudflare **code 1010**: bloqueio por IP/região, não chave inválida (`gsk_…` tem formato válido) |
| OpenRouter | `OPENROUTER_API_KEY` | ❌ 401 | "User not found" — chave não corresponde a conta nenhuma |

## Correções aplicadas
1. `keys.py` não tinha entrada `"nvidia"` → `keys.get("nvidia")` devolvia vazio
   apesar de a chave existir em `/etc/litellm.env`. Adicionada (aceita
   `NVIDIA_API_KEY` e `NVIDIA_NIM_API_KEY`).
2. `_vision_gemini` lia só `os.environ` → nunca achava a chave de
   `/etc/litellm.env`. Agora usa `keys.get()`.
3. `PIL ausente` **abortava** o nível Gemini em vez de mandar PNG cru.
4. `_ocr_text` usava só `--psm 6` (bloco uniforme), ruim p/ HUD de jogo.
   Agora multi-PSM (11/6/3) + autocontraste.
5. Cache de providers mortos agora tem **TTL de 5 min** — chave renovada
   volta sozinha, sem reiniciar (cache eterno seria gambiarra).

## Para renovar
Editar `/etc/litellm.env` (Nix, root) e esperar o TTL de 5 min expirar.
Groq provavelmente funciona se o IP sair do bloqueio Cloudflare; Gemini só
serve com uma chave `AIza…` de verdade.
