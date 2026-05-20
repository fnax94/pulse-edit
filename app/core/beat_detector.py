"""Beat detection: beat_this DNN (ISMIR 2024) primario + librosa fallback."""

import subprocess
import tempfile
import os
import sys
import platform

_IS_WINDOWS = platform.system() == "Windows"
_SUBPROCESS_KWARGS = {"creationflags": 0x08000000} if _IS_WINDOWS else {}

# When frozen by PyInstaller, point torch hub cache to bundled checkpoints
# so beat_this loads 'final0' offline without HF/torch.hub download.
if hasattr(sys, '_MEIPASS'):
    _bundled_cache = os.path.join(sys._MEIPASS, "model_cache")
    if os.path.isdir(_bundled_cache):
        os.environ.setdefault("TORCH_HOME", _bundled_cache)


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


def extract_audio(file_path, start_s=None, end_s=None):
    """Estrai audio in WAV mono temporaneo. Ritorna il path del wav.

    Se start_s/end_s sono dati, estrae solo quella porzione (per la feature
    "select audio range"). I beat times nel detector vengono poi shiftati di
    +start_s per matchare la timeline DR originale.
    """
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    tmp_dir = tempfile.mkdtemp()
    wav_path = os.path.join(tmp_dir, "audio.wav")

    cmd = [get_ffmpeg_path(), "-y"]
    # Ordine importante: -ss prima di -i = seek input veloce; per precision
    # decoder-accurate usiamo -ss dopo -i ma e' piu' lento. Compromesso:
    # -ss prima per cut grossolano + -accurate_seek (default in ffmpeg moderno).
    if start_s is not None and float(start_s) > 0.001:
        cmd += ["-ss", f"{float(start_s):.3f}"]
    cmd += ["-i", file_path]
    if end_s is not None and start_s is not None and float(end_s) > float(start_s):
        duration = float(end_s) - float(start_s)
        cmd += ["-t", f"{duration:.3f}"]
    cmd += [
        "-vn", "-ac", "1", "-ar", "22050", "-acodec", "pcm_s16le",
        wav_path
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=120, **_SUBPROCESS_KWARGS
        )
    except FileNotFoundError:
        ffmpeg_path = get_ffmpeg_path()
        raise RuntimeError(
            f"ffmpeg not found at: {ffmpeg_path}\n\n"
            "Please make sure PulseEdit.app is in your Applications folder.\n"
            "If the problem persists, contact support at abramo.benedetti@gmail.com"
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


def _detect_beats_dnn(wav_path):
    """Beat detection via beat_this (ISMIR 2024 DNN transformer).
    Ritorna (beats_list, downbeats_list) o None se modulo non disponibile/errore.

    Loggato a livello WARNING per ogni failure mode così non si verifica più
    il silent-fallback a librosa (caso v1.5.2: einops + rotary_embedding_torch
    mancanti dal bundle → import OK ma instantiation fallisce silenziosamente).
    """
    import logging
    _log = logging.getLogger("pulseedit")
    try:
        from beat_this.inference import File2Beats
    except Exception as e:
        _log.warning(f"beat_this DNN unavailable (import failed: {type(e).__name__}: {e}) — falling back to librosa")
        return None
    try:
        b2b = File2Beats(checkpoint_path="final0", dbn=False)
    except Exception as e:
        _log.warning(f"beat_this DNN init failed ({type(e).__name__}: {e}) — falling back to librosa. "
                     f"TORCH_HOME={os.environ.get('TORCH_HOME', '(unset)')}")
        return None
    try:
        beats_arr, downbeats_arr = b2b(wav_path)
        beats_list = [float(b) for b in beats_arr]
        downbeats_list = [float(b) for b in downbeats_arr]
        if len(beats_list) < 2:
            _log.warning(f"beat_this DNN returned only {len(beats_list)} beats — falling back to librosa")
            return None
        _log.info(f"beat_this DNN inference OK: {len(beats_list)} beats, {len(downbeats_list)} downbeats")
        return beats_list, downbeats_list
    except Exception as e:
        _log.warning(f"beat_this DNN inference failed ({type(e).__name__}: {e}) — falling back to librosa")
        return None


def _refine_beats_linreg(beats_list, audio_duration):
    """Linear regression sui beats: slope = beat_interval esatto, intercept = first_beat.
    Genera griglia uniforme estesa fino alla fine audio. Riduce drift cumulativo.
    """
    if len(beats_list) < 4:
        return beats_list
    import numpy as np
    indices = np.arange(len(beats_list))
    slope, intercept = np.polyfit(indices, beats_list, 1)
    beat_interval_s = float(slope)
    first_beat_fit = float(intercept)
    if beat_interval_s <= 0:
        return beats_list
    # Estendi indietro a 0 (intro senza batteria)
    first = first_beat_fit
    while first - beat_interval_s >= 0.05:
        first -= beat_interval_s
    # Estendi fino a fine audio
    num_beats = int((audio_duration - first) / beat_interval_s) + 1
    return [first + i * beat_interval_s for i in range(num_beats)]


def detect_beats(file_path, sensitivity=0.5, start_s=None, end_s=None):
    """Rileva i beat. Ritorna (bpm, beat_times, upbeats, energy_per_beat).

    Tenta beat_this (DNN ISMIR 2024) come algoritmo primario; ricade su
    librosa.beat.beat_track se il modulo non e' disponibile o fallisce.
    sensitivity: 0.0 (pochi beat) -> 1.0 (molti beat). Usata solo nel fallback librosa.

    start_s/end_s: porzione di audio in secondi. Se None, usa l'intero file.
    I beat_times restituiti sono sempre nel reference frame del file originale
    (non della porzione), cosi' la timeline DR resta coerente.
    """
    import librosa

    wav_path = extract_audio(file_path, start_s=start_s, end_s=end_s)
    _offset = float(start_s) if (start_s is not None and float(start_s) > 0.001) else 0.0

    try:
        y, sr = librosa.load(wav_path, sr=22050)

        if len(y) < sr:  # meno di 1 secondo
            raise RuntimeError("Audio too short (< 1 second)")

        audio_duration = len(y) / sr
        dnn_result = _detect_beats_dnn(wav_path)

        if dnn_result is not None:
            beats_list, dnn_downbeats = dnn_result
            # Linear regression refinement (BPM esatto, no drift cumulativo)
            beats_list = _refine_beats_linreg(beats_list, audio_duration)
            import numpy as np
            if len(beats_list) >= 2:
                bpm = 60.0 / float(np.median(np.diff(beats_list)))
            else:
                bpm = 120.0
            # Downbeat: usa i downbeats della DNN come ancora, poi ogni 4 beat
            if dnn_downbeats and len(beats_list) >= 4:
                # Allinea al primo downbeat DNN ricomputato sulla griglia raffinata
                first_db = dnn_downbeats[0]
                # Trova l'indice del beat piu' vicino al first downbeat
                start_idx = min(range(len(beats_list)),
                                key=lambda i: abs(beats_list[i] - first_db))
                upbeats = [beats_list[i] for i in range(start_idx, len(beats_list), 4)]
            else:
                bar_times = compute_bar_times(beats_list, 4)
                upbeats = compute_subdivisions(bar_times, "quarter", all_beats=beats_list)
        else:
            # Fallback librosa
            tempo, beat_frames = librosa.beat.beat_track(
                y=y, sr=sr,
                tightness=100 * (1 - sensitivity) + 10,
                units="frames"
            )
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)
            if hasattr(tempo, '__len__') and len(tempo) > 0:
                bpm = float(tempo[0])
            elif not hasattr(tempo, '__len__'):
                bpm = float(tempo)
            else:
                bpm = 120.0
            beats_list = [float(t) for t in beat_times]
            if len(beats_list) < 2:
                return bpm, beats_list, [], []
            # Estendi beat all'inizio
            avg_interval = (beats_list[-1] - beats_list[0]) / (len(beats_list) - 1)
            first_beat = beats_list[0]
            prepend = []
            while first_beat - avg_interval >= 0.05:
                first_beat -= avg_interval
                prepend.append(first_beat)
            if prepend:
                beats_list = list(reversed(prepend)) + beats_list
            # Estendi fino alla fine
            avg_interval = (beats_list[-1] - beats_list[0]) / (len(beats_list) - 1)
            last_beat = beats_list[-1]
            while last_beat + avg_interval < audio_duration - 0.1:
                last_beat += avg_interval
                beats_list.append(last_beat)
            # Upbeats quartinati
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

        # Se l'utente ha selezionato un range (start_s > 0), shifta i beat
        # times nel reference frame del file originale cosi' la timeline DR
        # resta coerente.
        if _offset > 0:
            beats_list = [b + _offset for b in beats_list]
            upbeats = [u + _offset for u in upbeats]

        return bpm, beats_list, upbeats, energy_per_beat
    finally:
        try:
            os.remove(wav_path)
            os.rmdir(os.path.dirname(wav_path))
        except OSError:
            pass


def get_waveform_peaks(file_path, num_bins=1000, max_duration_s=None):
    """Ritorna (peaks, duration_s) per drawing waveform in UI.

    peaks: lista di float 0..1 di lunghezza num_bins, rappresentano l'inviluppo
    audio (max abs per bin). duration_s: durata totale dell'audio in secondi.

    Veloce: ~0.5-2s per file mediante decimation con librosa.
    """
    import librosa
    import numpy as np
    # Carica audio a sample rate basso (8 kHz basta per draw waveform)
    duration = None
    if max_duration_s and float(max_duration_s) > 0:
        duration = float(max_duration_s)
    y, sr = librosa.load(file_path, sr=8000, mono=True, duration=duration)
    if len(y) == 0:
        return [0.0] * num_bins, 0.0
    total_duration = len(y) / sr
    # Bin l'audio in num_bins finestre, prendi max abs per bin
    bin_size = max(1, len(y) // num_bins)
    peaks = []
    for i in range(num_bins):
        start = i * bin_size
        end = min(len(y), start + bin_size)
        if start >= len(y):
            peaks.append(0.0)
            continue
        chunk = y[start:end]
        peaks.append(float(np.abs(chunk).max()))
    # Normalizza
    mx = max(peaks) if peaks else 1.0
    if mx > 0:
        peaks = [p / mx for p in peaks]
    return peaks, total_duration
