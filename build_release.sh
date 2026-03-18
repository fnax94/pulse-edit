#!/bin/bash
# Build Release — PyArmor (offuscamento) + PyInstaller (bundle .app)
cd "$(dirname "$0")"
source venv/bin/activate

echo "=== Step 1: Offuscamento codice con PyArmor ==="
rm -rf dist_obf
pyarmor gen --output dist_obf main.py app/

echo ""
echo "=== Step 2: Build app con PyInstaller ==="
cd dist_obf

pyinstaller --name "PulseEdit" \
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
    --hidden-import app.gui \
    --hidden-import app.gui.main_window \
    --hidden-import app.gui.license_dialog \
    --hidden-import app.licensing \
    --hidden-import app.licensing.lemon \
    --hidden-import app.licensing.storage \
    main.py

cd ..

echo ""
echo "=== Build completato! ==="
echo "App in: dist_obf/dist/PulseEdit.app"
echo "Per testarla: open 'dist_obf/dist/PulseEdit.app'"
