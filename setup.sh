#!/bin/zsh
# One-time setup for video-studio (safe to re-run; it only fills in what is missing).
#
# Everything heavy goes into your workspace, ~/VideoStudio (or $VIDEO_STUDIO_HOME):
#   .venv/    Python env: Whisper (transcription), Kokoro (voice), numpy/scipy/Pillow   ~1.4 GB
#   bin/      a standalone ffmpeg
#   models/   the Kokoro voice model                                                    ~340 MB
#   projects/ one folder per video you make
# The Whisper model (~1.6 GB) is cached by Hugging Face in ~/.cache/huggingface.
set -e
PLUGIN="$(cd "$(dirname "$0")" && pwd)"
H="${VIDEO_STUDIO_HOME:-$HOME/VideoStudio}"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "video-studio needs a Mac with Apple Silicon (M1 or later): the transcription runs on MLX." >&2
  exit 1
fi
PY=$(command -v python3 || true)
if [[ -z "$PY" ]] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Python 3.10+ is needed. Install it from python.org or with 'brew install python', then re-run." >&2
  exit 1
fi

mkdir -p "$H"/{bin,models,projects}
cd "$H"
echo "workspace: $H"

# a venv copied or moved from elsewhere has stale script paths; rebuild it if pip won't run
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  rm -rf .venv
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q imageio-ffmpeg mlx-whisper kokoro-onnx soundfile numpy scipy pillow

# our own ffmpeg: a system one may be missing, a different version, or blocked by macOS
FF=$(.venv/bin/python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")
ln -sfn "$FF" bin/ffmpeg
bin/ffmpeg -version | head -1

for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -s "models/$f" ] || { echo "downloading voice model $f"; curl -fSL --progress-bar -o "models/$f" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"; }
done

# espeak-ng (Kokoro's pronunciation engine) ignores data paths longer than ~160 characters,
# so keep a copy at a short path
DATA=$(.venv/bin/python -c "import espeakng_loader; print(espeakng_loader.get_data_path())")
mkdir -p ~/.cache
[ -f ~/.cache/espeak-ng-data/phontab ] || cp -R "$DATA" ~/.cache/espeak-ng-data

echo "fetching the Whisper model (first time only)"
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')" >/dev/null

# self-check: every tool imports, ffmpeg runs, the voice speaks
.venv/bin/python - "$PLUGIN/tools" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
import analyze, build, captions, cards, look, render, retakes, sfx, tidy, timeline, verify, voice  # noqa
from common import kokoro
audio, sr = kokoro().create("Setup complete.", voice="am_michael", speed=1.0, lang="en-us")
assert len(audio) > sr // 2
EOF
echo "setup ok"
