# Garimpar SFX e replace (@general subagent)

- **sessão:** `ses_f585adbe8ffeAAm7a86maeufHn`
- **quando:** 2026-09-16 00:36 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 22 (exportadas: 7)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No HD externo /run/media/nixos/YUMI/ (SÓ LEITURA, nada modificar), ache: (1) QUALQUER lógica de replace onomatopeia→SFX (tabelas, dicionários, código que troca texto por som; grep por: onomatopeia, "bang", "splash", "thud", "whoosh", sfx e replace no mesmo arquivo); (2) SFX e ambientes úteis para audiobook de época vitoriana/steampunk (rua, carroça, cavalo, chuva, porta, taverna, relógio, sino, multidão, passos, papel, fogo, metal, vidro, trovão, vento, coruja); (3) scripts de áudio (mix, master, binaural, pan, ffmpeg/sox). Prioridade: PROJETOS/PESQUISA/AI_SYSTEM/scripts/, PROJETOS/PESQUISA/AI_SYSTEM/docs/, MÍDIA/, STORAGE/, BACKUPS/MANJARO_EXTRACTED/, PROJETOS/TOOLS/. Para cada achado: caminho completo + conteúdo relevante (primeiras 30 linhas se código/tabela) + utilidade em 1-2 linhas. PT-BR, conciso, máximo 20 achados.

---

## · ?

Caçando SFX vitorianos e lógica onomatopeia→som no HD externo — só leitura.

---

## · ?

Encontrei o AI_SYSTEM e pastas prioritárias. Agora vasculhando o conteúdo relevante.

---

## · ?

Vou ler diretamente os arquivos-chave do audiobook e pipeline de voz.

---

## · ?

Achei a lógica central onomatopeia→SFX e sons ambientes. Aprofundando o código e inventário de áudios.

---

## · ?

Tabela onomatopeia→SFX localizada. Fechando o inventário de SFX vitorianos e scripts de mix.

---

## · ?

Varredura só-leitura em `/run/media/nixos/YUMI/` concluída. Nada modificado. Resultado (16 achados):

## (1) Lógica onomatopeia → SFX

**1. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/jarvis/audiobook_modules/data/sound_effects.json`**
Tabela central (112 linhas). Trecho:
```json
"shoot": {"keywords": ["Bangue!","bangue!","Bang!","bang!"], "file": "actions/shoot.ogg"},
"metal_clink": {"keywords": ["cling!","clink!"], "file": "actions/metal_cling.ogg"},
"footsteps": {"keywords": ["Tac! Tac! Tac!","tac! tac! tac!"], "file": "actions/footsteps.ogg"},
"onomatopoeia": ["Bang!","Pá!","Estilhaços!","Cling!","Clang!","Boom!","Crash!","Splash!","Tac!","Tique-taque","Ofego!","Arrepios!"]
```
Utilidade: é O dicionário pronto onomatopeia→arquivo SFX; copie/estenda para o audiobook vitoriano.

**2. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/jarvis/enhanced_audiobook.py` L263-302 + L505-519**
```python
SOUND_EFFECTS = {"rain": ["chuva","chuvendo"], "thunder": ["trovão","relâmpago"], ... "carriage": ["carruagem"], "church_bell": ["sino da igreja","sino tocou"], "clock": ["relógio","tique-taque"], "crowd": ["multidão"], "metal_clink": ["cling","clink"], "shoot": ["bangue","bang"], ...}
def strip_pure_onomatopoeia(text): onomatopoeia = ["clinque","clanque","cling","clink","clang","bangue","bang","boom","crash","splash","swoosh","whoosh","thud","thump","tac"] ...
def detect_sfx_with_position(text): ... re.finditer(r'\b'+keyword+r'\b') ...
def split_text_by_sfx(text, sfx_positions): ... segments {"type":"text"/"sfx"} ...
async def play_sound_effect(effect_name, volume=0.6): ... paplay --volume ...
```
Utilidade: pipeline completo keyword→posição→split texto/SFX→toca via `paplay` sem narrar a onomatopeia; modelo a reutilizar.

**3. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/jarvis/audiobook_modules/text_processor.py` (217 linhas)**
Versão modular do mesmo: carrega `sound_effects.json`, `detect_sfx_with_position()`, `detect_vocal_effect()`, `detect_emotion()`, `split_text_by_sfx()`.
Utilidade: use este módulo em vez do monolito — já separa SFX, vocal (riso/sussurro/choro) e emoção→volume.

**4. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/jarvis/audiobook_modules/audio_player.py` (91 linhas)**
```python
SOUND_MAP = {effect: data["file"] ...}
async def play_sound_effect(effect_name, volume=0.6): ... paplay --volume ...
async def play_audio_bytes(wav_bytes, volume=1.5): ... tempfile + paplay ...
```
Utilidade: camada de mix simples (volume por efeito, fire-and-forget); ponto onde inserir pan/binaural depois.

**5. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/jarvis/enhanced_audiobook.py.nextgen`**
Variante bilíngue (`carriage: ["carruagem","carriage","cocheiro"]`, `rain/raining/chuva`, `thunder/lightning/trovão`) + `detect_sound_effects()`, `strip_sfx_from_text()`, `detect_scene()`→`rain_bg`, flag `--no-sfx`.
Utilidade: base melhor para texto EN/PT e ambiente contínuo (chuva de fundo) — ideal p/ época vitoriana.

**6. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/docs/ENHANCED_AUDIOBOOK.md` L40-73**
Doc da detecção: clima (rain/thunder/wind/storm), natureza, ações (door/footsteps/explosion/scream), emoções→prosódia futura.
Utilidade: especificação do framework SFX + roadmap (play_sound_effect, ambiente em loop, EmotiVoice/Bark).

## (2) SFX e ambientes p/ vitoriano/steampunk

**7. `.../jarvis/assets/sounds/ambient/rain.wav`, `rain3.wav` (5,5 MB cada), `wind.wav` (2 MB), `fire.wav` (5,5 MB), `ocean.wav` (4,1 MB)**
WAVs reais presentes no HD (únicos SFX binários achados). Trecho: n/a (binário).
Utilidade: chuva/vento = Londres vitoriana; fogo = lareira/taverna; reaproveite direto como `weather/nature/ambient`.

**8. Mapeamento vitoriano já previsto (sem arquivo, só placeholder): `sound_map` em `enhanced_audiobook.py` L296-298**
`carriage→city/crowd.ogg`, `church_bell→city/crowd.ogg`, `clock→mechanical/clock_ticking.ogg`, `crowd→city/crowd.ogg`; keywords `carruagem`, `sino da igreja`, `relógio/tique-taque`, `multidão`, `porta/passos/vidro/metal`.
Utilidade: estrutura pronta p/ rua/carroça/sino/relógio/multidão/porta/passos/papel-fogo-metal-vidro — mas os `.ogg` NÃO existem no HD; baixe via item 10.

**9. `/run/media/nixos/YUMI/MÍDIA/Binaural_Healing_5min.wav` (51 MB)**
WAV binaural pronto.
Utilidade: referência de espacialidade binaural + cama de fundo; estude ocous como masterizar trilha imersiva.

**10. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/scripts/setup-audiobook-sounds.sh` (105 linhas)**
Cria `~/.jarvis/sounds/{weather,nature,actions,ambient}`, lista fontes (Freesound, BBC 16k efeitos, OpenGameArt, Zapsplat) + receitas `ffmpeg -i x.wav -c:a libvorbis x.ogg`, `paplay --volume`.
Utilidade: runbook p/ baixar os SFX vitorianos faltantes (cascos, carroça, sino, taverna, coruja, trovão) e padronizar em `.ogg`.

**11. `.../jarvis/cleaned.wav`, `final.wav`, `gravacao.wav`, `ruido.wav`, `temp.wav` + `[Jarvis (UCM) - Português Brasileiro]Vocês...... isso.mp3`**
Amostras de voz/ruído do pipeline (duplicadas em `BACKUPS/MANJARO_EXTRACTED/Projects/AI_SYSTEM/jarvis/`).
Utilidade: voz PT-BR de referência + perfis de ruído (`noise.prof/ruido.prof`) p/ redução de ruído na narração.

## (3) Scripts de áudio (mix/master/binaural/pan/ffmpeg-sox)

**12. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/scripts/audiobook-reader` (24 linhas)**
Wrapper `~/.jarvis/audiobook-env/bin/python + jarvis/enhanced_audiobook.py` (venv Python 3.11 p/ ChromaDB).
Utilidade: entry-point oficial do leitor; chame da pipeline do audiobook.

**13. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/scripts/debug-audiobook.py` (141 linhas)**
Monitor TTS→`paplay/aplay`, gaps >3s, `pactl list sink-inputs`.
Utilidade: debug de sincronia narração↔SFX.

**14. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/jarvis/jarvis-48k-fix.py` (54 linhas)**
Captura 48 kHz, decimação `[::3]`→16 kHz p/ wakeword, `paplay ...message-new-instant.oga`.
Utilidade: receita de resample 48k→16k e playback; adaptar p/ normalizar SFX a 48 kHz.

**15. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/scripts/test_stereo_audio.py` (31 linhas)**
Teste estéreo/mono PyAudio 48 kHz + energia por chunk.
Utilidade: único teste de estéreo achado; base p/ implementar pan/binaural.

**16. `/run/media/nixos/YUMI/PROJETOS/PESQUISA/AI_SYSTEM/docs/TTS_COMPARISON.md` (321 linhas) + `scripts/audio_logic_test.sh`, `scripts/test_audio_loopback.sh`, `jarvis/generate_voice_test_audio.py`**
Comparação Kokoro (atual, neutro) vs Chatterbox/Bark/EmotiVoice (emotivo, tags `[laugh]/[whisper]`); scripts de diagnóstico `parecord/paplay/wpctl/arecord` e geração de áudios de teste.
Utilidade: caminho p/ narração emotiva vitoriana; diagnóstico de cadeia Mic→TTS→alto-falante.

**Negativos importantes (evita retrabalho):** nenhum `ffmpeg/sox` de mix/master/pan/binaural além das receitas de conversão do item 10; nenhum asset de casco/carroça/coruja/taverna — só keywords/paths; nada em `PROJETOS/TOOLS/`, `STORAGE/`, `MÍDIA/GAMES/` além do binaural; `BACKUPS/MANJARO_EXTRACTED/` é cópia espelhada do mesmo `AI_SYSTEM` (mesmos 5 WAVs).

---

