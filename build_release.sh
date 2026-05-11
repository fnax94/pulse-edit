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

pyinstaller --name "PulseEdit" \
    --windowed \
    --noconfirm \
    --icon resources/icon.icns \
    --collect-all customtkinter \
    --add-binary "resources/ffmpeg:." \
    --hidden-import librosa \
    --hidden-import librosa.util \
    --hidden-import librosa.filters \
    --hidden-import librosa.feature \
    --hidden-import librosa.beat \
    --hidden-import librosa.onset \
    --hidden-import librosa.core \
    --hidden-import scipy.signal \
    --hidden-import scipy.fft \
    --hidden-import soundfile \
    --hidden-import numba \
    --hidden-import soxr \
    --hidden-import numpy \
    --hidden-import app \
    --hidden-import app.i18n \
    --hidden-import app.core \
    --hidden-import app.core.resolve_bridge \
    --hidden-import app.core.beat_detector \
    --hidden-import app.core.clip_analyzer \
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
