#!/bin/bash
# Build PulseEdit app con PyInstaller
cd "$(dirname "$0")"
source venv/bin/activate

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
    --hidden-import sklearn.utils._cython_blas \
    --hidden-import sklearn.neighbors.typedefs \
    --hidden-import sklearn.neighbors._partition_nodes \
    --hidden-import sklearn.tree._utils \
    --hidden-import numba \
    --hidden-import soxr \
    --hidden-import numpy \
    main.py

echo ""
echo "Build completato! App in: dist/PulseEdit.app"
echo "Per testarla: open 'dist/PulseEdit.app'"
