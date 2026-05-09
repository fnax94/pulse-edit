"""Analisi qualita visiva dei clip — trova il frame piu nitido."""

import subprocess
import os
import sys
import numpy as np


def get_ffmpeg_path():
    """Trova il path di ffmpeg."""
    import platform
    is_win = platform.system() == "Windows"
    exe = "ffmpeg.exe" if is_win else "ffmpeg"

    if hasattr(sys, '_MEIPASS'):
        for subdir in ["", "Resources", "Frameworks"]:
            bundled = os.path.join(sys._MEIPASS, subdir, exe) if subdir else os.path.join(sys._MEIPASS, exe)
            if os.path.exists(bundled):
                return bundled
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
    for subdir in ["Contents/Resources", "Contents/Frameworks", "Contents/MacOS"]:
        bundled = os.path.join(app_dir, subdir, exe)
        if os.path.exists(bundled):
            return bundled
    if not is_win and os.path.exists("/opt/homebrew/bin/ffmpeg"):
        return "/opt/homebrew/bin/ffmpeg"
    return exe


def analyze_clip(file_path, total_frames, fps, trim_start_s=0, trim_end_s=0,
                 num_samples=15):
    """Analizza un clip e trova il frame piu nitido (sharpest).

    Args:
        file_path: percorso del file video
        total_frames: numero totale di frame del clip
        fps: frame rate del clip (float)
        trim_start_s: secondi da tagliare dall'inizio
        trim_end_s: secondi da tagliare dalla fine
        num_samples: quanti frame campionare

    Returns:
        best_frame: numero del frame piu nitido (assoluto)
    """
    if not file_path or not os.path.exists(file_path):
        return total_frames // 2

    trim_start_f = int(trim_start_s * fps)
    trim_end_f = int(trim_end_s * fps)

    usable_start = trim_start_f
    usable_end = total_frames - trim_end_f

    if usable_end <= usable_start:
        return total_frames // 2

    # Margine 5% dentro la zona usabile
    usable_range = usable_end - usable_start
    margin = int(usable_range * 0.05)
    sample_start = usable_start + margin
    sample_end = usable_end - margin

    if sample_end <= sample_start:
        return (usable_start + usable_end) // 2

    positions = np.linspace(sample_start, sample_end, num_samples, dtype=int)

    best_score = -1
    best_frame = (usable_start + usable_end) // 2

    for pos in positions:
        timestamp = pos / fps
        frame = _extract_frame(file_path, timestamp)
        if frame is not None:
            score = _laplacian_variance(frame)
            if score > best_score:
                best_score = score
                best_frame = int(pos)

    return best_frame


def _extract_frame(file_path, timestamp, width=320, height=240):
    """Estrae un singolo frame come array grayscale via ffmpeg pipe."""
    cmd = [
        get_ffmpeg_path(),
        "-ss", f"{timestamp:.3f}",
        "-i", file_path,
        "-vframes", "1",
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-s", f"{width}x{height}",
        "-v", "quiet",
        "-"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0 and len(result.stdout) == width * height:
            return np.frombuffer(result.stdout, dtype=np.uint8).reshape(
                height, width
            )
    except Exception:
        pass
    return None


def _laplacian_variance(frame):
    """Calcola la varianza del Laplaciano (misura di nitidezza).

    Convoluzione 2D manuale con kernel Laplacian 3x3, senza OpenCV.
    """
    frame = frame.astype(np.float64)

    # Kernel Laplaciano:  [0, 1, 0]  [1, -4, 1]  [0, 1, 0]
    # Convoluzione tramite slicing
    laplacian = (
        frame[:-2, 1:-1] +       # sopra
        frame[2:, 1:-1] +        # sotto
        frame[1:-1, :-2] +       # sinistra
        frame[1:-1, 2:] -        # destra
        4 * frame[1:-1, 1:-1]    # centro
    )

    return float(np.var(laplacian))
