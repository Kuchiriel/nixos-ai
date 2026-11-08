# Fuçar HD e Manjaro (@general subagent)

- **sessão:** `ses_f590785ddffe5p11VbkeT9cuCY`
- **quando:** 2026-09-15 21:28 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 13 (exportadas: 4)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Explore /run/media/nixos/YUMI/ (HD externo, 470GB) e ache coisas úteis para: (1) projeto audiobook multi-voz PT-BR (áudio, SFX, scripts TTS/RVC/voz, datasets, modelos), (2) projeto JARVIS (assistente IA local: STT/TTS/wakeword/RVC/código), (3) outros projetos aproveitáveis (OTServer/wurm-like, tibia, automações). Lugares prioritários: PROJETOS/PESQUISA/, PROJETOS/TOOLS/, PROJETOS/PRODUTOS/, MÍDIA/, STORAGE/, BACKUPS/MANJARO_EXTRACTED/ (extração do Manjaro antigo com AI_SYSTEM e LLM), LIXO/.
NÃO modifique nada no HD (só leitura). Para cada achado reporte: caminho completo, o que é, tamanho, e utilidade concreta (1-2 linhas). Limite: 25 achados mais relevantes. Responda conciso em PT-BR.

---

## · ?

Varrendo seu HD externo em busca de ouro para audiobook e JARVIS.

---

## · ?

Mapeamento quase completo — buscando os últimos detalhes de áudio e backups.

---

## · ?

Leitura apenas, nada modificado. Top 25 achados no `/run/media/nixos/YUMI/`:

**AUDIOBOOK MULTI-VOZ PT-BR**
1. `PROJETOS/PESQUISA/AI_SYSTEM/scripts/audiobook-reader/` — dir vazio (placeholder) + `setup-audiobook-sounds.sh`, `debug-audiobook.py`, `test_stereo_audio.py`. Utilidade: esqueleto já nomeado do pipeline audiobook; reusar scripts de som/estéreo.
2. `PROJETOS/PESQUISA/AI_SYSTEM/docs/ENHANCED_AUDIOBOOK.md` + `TTS_COMPARISON.md` + `KOKORO_SETUP.md` + `setup_kokoro_models.sh` (KBs) + `kokoro_models/` (vazio). Utilidade: decisão de TTS documentada + installer Kokoro; só falta baixar pesos.
3. `PROJETOS/PESQUISA/AI_SYSTEM/scripts/test_voice_pipeline.py`, `debug_voice_full_pipeline.py`, `monitor_voice.py`, `autonomous_voice_stabilizer.py`, `list_audio_devices.py`, `verify_audio_capture.py` (KBs cada). Utilidade: harness pronto de teste/estabilização de voz para o audiobook.
4. `PROJETOS/PESQUISA/AI_SYSTEM/[Jarvis (UCM) - Português Brasileiro]Vocês...... isso.mp3` — 526K. Utilidade: amostra de voz PT-BR estilo UCM; referência de timbre/avaliação A/B.
5. `MÍDIA/Binaural_Healing_5min.wav` — 51M. Utilidade: trilha/SFX ambiente pronta para fundo de audiobook/meditação.
6. `MÍDIA/Battlestar Galactica - The Plan (2009)-{en,pt-BR}.srt` + `03...` (85–97K cada, 4 arquivos). Utilidade: corpus paralelo EN↔PT-BR com timestamps; treino de timing/diarização e teste de tradução.
7. `STORAGE/Projetos/Edição de Vídeo/Projeto Fim do Mundo/` — `1.wav`, `2.wav`, `vocodes_*.wav`, `wav2lip.pth`, `End of the world.vpj` (~100MB+). Utilidade: amostras de voz + modelo Wav2Lip; pipeline voz→lipsync reaproveitável para audiobook com avatar.
8. `PROJETOS/PESQUISA/AI_SYSTEM/datasets/` — `training_data.jsonl` (23K) + `rive/` + `aiml_source/`. Utilidade: dataset de diálogos Rive/AIML; base para roteirização multi-personagem.
9. `PROJETOS/PRODUTOS/guia_renamer/bin/tesseract/` — ~1,7G total do produto. Utilidade: OCR bundled; digitalizar livros físicos → texto → TTS.

**JARVIS (STT/TTS/wakeword/RVC/código)**
10. `PROJETOS/PESQUISA/AI_SYSTEM/` — 253M, snapshot JARVIS completo (core, agents, orchestrator, daemons, ipc, llm, jarvis-cli, `jarvis-wakeword.sh.rclonelink`, `jarvis-voice-assistant/` vazio). Utilidade: base direta do JARVIS; diff contra `~/projects/nixos-ai`.
11. `PROJETOS/PESQUISA/AI_SYSTEM/docs/` — `OT_SERVER_AI_WORKFLOW.md`, `OVERNIGHT_LEARNING.md`, `LITELLM_SETUP_GUIDE.md`, `OLLAMA_INTEGRATION_GUIDE.md`, `TIBIA_15_20_REVERSE_ENGINEERING.md` (~40 docs). Utilidade: runbooks de overnight-learning, LiteLLM/Ollama e integração OTServer.
12. `PROJETOS/PESQUISA/LLM/` — 1,0M (`hardware_detector.py`, `model_config.py`, `model_loader.py`). Utilidade: loader/detector de modelos; portar para `nixos-ai/modules/ai`.
13. `STORAGE/Documentos/LLM/` — cópia do item 12. Utilidade: backup redundante; checar diff.
14. `PROJETOS/PESQUISA/AI_SYSTEM/config*.jsonc/yaml` (~20 snapshots: `config_final_v9.jsonc`, `config-safe_v6`, `config-smart.yaml`...). Utilidade: histórico de configs boas/ruins; rollback rápido.
15. `BACKUPS/MANJARO_EXTRACTED/Projects/AI_SYSTEM/` — parte dos 22G do backup. Utilidade: versão do Manjaro antigo; resgatar `GEMINI_VOICE_PIPELINE_MISSION.md` e scripts perdidos.
16. `PROJETOS/TOOLS/Scripts/EEGPUPV/` + `IEGPUPV/` (GPU-PV passthrough, Parsec/Sunshine/VDD). Utilidade: rodar RVC/TTS com GPU em VM Windows; guia Hyper-V pronto.

**OUTROS (OTServer/automações/produtos)**
17. `PROJETOS/PESQUISA/OTServer_UPGRADE/` — 12G (`canary/` 2,0G buildável, `tibia-captures/` 512M pcaps+bins, `otclient-mehah/` 454M, `otclient-mehah-clean/`, `tibia-15.20-analysis/`, `tibia-reverse-eng-tools/`, `JARVIS_INTEGRATION.md`). Utilidade: todo o stack wurm-like/Tibia + forense de protocolo.
18. `PROJETOS/PESQUISA/tibia_15_20_discoveries/` — 13M (`checkpoints/`, `bundling/` vazios). Utilidade: pesquisa protocolo 15.20; checar logs antes de descartar.
19. `BACKUPS/MANJARO_EXTRACTED/Projects/OTServer_UPGRADE/` — 12G duplicado. Utilidade: cópia de segurança do item 17; diff forense.
20. `PROJETOS/PRODUTOS/Wurm Ultimate/` — 5,9M (vision `detection/`, `macros/`, `safety/`, gui). Utilidade: macro/visão computacional pronto; modelo para automação de jogo.
21. `PROJETOS/PRODUTOS/MuDreamNotifier/` — 199M (`dist/`, `dist_obf/` PyArmor, `license_generator.py`). Utilidade: padrão de build+licenciamento Windows para empacotar/vender seus apps.
22. `PROJETOS/PRODUTOS/guia_renamer/` — 1,7G (OCR, Supabase, landing, tests). Utilidade: app Python comercial completo; reusar funil Supabase/licenças e OCR.
23. `MÍDIA/GAMES/RuneScape Dragonwilds Translation/` — pequeno (`pt-BR Screenshots/`, `readme.txt`, `Jagex Contact/`). Utilidade: pipeline de tradução PT-BR com screenshots; modelo de QA para revisão de audiobook.
24. `STORAGE/Projetos/` — bots e automações (`BombCrypto/`, `Bot/`, `Bot_Nuxt/`, `useful-scripts/`, `Shell Scripts/`, `termux-assistant/`). Utilidade: biblioteca de referência de bots/automações.
25. `LIXO/curriculos/` — vazio + `BACKUPS/NixOS.vhdx` + `BACKUPS/DRIVERS/` (imagem Windows + drivers). Utilidade: LIXO sem valor; VHDX/drivers servem só como VM de teste TTS Windows.

Sugestão: priorizar cópia (para `~/projects/`) dos itens 1–4, 7, 10–12 e 17 na próxima sessão.

---

