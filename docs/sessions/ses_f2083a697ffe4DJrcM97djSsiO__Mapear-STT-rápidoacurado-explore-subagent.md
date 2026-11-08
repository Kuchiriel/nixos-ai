# Mapear STT rápido/acurado (@explore subagent)

- **sessão:** `ses_f2083a697ffe4DJrcM97djSsiO`
- **quando:** 2026-09-26 20:51 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 7 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Nos repos /home/nixos/projects/karaok e /home/nixos/projects/applio-lab, descubra qual stack de STT/transcrição eles usam (faster-whisper? modelo qual? Vosk? sherpa-onnx? Wyoming?). Para cada um retorne: biblioteca, nome/tamanho do modelo, onde o modelo está em disco (~/models? .venv? cache?), e um número de velocidade/acurácia se houver nos docs/testes. Depois compare com o que o JARVIS usa (grep faster-whisper|whisper|vosk|sherpa em /home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/stt* ou voice*). Resposta concisa: tabela comparativa + veredito de qual o Jarvis deveria usar e por quê. NÃO edite nada.

---

## · ?

Nenhum arquivo editado. `vosk|sherpa|wyoming|parakeet|whisper.cpp` = zero hits em `karaok` e `applio-lab`; JARVIS só cita `whisper.cpp` como plano futuro em `hwprofile.py`.

| Repo | Biblioteca | Modelo ativo | Modelo em disco | Velocidade / acurácia registrada |
|---|---|---|---|---|
| `karaok` (`src/karaok/transcription.py`, `.venv`: `faster-whisper 1.2.1`, `whisperx 3.8.6`) | `faster-whisper` direto (CTranslate2) + `WhisperX` legado; estratégia LRCLIB-first | `large-v3-turbo` (ativo: `align_lrc_with_stt(model="large-v3-turbo")`, `transcribe_lrc_turbo`); `small` legado (`config.py: Systran/faster-whisper-small`, `whisperx_model=small`) | Sem `download_root` → cache HF padrão `~/.cache/huggingface/hub/` (`README`: reusa cache, `small` ~464 MB). `.venv` só libs. `~/models/` só `htdemucs` | `~20s/4min` GPU turbo fp16 (comentário código); fallback cego cuda→cpu custava `~40s`/música (OOM) → `_pick_whisper_device(min 2.2 GB livres)`; `prepare --all ~10-15min` GPU; `warmup 92s→2.0s` cache-hit. Sem WER; qualidade via `no_speech>0.7`, `avg_logprob<-0.8`, anti-banter, fuzzy `≥0.55`, time-prior `±12s` (sem ele: drift `±178s`, 28/31 músicas) |
| `applio-lab` (`scripts/fw-stt.py`, `scripts/stt-word-check.py` — "padrão espiado do karaok") | `faster-whisper` direto, só isso | `fw-stt.py: "turbo"` (`cuda/float16` → fallback `cpu/int8`, `language=pt`, `vad_filter=True`); `stt-word-check.py: "small"` (`cpu/int8`, `language=pt`, `word_timestamps=True`) | Sem `download_root` → HF cache padrão. venv `~/.venvs/lab`. `~/models/` = só RVC `.pth` + `timbre-refs/`, nenhum Whisper | Sem WER formal; threshold `ratio 0.60` (`check_seg lim=0.60`) + diff palavra-a-palavra com `t0-t1`. Uso como régua: narrador alvo `150-160wpm` (`santa speed 0.8 ≈157wpm`, medido via STT). `small` CPU de propósito: "seguro com GPU ocupada pelo render" |
| JARVIS (`nixos-ai/.../jarvis/core/voice.py` + `modules/ai/models.nix:286`) | `faster-whisper` (nixpkgs 1.2.1), import lazy, **CPU `int8` sempre**, subprocess isolado (CTranslate2+Kokoro = FPE), `beam=3`, `condition_on_previous_text=False`, `initial_prompt="Hey Jarvis."`, VAD `0.5/250ms/1000ms/400ms`, `STT_MIN_CONFIDENCE=-0.60` (limpa `-0.23/-0.38` vs alucinação `-0.69..-1.14`), timeout 60s | `small` (`STT_MODEL_DEFAULT=JARVIS_STT_MODEL\|\|"small"`), fonte `models.nix: whisper-small` (Systran, 4 arquivos com `sha256`) | `download_root=~/.local/share/jarvis/voice` (`JARVIS_VOICE_DIR`), provisionado declarativo Nix (`modelsLink` em `jarvis-wakeword.nix`), não HF volátil | Sem bench t/s no código; `hwprofile.py` prevê `whisper.cpp` SYCL/OpenVINO `12x` na iGPU UHD 770 (futuro, inativo) |

**Veredito: JARVIS fica no `faster-whisper small CPU int8` atual.**

Por quê: (1) convergência — os 3 usam mesmo runtime/versão/modelo-base, nada prova ganho em trocar; (2) VRAM 6 GB = 1 LLM por vez — `turbo` GPU exige 2.2 GB livres (prova do karaok) e o lab usa `small` CPU exatamente para não brigar com GPU ocupada; (3) provisionamento Nix pinado > HF cache imperativo; (4) VAD+confiança já calibrados para casa ruidosa. Único cherry-pick válido: copiar `_pick_whisper_device()` do karaok para turbo-GPU oportunista quando VRAM livre, e `word_timestamps+fuzzy` (karaok/applio-lab) se um dia precisar alinhamento — não trocar stack para Vosk/sherpa/Wyoming (perderia PT-BR multi-língua sem ganho medido).

---

