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
[ -d $SPK/applio/rvc ] || git clone -q --depth 1 https://github.com/IAHispano/Applio.git $SPK/applio
[ -d $SPK/linacodec/src ] || git clone -q https://github.com/ysharma3501/LinaCodec.git $SPK/linacodec
mkdir -p $SPK/applio/rvc/models/predictors $SPK/applio/rvc/models/embedders/contentvec
cd $SPK/applio/rvc/models
for f in predictors/rmvpe.pt predictors/fcpe.pt embedders/contentvec/pytorch_model.bin embedders/contentvec/config.json; do
  [ -f "$f" ] || nix-shell -p aria2 --run "aria2c -x8 -s8 -k2M -c -o $f https://huggingface.co/IAHispano/Applio/resolve/main/Resources/$f"
done

cat <<'EOF'
# Exporte antes de usar voice-clone:
export LD_LIBRARY_PATH=/nix/store/7vafhlh0lmcvi75jfyy09qwr4m3x1ks3-gcc-15.2.0-lib/lib:/nix/store/483x61iy35irm4wr2b7dwzihljhp6da2-zlib-1.3.2/lib:$LD_LIBRARY_PATH
export JARVIS_RVC_PYTHON=/tmp/opencode/tts-venv/bin/python
export JARVIS_RVC_APP_DIR=/tmp/opencode/applio
export JARVIS_RVC_LD_PATH=/nix/store/7vafhlh0lmcvi75jfyy09qwr4m3x1ks3-gcc-15.2.0-lib/lib:/nix/store/483x61iy35irm4wr2b7dwzihljhp6da2-zlib-1.3.2/lib
export JARVIS_VOICE_CLONE_MODEL=$HOME/models/Jarvis_62e_434s_best_epoch.pth
export JARVIS_VOICE_CLONE_INDEX=$HOME/models/added_Jarvis_v2.index
EOF
