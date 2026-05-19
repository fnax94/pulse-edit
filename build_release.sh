#!/bin/bash
# Build Release — PyInstaller (bundle .app) senza PyArmor
# Protezione fornita da license-server.abtools.workers.dev (hardware binding)

cd "$(dirname "$0")"
source venv/bin/activate

echo "=== Pre-build check: ffmpeg must be statically linked ==="
if otool -L resources/ffmpeg 2>/dev/null | grep -qi homebrew; then
  echo "✗ resources/ffmpeg is dynamic-linked to Homebrew dylibs!" >&2
  echo "  This breaks the app on any Mac without Homebrew + matching ffmpeg." >&2
  echo "  Replace resources/ffmpeg with a static binary (e.g. from osxexperts.net)." >&2
  echo "  Aborting build." >&2
  exit 1
fi

echo "=== Build app con PyInstaller ==="
rm -rf build dist

# Pre-fetch beat_this DNN checkpoint (offline-ready bundle)
# torch.hub looks under $TORCH_HOME/hub/checkpoints/ so we mirror the full
# hub/ subtree (not just checkpoints/) to keep beat_this offline-loadable.
echo "▶ Pre-downloading beat_this 'final0' checkpoint..."
python -c "from beat_this.inference import File2Beats; File2Beats(checkpoint_path='final0', dbn=False)" || {
  echo "⚠ beat_this not installed in venv — install with: pip install beat_this torch torchaudio"
  exit 1
}
rm -rf model_cache
mkdir -p model_cache
if [ -d "$HOME/.cache/torch/hub" ]; then
  cp -r "$HOME/.cache/torch/hub" model_cache/
  echo "▶ Bundled checkpoint(s):"
  find model_cache -name "*.ckpt" -o -name "*.pt" -o -name "*.pth" 2>/dev/null
else
  echo "✗ ~/.cache/torch/hub not found — beat_this checkpoint missing!" >&2
  exit 1
fi

pyinstaller --name "PulseEdit" \
    --windowed \
    --noconfirm \
    --clean \
    --icon resources/icon.icns \
    --collect-all customtkinter \
    --collect-all librosa \
    --collect-all certifi \
    --collect-all beat_this \
    --collect-all einops \
    --collect-all rotary_embedding_torch \
    --collect-all torch \
    --collect-all torchaudio \
    --collect-all numba \
    --collect-all llvmlite \
    --collect-all sklearn \
    --add-binary "resources/ffmpeg:." \
    --add-data "app/__version__.py:app" \
    --add-data "model_cache:model_cache" \
    --hidden-import scipy.signal \
    --hidden-import scipy.fft \
    --hidden-import scipy.ndimage \
    --hidden-import soundfile \
    --hidden-import soxr \
    --hidden-import numpy \
    --hidden-import lazy_loader \
    --hidden-import audioread \
    --hidden-import pooch \
    --hidden-import decorator \
    --hidden-import joblib \
    --hidden-import cffi \
    --hidden-import msgpack \
    --hidden-import app \
    --hidden-import app.__version__ \
    --hidden-import app.i18n \
    --hidden-import app.core \
    --hidden-import app.core.resolve_bridge \
    --hidden-import app.core.resolve_worker \
    --hidden-import app.core.beat_detector \
    --hidden-import app.core.editor \
    --hidden-import app.core.mood_analyzer \
    --hidden-import app.gui \
    --hidden-import app.gui.main_window \
    --hidden-import app.gui.license_dialog \
    --hidden-import app.licensing \
    --hidden-import app.licensing.lemon \
    --hidden-import app.licensing.storage \
    main.py

echo ""
echo "=== Copia file installazione ==="
[ -f "INSTALL.txt" ] && cp "INSTALL.txt" "dist/"
[ -f "Installa PulseEdit.command" ] && cp "Installa PulseEdit.command" "dist/"

echo ""
echo "=== Build completato! ==="
echo "App in: dist/PulseEdit.app"
echo "Per testarla: open 'dist/PulseEdit.app'"
