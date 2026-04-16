#!/bin/bash
# Release PulseEdit: PyArmor → PyInstaller → AB Tools
set -e
cd "$(dirname "$0")"
VENV="$(pwd)/venv/bin"
PYARMOR="$VENV/python $VENV/pyarmor-8"
DEST="$HOME/Desktop/AB Tools"

echo "=== Step 1: Offuscamento PyArmor ==="
rm -rf /tmp/pyarmor_pe
$PYARMOR gen --output /tmp/pyarmor_pe main.py app/
cp -R /tmp/pyarmor_pe/* dist_obf/

echo ""
echo "=== Step 2: Build PyInstaller ==="
cd dist_obf
$VENV/python -m PyInstaller --name "PulseEdit" \
    --windowed \
    --noconfirm \
    --icon ../resources/icon.icns \
    --collect-all customtkinter \
    --add-data "pyarmor_runtime_000000:pyarmor_runtime_000000" \
    --add-binary "../resources/ffmpeg:." \
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
    --hidden-import pyarmor_runtime_000000 \
    --hidden-import app \
    --hidden-import app.i18n \
    --hidden-import app.core \
    --hidden-import app.core.resolve_bridge \
    --hidden-import app.core.beat_detector \
    --hidden-import app.core.clip_analyzer \
    --hidden-import app.core.editor \
    --hidden-import app.core.custom_patterns \
    --hidden-import app.gui \
    --hidden-import app.gui.main_window \
    --hidden-import app.gui.license_dialog \
    --hidden-import app.licensing \
    --hidden-import app.licensing.lemon \
    --hidden-import app.licensing.storage \
    main.py
cd ..

echo ""
echo "=== Step 3: Copia file installazione ==="
cp "INSTALL.txt" "dist_obf/dist/"
cp "Installa PulseEdit.command" "dist_obf/dist/"

echo ""
echo "=== Step 4: Copia in AB Tools ==="
mkdir -p "$DEST"
rm -rf "$DEST/PulseEdit.app"
cp -R dist_obf/dist/PulseEdit.app "$DEST/"

echo ""
echo "=== Release completata! ==="
echo "App in: $DEST/PulseEdit.app"
