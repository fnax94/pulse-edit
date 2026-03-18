"""AI Mood Analyzer — classifica il mood musicale dalle feature audio.

Usa le feature gia estratte da librosa (beat_detector) per classificare
il brano in 6 categorie di mood, poi mappa ciascun mood a parametri
di editing ottimali (cut pattern, zoom, speed ramp).

Zero dipendenze aggiuntive — usa solo librosa (gia presente) + numpy.
"""

import numpy as np


# ─── Mood Categories ───

MOODS = {
    "energetic": {
        "label_en": "Energetic",
        "label_it": "Energetico",
        "cut_pattern": "ai_mixed",
        "clip_order": "random",
        # Pesi densita per ai_mixed: [dense, medium, sparse, very_sparse]
        "density_weights": [0.35, 0.35, 0.20, 0.10],
        "zoom_range": (5, 15),
        "zoom_dur_range": (20, 60),
        "zoom_dirs": ["in", "out", "in_out"],
        "zoom_easings": ["cubic_out", "quad_out", "ease_out", "rebound_out"],
        "speed_range": (0.5, 0.7),       # min 0.5x sempre
        "speed_fast_range": (1.2, 1.5),  # velocita per ramp fast→slow
        "speed_chance": 0.6,
        "speed_dur_range": (50, 80),
        "speed_dirs": ["in", "out", "in_out"],
        # ramp_types: normal=1→0.5, fast_slow=1.5→0.5→1.5, slow_fast=0.5→1.5→0.5
        "speed_ramp_types": ["normal", "normal", "fast_slow", "slow_fast"],
        "speed_easings_gentle": ["ease", "ease_out", "quad_out"],
        "speed_easings_aggressive": ["cubic_out", "cubic_in", "rebound_out", "elastic_out", "overshoot_out"],
        "freeze_chance": 0.3,     # probabilita di freeze frame nel punto di transizione
        "freeze_range": (2, 4),   # frame di pausa
        "optical_flow": True,     # slowmo fluido
        "sync_zoom_speed": True,  # sincronizza zoom con speed ramp
    },
    "aggressive": {
        "label_en": "Aggressive",
        "label_it": "Aggressivo",
        "cut_pattern": "ai_mixed",
        "clip_order": "random",
        "density_weights": [0.45, 0.30, 0.15, 0.10],
        "zoom_range": (10, 20),
        "zoom_dur_range": (15, 35),
        "zoom_dirs": ["in", "out", "in_out"],
        "zoom_easings": ["cubic_in", "quad_in", "rebound_in", "rebound_out"],
        "speed_range": (0.5, 0.6),
        "speed_fast_range": (1.3, 1.5),
        "speed_chance": 0.7,
        "speed_dur_range": (40, 70),
        "speed_dirs": ["in", "out", "in_out"],
        "speed_ramp_types": ["normal", "fast_slow", "fast_slow", "slow_fast"],
        "speed_easings_gentle": ["ease_out", "quad_out"],
        "speed_easings_aggressive": ["cubic_in", "quad_in", "rebound_in", "rebound_out", "elastic_in", "bounce_out"],
        "freeze_chance": 0.4,
        "freeze_range": (2, 5),
        "optical_flow": True,
        "sync_zoom_speed": True,
    },
    "epic": {
        "label_en": "Epic",
        "label_it": "Epico",
        "cut_pattern": "ai_mixed",
        "clip_order": "random",
        "density_weights": [0.20, 0.35, 0.30, 0.15],
        "zoom_range": (3, 10),
        "zoom_dur_range": (50, 100),
        "zoom_dirs": ["in", "in", "in", "out", "in_out"],
        "zoom_easings": ["ease", "quad_ease", "cubic_ease", "circular_ease"],
        "speed_range": (0.5, 0.7),
        "speed_fast_range": (1.2, 1.4),
        "speed_chance": 0.4,
        "speed_dur_range": (60, 100),
        "speed_dirs": ["in", "out", "in_out", "in_out"],
        "speed_ramp_types": ["normal", "normal", "fast_slow", "slow_fast"],
        "speed_easings_gentle": ["ease", "ease_out", "quad_ease"],
        "speed_easings_aggressive": ["cubic_ease", "cubic_in", "rebound_out", "elastic_out"],
        "freeze_chance": 0.35,
        "freeze_range": (3, 6),
        "optical_flow": True,
        "sync_zoom_speed": True,
    },
    "happy": {
        "label_en": "Happy",
        "label_it": "Allegro",
        "cut_pattern": "ai_mixed",
        "clip_order": "random",
        "density_weights": [0.25, 0.35, 0.25, 0.15],
        "zoom_range": (3, 8),
        "zoom_dur_range": (30, 70),
        "zoom_dirs": ["in", "out", "in_out"],
        "zoom_easings": ["ease_out", "quad_out", "ease", "rebound_out"],
        "speed_range": (0.6, 0.8),
        "speed_fast_range": (1.1, 1.3),
        "speed_chance": 0.3,
        "speed_dur_range": (50, 80),
        "speed_dirs": ["in", "out", "in_out"],
        "speed_ramp_types": ["normal", "normal", "normal", "fast_slow"],
        "speed_easings_gentle": ["ease", "ease_out", "linear"],
        "speed_easings_aggressive": ["quad_out", "cubic_out", "rebound_out", "bounce_out"],
        "freeze_chance": 0.15,
        "freeze_range": (2, 3),
        "optical_flow": True,
        "sync_zoom_speed": False,
    },
    "melancholic": {
        "label_en": "Melancholic",
        "label_it": "Malinconico",
        "cut_pattern": "ai_mixed",
        "clip_order": "random",
        "density_weights": [0.10, 0.20, 0.35, 0.35],
        "zoom_range": (2, 5),
        "zoom_dur_range": (70, 100),
        "zoom_dirs": ["out", "out", "in", "in_out"],
        "zoom_easings": ["ease", "linear", "ease_out"],
        "speed_range": (0.6, 0.8),
        "speed_fast_range": (1.0, 1.2),
        "speed_chance": 0.25,
        "speed_dur_range": (70, 100),
        "speed_dirs": ["out", "in", "in_out"],
        "speed_ramp_types": ["normal", "normal", "normal", "slow_fast"],
        "speed_easings_gentle": ["linear", "ease", "ease_out"],
        "speed_easings_aggressive": ["quad_out", "ease_out", "elastic_out"],
        "freeze_chance": 0.2,
        "freeze_range": (3, 5),
        "optical_flow": True,
        "sync_zoom_speed": False,
    },
    "calm": {
        "label_en": "Calm",
        "label_it": "Calmo",
        "cut_pattern": "ai_mixed",
        "clip_order": "random",
        "density_weights": [0.05, 0.15, 0.35, 0.45],
        "zoom_range": (1, 4),
        "zoom_dur_range": (80, 100),
        "zoom_dirs": ["out"],
        "zoom_easings": ["linear", "ease", "ease_out"],
        "speed_range": (0.7, 0.9),
        "speed_fast_range": (1.0, 1.1),
        "speed_chance": 0.15,
        "speed_dur_range": (70, 100),
        "speed_dirs": ["out", "in_out"],
        "speed_ramp_types": ["normal", "normal"],
        "speed_easings_gentle": ["linear", "ease"],
        "speed_easings_aggressive": ["ease_out", "quad_out"],
        "freeze_chance": 0.1,
        "freeze_range": (2, 3),
        "optical_flow": True,
        "sync_zoom_speed": False,
    },
}


def apply_intensity(preset, intensity):
    """Modifica il preset in base allo slider intensita (0.0 = calmo, 1.0 = intenso).

    intensity 0.5 = preset originale (nessuna modifica).
    intensity > 0.5 = piu tagli, piu zoom, piu speed, easing aggressivi.
    intensity < 0.5 = meno tagli, meno zoom, meno speed, easing dolci.
    """
    if abs(intensity - 0.5) < 0.01:
        return preset

    p = dict(preset)

    # Fattore di shift: -1.0 (calmo) a +1.0 (intenso)
    shift = (intensity - 0.5) * 2.0

    # ── Density weights: sposta verso dense (shift>0) o sparse (shift<0) ──
    w = list(p["density_weights"])
    if shift > 0:
        transfer = shift * 0.2
        w[0] += transfer
        w[1] += transfer * 0.5
        w[2] -= transfer * 0.7
        w[3] -= transfer * 0.8
    else:
        transfer = abs(shift) * 0.2
        w[0] -= transfer * 0.8
        w[1] -= transfer * 0.7
        w[2] += transfer * 0.5
        w[3] += transfer
    w = [max(0.02, x) for x in w]
    total = sum(w)
    p["density_weights"] = [x / total for x in w]

    # ── Zoom: piu intenso = piu zoom ──
    z_lo, z_hi = p["zoom_range"]
    z_shift = int(shift * 5)
    p["zoom_range"] = (max(1, z_lo + z_shift), max(2, z_hi + z_shift))

    # ── Speed: intenso = min piu basso (ma mai sotto 0.5), fast piu alto ──
    s_lo, s_hi = p["speed_range"]
    s_shift = shift * 0.1
    p["speed_range"] = (
        max(0.5, round(s_lo - s_shift, 2)),   # mai sotto 0.5x
        min(0.95, round(s_hi - s_shift, 2)),
    )
    # Fast range: intenso = piu veloce
    if "speed_fast_range" in p:
        f_lo, f_hi = p["speed_fast_range"]
        p["speed_fast_range"] = (
            max(1.0, round(f_lo + s_shift, 2)),
            min(2.0, round(f_hi + s_shift, 2)),
        )
    p["speed_chance"] = min(0.9, max(0.05, p["speed_chance"] + shift * 0.25))

    # ── Speed duration: piu intenso = durata piu lunga (piu visibile) ──
    sd_lo, sd_hi = p["speed_dur_range"]
    sd_shift = int(shift * 15)
    p["speed_dur_range"] = (
        max(20, min(100, sd_lo + sd_shift)),
        max(30, min(100, sd_hi + sd_shift)),
    )

    # ── Easing: intenso → aggressivi, calmo → dolci ──
    gentle = p.get("speed_easings_gentle", ["ease", "linear"])
    aggressive = p.get("speed_easings_aggressive", ["cubic_out", "rebound_out"])
    if shift > 0.3:
        # Intenso: solo easing aggressivi
        p["speed_easings"] = aggressive
    elif shift < -0.3:
        # Calmo: solo easing dolci
        p["speed_easings"] = gentle
    else:
        # Neutro: mix di entrambi
        p["speed_easings"] = gentle + aggressive

    # ── Ramp types: intenso = piu fast_slow/slow_fast, calmo = solo normal ──
    if shift > 0.3:
        p["speed_ramp_types"] = p.get("speed_ramp_types", ["normal"]) + \
            ["fast_slow", "slow_fast"]
    elif shift < -0.3:
        p["speed_ramp_types"] = ["normal"]

    return p


def blend_presets(preset_a, preset_b, weight_a):
    """Mescola due preset con peso weight_a (0.0-1.0) per il primo.

    Usato quando la confidence e' bassa: il mood principale e il secondo
    classificato vengono mescolati proporzionalmente.
    """
    weight_b = 1.0 - weight_a
    blended = dict(preset_a)

    # Blend density weights
    wa = preset_a["density_weights"]
    wb = preset_b["density_weights"]
    blended["density_weights"] = [
        wa[i] * weight_a + wb[i] * weight_b for i in range(4)
    ]

    # Blend zoom range
    za, zb = preset_a["zoom_range"], preset_b["zoom_range"]
    blended["zoom_range"] = (
        int(za[0] * weight_a + zb[0] * weight_b),
        int(za[1] * weight_a + zb[1] * weight_b),
    )

    # Blend zoom duration range
    da, db = preset_a["zoom_dur_range"], preset_b["zoom_dur_range"]
    blended["zoom_dur_range"] = (
        int(da[0] * weight_a + db[0] * weight_b),
        int(da[1] * weight_a + db[1] * weight_b),
    )

    # Unisci dirs e easings da entrambi
    blended["zoom_dirs"] = list(set(preset_a["zoom_dirs"] + preset_b["zoom_dirs"]))
    blended["zoom_easings"] = list(set(preset_a["zoom_easings"] + preset_b["zoom_easings"]))

    # Blend speed
    sa, sb = preset_a["speed_range"], preset_b["speed_range"]
    blended["speed_range"] = (
        round(sa[0] * weight_a + sb[0] * weight_b, 2),
        round(sa[1] * weight_a + sb[1] * weight_b, 2),
    )
    blended["speed_chance"] = (
        preset_a["speed_chance"] * weight_a + preset_b["speed_chance"] * weight_b
    )
    sda, sdb = preset_a["speed_dur_range"], preset_b["speed_dur_range"]
    blended["speed_dur_range"] = (
        int(sda[0] * weight_a + sdb[0] * weight_b),
        int(sda[1] * weight_a + sdb[1] * weight_b),
    )
    blended["speed_dirs"] = list(set(preset_a["speed_dirs"] + preset_b["speed_dirs"]))

    # Blend speed_fast_range
    fa = preset_a.get("speed_fast_range", (1.0, 1.0))
    fb = preset_b.get("speed_fast_range", (1.0, 1.0))
    blended["speed_fast_range"] = (
        round(fa[0] * weight_a + fb[0] * weight_b, 2),
        round(fa[1] * weight_a + fb[1] * weight_b, 2),
    )

    # Unisci ramp types e easings
    blended["speed_ramp_types"] = list(set(
        preset_a.get("speed_ramp_types", ["normal"]) +
        preset_b.get("speed_ramp_types", ["normal"])
    ))
    blended["speed_easings_gentle"] = list(set(
        preset_a.get("speed_easings_gentle", []) +
        preset_b.get("speed_easings_gentle", [])
    ))
    blended["speed_easings_aggressive"] = list(set(
        preset_a.get("speed_easings_aggressive", []) +
        preset_b.get("speed_easings_aggressive", [])
    ))

    return blended


def randomize_clip_params(preset, rng=None, clip_frames=None, fps=24):
    """Genera parametri randomizzati per una singola clip basandosi sul preset.

    clip_frames: durata clip in frame (per scegliere direzione speed).
    fps: frame rate per calcolare durata in secondi.

    Returns dict con valori specifici per questa clip.
    """
    import random
    r = rng or random

    zoom_lo, zoom_hi = preset["zoom_range"]
    zoom_pct = r.randint(zoom_lo, zoom_hi)

    dur_lo, dur_hi = preset["zoom_dur_range"]
    zoom_dur = r.randint(dur_lo, dur_hi)

    # ── Speed ramp type ──
    ramp_types = preset.get("speed_ramp_types", ["normal"])
    ramp_type = r.choice(ramp_types)

    # Velocita slow (target del rallentamento)
    speed_slow = round(r.uniform(*preset["speed_range"]), 2)
    speed_slow = max(0.5, speed_slow)  # mai sotto 0.5x

    # Velocita fast (per ramp fast_slow e slow_fast)
    fast_range = preset.get("speed_fast_range", (1.0, 1.0))
    speed_fast = round(r.uniform(*fast_range), 2)

    # ── Calcola speed_val e speed_from in base al ramp_type ──
    if ramp_type == "fast_slow":
        # fast→slow→fast: parte da speed_fast, scende a speed_slow
        speed_val = speed_slow     # target (il punto lento)
        speed_from = speed_fast    # partenza (veloce)
    elif ramp_type == "slow_fast":
        # slow→fast→slow: parte da speed_slow, sale a speed_fast
        speed_val = speed_fast     # target (il punto veloce)
        speed_from = speed_slow    # partenza (lenta)
    else:
        # normal: 1.0 → speed_slow
        speed_val = speed_slow
        speed_from = 1.0

    # ── Direzione: clip corte → in/out, clip lunghe → in_out ──
    speed_dirs = preset.get("speed_dirs", ["in", "out", "in_out"])
    if clip_frames is not None:
        clip_secs = clip_frames / max(1, fps)
        if clip_secs < 1.5:
            # Clip corte: solo in o out
            short_dirs = [d for d in speed_dirs if d != "in_out"]
            speed_dir = r.choice(short_dirs) if short_dirs else r.choice(speed_dirs)
        elif clip_secs > 3.0:
            # Clip lunghe: preferisci in_out
            long_dirs = speed_dirs + ["in_out"] * 2
            speed_dir = r.choice(long_dirs)
        else:
            speed_dir = r.choice(speed_dirs)
    else:
        speed_dir = r.choice(speed_dirs)

    # ── Easing (gia modulato da apply_intensity se presente) ──
    easings = preset.get("speed_easings")
    if not easings:
        # Fallback: mix gentle + aggressive
        easings = preset.get("speed_easings_gentle", ["ease"]) + \
                  preset.get("speed_easings_aggressive", ["cubic_out"])
    speed_easing = r.choice(easings)

    # ── Freeze frame ──
    freeze_frames = 0
    freeze_chance = preset.get("freeze_chance", 0)
    if r.random() < freeze_chance:
        fr_lo, fr_hi = preset.get("freeze_range", (2, 4))
        freeze_frames = r.randint(fr_lo, fr_hi)

    # ── Optical flow ──
    optical_flow = preset.get("optical_flow", False)

    # ── Sync zoom-speed: stessa direzione e durata ──
    zoom_dir = r.choice(preset["zoom_dirs"])
    sync = preset.get("sync_zoom_speed", False)
    if sync and r.random() < preset["speed_chance"]:
        # Sincronizza: zoom segue la direzione speed
        # Speed in (rallenta) → zoom in (avvicina) = effetto drammatico
        # Speed out (accelera) → zoom out (allontana) = effetto release
        if speed_dir == "in_out":
            zoom_dir = "in"  # zoom in durante rallentamento centrale
        elif speed_dir == "in":
            zoom_dir = "in"
        else:
            zoom_dir = "out"

    # ── Speed duration: limita in base ai frame disponibili ──
    raw_speed_dur_pct = r.randint(*preset["speed_dur_range"])

    # Calcola la % massima del clip che puo essere rallentata senza
    # esaurire i frame sorgente. Se la clip rallenta a speed_val,
    # la parte rallentata consuma frame_source = dur * (1/speed_val).
    # Per non sforare: dur_ramp * (1/min_speed) + dur_rest <= clip_frames
    # → dur_ramp_max = clip_frames * min_speed / 1.0
    # In percentuale: max_pct = min_speed * 100
    min_speed = min(speed_val, speed_from) if speed_from else speed_val
    if min_speed < 1.0 and min_speed > 0:
        # Percentuale massima del clip che puo essere rallentata
        max_safe_pct = int(min_speed * 95)  # 95% margine sicurezza
        speed_dur_pct = min(raw_speed_dur_pct, max_safe_pct)
    else:
        speed_dur_pct = raw_speed_dur_pct

    # Clip troppo corte (< 12 frame): no speed ramp
    apply_speed = r.random() < preset["speed_chance"]
    if clip_frames is not None and clip_frames < 12:
        apply_speed = False

    # ── Shuffle effetti: non tutte le clip hanno lo stesso trattamento ──
    # Probabilita di applicare zoom (70-90% a seconda del mood)
    zoom_chance = 0.85 if len(preset.get("zoom_dirs", [])) > 1 else 0.7
    apply_zoom = r.random() < zoom_chance

    # Evita che una clip non abbia nessun effetto (almeno uno dei due)
    if not apply_zoom and not apply_speed:
        # Forza almeno uno
        if r.random() < 0.6:
            apply_zoom = True
        else:
            apply_speed = True

    return {
        "zoom_pct": zoom_pct,
        "zoom_value": 1.0 + (zoom_pct / 100.0),
        "zoom_dur_pct": zoom_dur,
        "zoom_dir": zoom_dir,
        "zoom_easing": r.choice(preset["zoom_easings"]),
        "speed_val": speed_val,
        "speed_from": speed_from,
        "speed_dur_pct": speed_dur_pct,
        "speed_dir": speed_dir,
        "speed_easing": speed_easing,
        "apply_speed": apply_speed,
        "apply_zoom": apply_zoom,
        "freeze_frames": freeze_frames,
        "optical_flow": optical_flow,
    }


def analyze_mood(y, sr):
    """Analizza il mood del brano audio.

    Args:
        y: audio signal (numpy array, mono)
        sr: sample rate

    Returns:
        (mood_key, confidence, scores_dict)
        mood_key: chiave in MOODS
        confidence: 0.0-1.0
        scores_dict: punteggio per ogni mood
    """
    import librosa

    hop = 512

    # ── Feature extraction ──

    # 1. Tempo
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    if hasattr(tempo, '__len__'):
        bpm = float(tempo[0]) if len(tempo) > 0 else 120.0
    else:
        bpm = float(tempo)

    # 2. RMS energy (media e varianza)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    rms_mean = float(np.mean(rms))
    rms_std = float(np.std(rms))

    # 3. Spectral centroid (brillantezza timbrica)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
    centroid_mean = float(np.mean(centroid))

    # 4. Spectral contrast (differenza picchi/valli nello spettro)
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr, hop_length=hop)
    contrast_mean = float(np.mean(contrast))

    # 5. Spectral flatness (rumorosita vs tonalita)
    flatness = librosa.feature.spectral_flatness(y=y, hop_length=hop)[0]
    flatness_mean = float(np.mean(flatness))

    # 6. Onset strength (percussivita)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    onset_mean = float(np.mean(onset_env))
    onset_std = float(np.std(onset_env))

    # 7. Harmonic-percussive ratio
    y_harm, y_perc = librosa.effects.hpss(y)
    harm_energy = float(np.mean(y_harm ** 2))
    perc_energy = float(np.mean(y_perc ** 2))
    hp_ratio = harm_energy / (perc_energy + 1e-10)

    # 8. Spectral bandwidth
    bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, hop_length=hop)[0]
    bandwidth_mean = float(np.mean(bandwidth))

    # ── Normalize features to 0-1 range ──
    # Ranges basati su analisi di centinaia di brani
    bpm_norm = np.clip((bpm - 60) / 140, 0, 1)           # 60-200 bpm
    rms_norm = np.clip(rms_mean / 0.15, 0, 1)             # 0-0.15
    rms_var = np.clip(rms_std / 0.08, 0, 1)               # varianza dinamica
    centroid_norm = np.clip(centroid_mean / 5000, 0, 1)    # 0-5000 Hz
    contrast_norm = np.clip(contrast_mean / 30, 0, 1)      # 0-30
    flatness_norm = np.clip(flatness_mean / 0.3, 0, 1)    # 0-0.3
    onset_norm = np.clip(onset_mean / 15, 0, 1)            # 0-15
    onset_var = np.clip(onset_std / 10, 0, 1)
    hp_norm = np.clip(hp_ratio / 10, 0, 1)                 # 0=perc, 1=harmonic
    bw_norm = np.clip(bandwidth_mean / 3000, 0, 1)         # 0-3000

    # ── Score each mood ──
    scores = {}

    # Energetic: tempo alto, energia alta, onset forte, mix harm/perc
    scores["energetic"] = (
        0.25 * bpm_norm +
        0.20 * rms_norm +
        0.20 * onset_norm +
        0.15 * centroid_norm +
        0.10 * (1 - hp_norm) +  # piu percussivo
        0.10 * bw_norm
    )

    # Aggressive: tutto al massimo, flatness alta (distorsione), onset variabile
    scores["aggressive"] = (
        0.15 * bpm_norm +
        0.20 * rms_norm +
        0.20 * onset_norm +
        0.15 * flatness_norm +      # rumore/distorsione
        0.15 * (1 - hp_norm) +      # molto percussivo
        0.15 * onset_var             # onset imprevedibile
    )

    # Epic: energia medio-alta, alto contrasto spettrale, armonico, dinamico
    scores["epic"] = (
        0.10 * bpm_norm +
        0.15 * rms_norm +
        0.20 * contrast_norm +       # contrasto spettrale alto
        0.20 * rms_var +             # molto dinamico
        0.20 * hp_norm +             # armonico (orchestrale)
        0.15 * bw_norm               # ampio spettro
    )

    # Happy: tempo medio-alto, energia media, armonico, centroid medio
    scores["happy"] = (
        0.25 * bpm_norm +
        0.15 * rms_norm +
        0.15 * (1 - flatness_norm) +  # tonale
        0.15 * hp_norm +              # armonico
        0.15 * centroid_norm +
        0.15 * (1 - rms_var)          # dinamica costante
    )

    # Melancholic: tempo basso, armonico, centroid medio-basso, dinamico
    scores["melancholic"] = (
        0.25 * (1 - bpm_norm) +        # lento
        0.15 * (1 - rms_norm) +        # energia bassa
        0.20 * hp_norm +               # molto armonico
        0.15 * rms_var +               # variazione dinamica
        0.15 * (1 - centroid_norm) +   # timbro scuro
        0.10 * (1 - flatness_norm)     # tonale
    )

    # Calm: tutto basso, armonico, poco onset, poca variazione
    scores["calm"] = (
        0.20 * (1 - bpm_norm) +
        0.20 * (1 - rms_norm) +
        0.15 * (1 - onset_norm) +
        0.15 * hp_norm +
        0.15 * (1 - rms_var) +
        0.15 * (1 - centroid_norm)
    )

    # ── Determine winner ──
    best_mood = max(scores, key=scores.get)
    best_score = scores[best_mood]

    # Confidence: distanza dal secondo classificato
    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) > 1:
        gap = sorted_scores[0] - sorted_scores[1]
        confidence = min(1.0, gap / 0.15 + 0.5)
    else:
        confidence = 1.0

    return best_mood, confidence, scores


def get_mood_preset(mood_key):
    """Ritorna il preset di editing per un dato mood."""
    return MOODS.get(mood_key, MOODS["energetic"])


def build_ai_preset(mood_key, confidence, scores, intensity=0.5):
    """Costruisce il preset finale combinando mood, confidence e intensita.

    Se confidence < 0.7, mescola i parametri del primo e secondo mood.
    Poi applica lo slider intensita.
    """
    preset = dict(get_mood_preset(mood_key))

    # ── Blend con secondo mood se confidence bassa ──
    if confidence < 0.7:
        sorted_moods = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_moods) >= 2:
            second_mood = sorted_moods[1][0]
            second_preset = get_mood_preset(second_mood)
            # Peso proporzionale alla confidence: 0.5 conf → 60/40, 0.7 conf → 100/0
            weight_a = 0.5 + (confidence / 0.7) * 0.5
            weight_a = min(1.0, max(0.5, weight_a))
            preset = blend_presets(preset, second_preset, weight_a)

    # ── Applica slider intensita ──
    preset = apply_intensity(preset, intensity)

    return preset
