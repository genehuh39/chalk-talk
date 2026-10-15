#!/usr/bin/env bash
# One-time setup for Chalk Talk on an Apple Silicon Mac.
# Needs: ffmpeg (brew install ffmpeg), uv (https://docs.astral.sh/uv/), git, curl.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
TH="$ROOT/talking-head"
SADTALKER_COMMIT=cd4c0465ae0b54a6f85af57f5c65fec9fe23e7f8

for cmd in ffmpeg uv git curl; do
  command -v "$cmd" >/dev/null || { echo "missing: $cmd"; exit 1; }
done

echo "==> SadTalker (cloned at a pinned commit, patched for Apple Silicon)"
if [ ! -d "$TH/SadTalker" ]; then
  git clone https://github.com/OpenTalker/SadTalker.git "$TH/SadTalker"
  git -C "$TH/SadTalker" checkout -q "$SADTALKER_COMMIT"
  git -C "$TH/SadTalker" apply "$TH/patches/sadtalker-apple-silicon.patch"
fi

echo "==> SadTalker model weights (~2.6 GB)"
cd "$TH/SadTalker"
mkdir -p checkpoints gfpgan/weights
B=https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc
for f in mapping_00109-model.pth.tar mapping_00229-model.pth.tar SadTalker_V0.0.2_256.safetensors SadTalker_V0.0.2_512.safetensors; do
  [ -s "checkpoints/$f" ] || curl -fL -o "checkpoints/$f" "$B/$f"
done
for u in \
  https://github.com/xinntao/facexlib/releases/download/v0.1.0/alignment_WFLW_4HG.pth \
  https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth \
  https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth \
  https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth; do
  f="gfpgan/weights/$(basename "$u")"
  [ -s "$f" ] || curl -fL -o "$f" "$u"
done

echo "==> SadTalker environment (Python 3.10)"
cd "$TH"
[ -d .venv-sadtalker ] || uv venv -q --python 3.10 .venv-sadtalker
VIRTUAL_ENV=.venv-sadtalker uv pip install -q torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1
VIRTUAL_ENV=.venv-sadtalker uv pip install -q -r requirements-sadtalker.txt
# basicsr imports a torchvision module that was removed in torchvision 0.17+
DEG="$(.venv-sadtalker/bin/python -c 'import importlib.util as u; print(u.find_spec("basicsr").submodule_search_locations[0])')/data/degradations.py"
sed -i '' 's/from torchvision.transforms.functional_tensor import rgb_to_grayscale/from torchvision.transforms.functional import rgb_to_grayscale/' "$DEG"
# Robust Video Matting weights (for the background-removed coach)
.venv-sadtalker/bin/python -c "import torch; torch.hub.load('PeterL1n/RobustVideoMatting', 'mobilenetv3', trust_repo=True)"

echo "==> Kokoro TTS environment (Python 3.11)"
[ -d .venv-tts ] || uv venv -q --python 3.11 .venv-tts
VIRTUAL_ENV=.venv-tts uv pip install -q -r requirements-tts.txt

echo "==> Chalk Talk app environment (Python 3.11)"
cd "$ROOT/chalk-talk"
[ -d .venv ] || uv venv -q --python 3.11 .venv
VIRTUAL_ENV=.venv uv pip install -q -r requirements.txt
[ -f .env.local ] || [ -f .env ] || cp .env.example .env.local

echo
echo "Done. Add your API key to chalk-talk/.env.local, then run:"
echo "  cd chalk-talk && .venv/bin/uvicorn app:app --port 8000"
