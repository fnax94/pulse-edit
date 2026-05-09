"""Beat detection usando librosa."""

import subprocess
import tempfile
import os
import sys
import platform

_IS_WINDOWS = platform.system() == "Windows"
_SUBPROCESS_KWARGS = {"creationflags": 0x08000000} if _IS_WINDOWS else {}


def get_ffmpeg_path():
    """Trova il path di ffmpeg (bundled o sistema)."""
    import logging
    _log = logging.getLogger("pulseedit")
    exe = "ffmpeg.exe" if _IS_WINDOWS else "ffmpeg"
    candidates = []

    if hasattr(sys, '_MEIPASS'):
        for subdir in ["", "Resources", "Frameworks"]:
            bundled = os.path.join(sys._MEIPASS, subdir, exe) if subdir else os.path.join(sys._MEIPASS, exe)
            candidates.append(bundled)
            if os.path.exists(bundled):
                _log.info(f"ffmpeg found at _MEIPASS: {bundled}")
                return bundled

    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
    for subdir in ["Contents/Resources", "Contents/Frameworks", "Contents/MacOS"]:
        bundled = os.path.join(app_dir, subdir, exe)
        candidates.append(bundled)
        if os.path.exists(bundled):
            _log.info(f"ffmpeg found at app_dir: {bundled}")
            return bundled

    import shutil
    which = shutil.which(exe)
    if which:
        _log.info(f"ffmpeg found via which: {which}")
        return which

    if not _IS_WINDOWS and os.path.exists("/opt/homebrew/bin/ffmpeg"):
        return "/opt/homebrew/bin/ffmpeg"
    if not _IS_WINDOWS and os.path.exists("/usr/local/bin/ffmpeg"):
        return "/usr/local/bin/ffmpeg"

    _log.error(f"ffmpeg NOT FOUND. Searched: {candidates}")
    return exe


def extract_audio(file_path):
    """Estrai audio in WAV mono temporaneo. Ritorna il path del wav."""
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    tmp_dir = tempfile.mkdtemp()
    wav_path = os.path.join(tmp_dir, "audio.wav")

    cmd = [
        get_ffmpeg_path(), "-y", "-i", file_path,
        "-vn", "-ac", "1", "-ar", "22050", "-acodec", "pcm_s16le",
        wav_path
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=120, **_SUBPROCESS_KWARGS
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg timeout (file too large or unresponsive)")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[:200]}")
    if not os.path.exists(wav_path):
        raise RuntimeError("ffmpeg did not produce output audio")
    return wav_path


def compute_bar_times(beats_list, beats_per_bar=4):
    """Estrai i tempi dei downbeat (inizio battuta) dai beat rilevati."""
    return [beats_list[i] for i in range(0, len(beats_list), beats_per_bar)]


def compute_subdivisions(bar_times, mode="quarter", all_beats=None):
    """Calcola i punti di suddivisione tra battute consecutive.

    Lavora sulle BATTUTE (marker oro), non sui singoli beat.

    Per quartinato: usa i beat REALI rilevati da librosa (se disponibili),
    cosi le suddivisioni sono precise anche con tempo non perfettamente costante.
    Per terzinato e sestinato: interpola matematicamente tra le battute.

    mode:
        "half":      1 punto a 1/2 — meta battuta
        "triplet":   2 punti a 1/3, 2/3 — terzinato
        "quarter":   3 punti a 1/4, 2/4, 3/4 — quartinato (= beat 2,3,4)
        "sextuplet": 5 punti a 1/6, 2/6, 3/6, 4/6, 5/6 — sestinato
        "eighth":    7 punti a 1/8..7/8 — ottavi
    """
    subdivisions = []
    for i in range(len(bar_times) - 1):
        bar_start = bar_times[i]
        bar_end = bar_times[i + 1]
        interval = bar_end - bar_start

        if mode == "quarter" and all_beats is not None:
            # Usa i beat reali rilevati tra questa battuta e la prossima
            real_beats = [b for b in all_beats
                          if b > bar_start and b < bar_end]
            subdivisions.extend(real_beats)
        elif mode == "half":
            subdivisions.append(bar_start + interval * 0.5)
        elif mode == "triplet":
            for k in range(1, 3):
                subdivisions.append(bar_start + interval * k / 3.0)
        elif mode == "quarter":
            for k in range(1, 4):
                subdivisions.append(bar_start + interval * k / 4.0)
        elif mode == "sextuplet":
            for k in range(1, 6):
                subdivisions.append(bar_start + interval * k / 6.0)
        elif mode == "eighth":
            for k in range(1, 8):
                subdivisions.append(bar_start + interval * k / 8.0)
    return subdivisions


def detect_beats(file_path, sensitivity=0.5):
    """Rileva i beat. Ritorna (bpm, beat_times_array).

    sensitivity: 0.0 (pochi beat) -> 1.0 (molti beat)
    """
    import librosa

    wav_path = extract_audio(file_path)

    try:
        y, sr = librosa.load(wav_path, sr=22050)

        if len(y) < sr:  # meno di 1 secondo
            raise RuntimeError("Audio too short (< 1 second)")

        tempo, beat_frames = librosa.beat.beat_track(
            y=y, sr=sr,
            tightness=100 * (1 - sensitivity) + 10,
            units="frames"
        )

        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        # BPM: gestisci array o scalare, con fallback
        if hasattr(tempo, '__len__') and len(tempo) > 0:
            bpm = float(tempo[0])
        elif not hasattr(tempo, '__len__'):
            bpm = float(tempo)
        else:
            bpm = 120.0

        beats_list = [float(t) for t in beat_times]
        if len(beats_list) < 2:
            return bpm, beats_list, [], []

        # Estendi beat all'inizio dell'audio (intro senza batteria)
        if len(beats_list) >= 2:
            avg_interval = (beats_list[-1] - beats_list[0]) / (len(beats_list) - 1)
            first_beat = beats_list[0]
            prepend = []
            while first_beat - avg_interval >= 0.05:
                first_beat -= avg_interval
                prepend.append(first_beat)
            if prepend:
                beats_list = list(reversed(prepend)) + beats_list

        # Estendi beat fino alla fine dell'audio (fade-out/coda)
        audio_duration = len(y) / sr
        if len(beats_list) >= 2:
            avg_interval = (beats_list[-1] - beats_list[0]) / (len(beats_list) - 1)
            last_beat = beats_list[-1]
            while last_beat + avg_interval < audio_duration - 0.1:
                last_beat += avg_interval
                beats_list.append(last_beat)

        # Upbeat default: quartinato (beat 2,3,4 della battuta)
        bar_times = compute_bar_times(beats_list, 4)
        upbeats = compute_subdivisions(bar_times, "quarter", all_beats=beats_list)

        # ── Analisi musicale multi-feature per Energy Map ──
        import numpy as np
        from scipy.ndimage import uniform_filter1d

        hop = 512

        # Separazione armonica/percussiva
        y_harm, y_perc = librosa.effects.hpss(y)

        def _safe_feature(func, **kwargs):
            """Estrai feature con fallback ad array vuoto."""
            try:
                r = func(**kwargs)
                if hasattr(r, 'shape') and r.ndim > 1:
                    r = r[0]
                return r if len(r) > 0 else np.zeros(1)
            except Exception:
                return np.zeros(1)

        def _norm(arr):
            mx = arr.max() if len(arr) > 0 else 0
            return arr / mx if mx > 0 else arr

        # 7 feature con protezione array vuoti
        onset_env = _safe_feature(librosa.onset.onset_strength, y=y, sr=sr, hop_length=hop)

        centroid = _safe_feature(librosa.feature.spectral_centroid, y=y, sr=sr, hop_length=hop)

        _sc = librosa.feature.spectral_contrast(y=y, sr=sr, hop_length=hop)
        contrast = np.mean(_sc, axis=0) if _sc.size > 0 else np.zeros(1)

        bandwidth = _safe_feature(librosa.feature.spectral_bandwidth, y=y, sr=sr, hop_length=hop)

        flatness = _safe_feature(librosa.feature.spectral_flatness, y=y, hop_length=hop)

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
        if chroma.size > 0 and chroma.shape[1] > 1:
            chroma_diff = np.sqrt(np.sum(np.diff(chroma, axis=1) ** 2, axis=0))
            chroma_diff = np.concatenate([[0], chroma_diff])
        else:
            chroma_diff = np.zeros(1)

        perc_rms = _safe_feature(librosa.feature.rms, y=y_perc, hop_length=hop)

        # Allinea alla stessa lunghezza
        min_len = min(len(onset_env), len(centroid), len(contrast),
                      len(bandwidth), len(flatness), len(chroma_diff),
                      len(perc_rms))
        if min_len < 1:
            return bpm, beats_list, upbeats, [0.5] * len(beats_list)

        features = [onset_env, centroid, contrast, bandwidth,
                    flatness, chroma_diff, perc_rms]
        features = [_norm(f[:min_len]) for f in features]
        weights = [0.20, 0.15, 0.15, 0.10, 0.10, 0.15, 0.15]

        activity = sum(w * f for w, f in zip(weights, features))

        smooth_frames = max(1, int(2.0 * sr / hop))
        activity_smooth = uniform_filter1d(activity, size=smooth_frames)

        frame_times = librosa.frames_to_time(
            np.arange(min_len), sr=sr, hop_length=hop
        )

        # Campiona attivita ad ogni beat time
        energy_per_beat = []
        if len(activity_smooth) > 0 and len(frame_times) > 0:
            for bt in beats_list:
                idx = np.searchsorted(frame_times, bt)
                idx = max(0, min(idx, len(activity_smooth) - 1))
                energy_per_beat.append(float(activity_smooth[idx]))
        else:
            energy_per_beat = [0.5] * len(beats_list)

        # Normalizza a 0-1 con min-max stretching
        # (senza questo, la media di 7 feature normalizzate resta alta
        #  e tutti i beat risultano "alta energia")
        if energy_per_beat:
            min_e = min(energy_per_beat)
            max_e = max(energy_per_beat)
            range_e = max_e - min_e
            if range_e > 0:
                energy_per_beat = [(e - min_e) / range_e for e in energy_per_beat]
            else:
                energy_per_beat = [0.5] * len(energy_per_beat)

        return bpm, beats_list, upbeats, energy_per_beat
    finally:
        try:
            os.remove(wav_path)
            os.rmdir(os.path.dirname(wav_path))
        except OSError:
            pass
