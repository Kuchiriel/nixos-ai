#!/usr/bin/env bash
# Reconstrói o ambiente RVC do spike (efêmero em /tmp) após reboot.
# Uso: ./scripts/rvc-spike-bootstrap.sh
# Ao final, exporta as envs que jarvis.core.voice_clone precisa.
# Empacotamento Nix definitivo (jarvis-voice-clone) ainda pendente.
set -e
SPK=/tmp/opencode
VENV=$SPK/tts-venv
WHEELS=$SPK/wheels

nix-shell -p python3 python3Packages.virtualenv aria2 ffmpeg --run "
  [ -x $VENV/bin/python ] || virtualenv $VENV
  $VENV/bin/pip download -q -d $WHEELS --resume-retries 10 --timeout 180 --retries 10 torch torchaudio --index-url https://download.pytorch.org/whl/cpu
  $VENV/bin/pip download -q -d $WHEELS --resume-retries 10 --timeout 180 --retries 10 transformers sentencepiece soundfile onnxruntime numpy huggingface_hub lhotse vocos pydub librosa soxr noisereduce pedalboard resampy torchcrepe scipy torchfcpe wget jsonargparse tensorboard faiss-cpu
  $VENV/bin/pip install -q --no-index --find-links $WHEELS torch torchaudio transformers sentencepiece soundfile onnxruntime numpy huggingface_hub lhotse vocos pydub librosa soxr noisereduce resampy torchcrepe scipy torchfcpe wget jsonargparse tensorboard faiss-cpu
"
# nix-ld compat (idempotente): o virtualenv symlinka o interpretador para o
# store (read-only) e o loader do store ignora NIX_LD_LIBRARY_PATH → torch
# não acha libstdc++/libz sem LD manual. Copia o binário para dentro do venv
# e aponta o INTERP para o loader nix-ld (/lib64): a partir daí, o venv
# resolve as libs sozinho — zero LD_LIBRARY_PATH, zero store path hardcoded,
# imune a GC. (Prova: env -i $VENV/bin/python -c "import torch".)
nix-shell -p patchelf --run "
  if [ -L $VENV/bin/python ]; then cp -f --remove-destination \$(readlink -f $VENV/bin/python) $VENV/bin/python; chmod +w $VENV/bin/python; fi
  patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 $VENV/bin/python
  patchelf --print-interpreter $VENV/bin/python
"
[ -d $SPK/applio/rvc ] || git clone -q --depth 1 https://github.com/IAHispano/Applio.git $SPK/applio
[ -d $SPK/linacodec/src ] || git clone -q https://github.com/ysharma3501/LinaCodec.git $SPK/linacodec
mkdir -p $SPK/applio/rvc/models/predictors $SPK/applio/rvc/models/embedders/contentvec
cd $SPK/applio/rvc/models
for f in predictors/rmvpe.pt predictors/fcpe.pt embedders/contentvec/pytorch_model.bin embedders/contentvec/config.json; do
  [ -f "$f" ] || nix-shell -p aria2 --run "aria2c -x8 -s8 -k2M -c -o $f https://huggingface.co/IAHispano/Applio/resolve/main/Resources/$f"
done

cat <<'EOF'
# Uso interativo (bash e zsh já fazem source via home.nix — nada manual):
#   source scripts/rvc-env.sh
# (O python do venv usa o loader nix-ld → sem LD_LIBRARY_PATH manual.)
export JARVIS_RVC_PYTHON=/tmp/opencode/tts-venv/bin/python
export JARVIS_RVC_APP_DIR=/tmp/opencode/applio
export JARVIS_VOICE_CLONE_MODEL=$HOME/models/Jarvis_62e_434s_best_epoch.pth
export JARVIS_VOICE_CLONE_INDEX=$HOME/models/added_Jarvis_v2.index
EOF
