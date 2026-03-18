"""Algoritmo centrale per costruire la sequenza di edit a tempo di beat."""


import random


# ─── Cut Pattern System ───

def apply_cut_pattern(beat_frames, upbeat_frames, pattern_name,
                      energy_data=None, bar_frames=None,
                      density_weights=None):
    """Filtra i marker in base al pattern scelto.

    beat_frames: lista ordinata di frame dei beat (tutti, inclusi bar)
    upbeat_frames: lista ordinata di frame degli upbeat (levare)
    bar_frames: lista ordinata di frame dei downbeat (inizio battuta)
    pattern_name: nome del preset

    Ritorna: lista ordinata di frame da usare come punti di taglio.
    """
    if not beat_frames:
        return []
    if bar_frames is None:
        bar_frames = [beat_frames[i] for i in range(0, len(beat_frames), 4)]

    all_markers = sorted(set(beat_frames + upbeat_frames))
    n = len(beat_frames)

    if pattern_name == "every_beat":
        # Taglio su ogni beat (battere) — comportamento classico
        return list(beat_frames)

    elif pattern_name == "beat_upbeat":
        # Taglio su ogni beat + upbeat (doppia velocita)
        return all_markers

    elif pattern_name == "half_time":
        # Taglio ogni 2 beat
        return [beat_frames[i] for i in range(0, n, 2)]

    elif pattern_name == "fast_to_slow":
        # Prima meta: beat + upbeat, seconda meta: ogni 2 beat
        mid = n // 2
        mid_time = beat_frames[mid] if mid < n else beat_frames[-1]

        fast_part = [m for m in all_markers if m <= mid_time]
        slow_part = [beat_frames[i] for i in range(mid, n, 2) if beat_frames[i] > mid_time]
        return sorted(set(fast_part + slow_part))

    elif pattern_name == "slow_to_fast":
        # Prima meta: ogni 2 beat, seconda meta: beat + upbeat
        mid = n // 2
        mid_time = beat_frames[mid] if mid < n else beat_frames[-1]

        slow_part = [beat_frames[i] for i in range(0, mid, 2)]
        fast_part = [m for m in all_markers if m > mid_time]
        return sorted(set(slow_part + fast_part))

    elif pattern_name == "buildup":
        # Progressivamente piu veloce: ogni 4 → ogni 2 → ogni beat → beat+upbeat
        result = set()
        quarter = n // 4
        for i in range(n):
            if i < quarter:
                if i % 4 == 0:
                    result.add(beat_frames[i])
            elif i < quarter * 2:
                if i % 2 == 0:
                    result.add(beat_frames[i])
            elif i < quarter * 3:
                result.add(beat_frames[i])
            else:
                result.add(beat_frames[i])
        # Ultimo quarto: aggiungi anche upbeat
        if quarter * 3 < n:
            last_quarter_start = beat_frames[quarter * 3]
            for ub in upbeat_frames:
                if ub >= last_quarter_start:
                    result.add(ub)
        return sorted(result)

    elif pattern_name == "wedding":
        # Taglio ogni 4 beat — stile matrimoniale, lento e elegante
        return [beat_frames[i] for i in range(0, n, 4)]

    elif pattern_name == "energy_map":
        # Adatta la densita dei tagli all'attivita musicale REALE.
        # Riferimento principale: la BATTUTA (bar) come unita ritmica.
        # Nelle sezioni ad alta energia, attinge anche ai marker rossi
        # (suddivisioni) per tagli piu dinamici, mantenendo il beat.
        n_bars = len(bar_frames)
        if n_bars < 2 or not energy_data:
            return list(bar_frames)

        # Mappa suddivisioni per battuta (grid points tra bar[i] e bar[i+1])
        bar_subdivs = {}
        bar_energy = []
        bar_set = set(bar_frames)
        for bi in range(n_bars):
            bar_start = bar_frames[bi]
            bar_end = bar_frames[bi + 1] if bi + 1 < n_bars else float('inf')

            energies = []
            subdivs = []
            for gi, gf in enumerate(beat_frames):
                if gf >= bar_start and gf < bar_end:
                    if gi < len(energy_data):
                        energies.append(energy_data[gi])
                    if gf not in bar_set and gf > bar_start:
                        subdivs.append(gf)

            bar_energy.append(
                sum(energies) / len(energies) if energies else 0.5
            )
            bar_subdivs[bi] = subdivs

        result = []
        i = 0
        while i < n_bars:
            result.append(bar_frames[i])
            e = bar_energy[i]

            # Quante BATTUTE saltare + uso suddivisioni
            if e > 0.85:
                # Altissima: ogni battuta + suddivisioni interne (upbeat)
                # per tagli frenetici che seguono il groove
                result.extend(bar_subdivs.get(i, []))
                skip = 1
            elif e > 0.7:
                # Alta: ogni battuta, niente suddivisioni
                skip = 1
            elif e > 0.45:
                # Media-alta: ogni 2 battute
                skip = 2
            elif e > 0.25:
                # Media: ogni 4 battute
                skip = 4
            else:
                # Calma: ogni 8 battute
                skip = 8

            i += skip

        # Assicura ultima battuta
        if bar_frames and bar_frames[-1] not in result:
            result.append(bar_frames[-1])
        return sorted(result)

    elif pattern_name == "random_energy_fast":
        # Alta energia: 80% beat, 50% upbeat — molti tagli
        result = set()
        for b in beat_frames:
            if random.random() < 0.8:
                result.add(b)
        for ub in upbeat_frames:
            if random.random() < 0.5:
                result.add(ub)
        if beat_frames:
            result.add(beat_frames[0])
            result.add(beat_frames[-1])
        return sorted(result)

    elif pattern_name == "random_energy_slow":
        # Bassa energia: 50% beat, no upbeat, salta spesso
        result = set()
        for b in beat_frames:
            if random.random() < 0.5:
                result.add(b)
        if beat_frames:
            result.add(beat_frames[0])
            result.add(beat_frames[-1])
        return sorted(result)

    elif pattern_name == "every_bar":
        # Taglio solo sull'inizio di ogni battuta (ogni 4 beat in 4/4)
        return list(bar_frames)

    elif pattern_name == "ai_mixed":
        # Alterna casualmente tra densita diverse per creare varieta
        # di durate clip lungo tutta la timeline.
        # density_weights: [dense, medium, sparse, very_sparse] probabilita
        # energy_data: se presente, modula i pesi in base all'energia locale
        n_bars = len(bar_frames)
        if n_bars < 2:
            return list(beat_frames)

        # Pesi di default se non forniti
        weights = density_weights or [0.25, 0.25, 0.25, 0.25]
        densities = ["dense", "medium", "sparse", "very_sparse"]

        # Mappa beat e suddivisioni per ogni battuta
        bar_beats = {}
        bar_set = set(bar_frames)
        bar_energy_map = []
        for bi in range(n_bars):
            bar_start = bar_frames[bi]
            bar_end = bar_frames[bi + 1] if bi + 1 < n_bars else float('inf')
            bar_beats[bi] = [b for b in all_markers if b >= bar_start and b < bar_end]

            # Calcola energia media per questa battuta
            if energy_data:
                energies = []
                for gi, gf in enumerate(beat_frames):
                    if gf >= bar_start and gf < bar_end and gi < len(energy_data):
                        energies.append(energy_data[gi])
                bar_energy_map.append(
                    sum(energies) / len(energies) if energies else 0.5
                )
            else:
                bar_energy_map.append(0.5)

        result = set()
        i = 0
        while i < n_bars:
            # Modula pesi in base all'energia locale della battuta
            e = bar_energy_map[i]
            w = list(weights)
            if energy_data:
                # energia alta (>0.6) → sposta peso verso dense
                # energia bassa (<0.4) → sposta peso verso sparse
                energy_shift = (e - 0.5) * 0.4
                w[0] += energy_shift        # dense
                w[1] += energy_shift * 0.3  # medium
                w[2] -= energy_shift * 0.3  # sparse
                w[3] -= energy_shift        # very_sparse
                w = [max(0.02, x) for x in w]
                total = sum(w)
                w = [x / total for x in w]

            # Scelta pesata della densita
            d = random.choices(densities, weights=w, k=1)[0]

            if d == "dense":
                # Tutti i marker (beat + suddivisioni) — clip molto corte
                result.update(bar_beats.get(i, [bar_frames[i]]))
                i += 1
            elif d == "medium":
                # Solo beat principali — clip medie
                result.add(bar_frames[i])
                beats_in_bar = [b for b in beat_frames
                                if b >= bar_frames[i] and
                                b < (bar_frames[i + 1] if i + 1 < n_bars else float('inf'))]
                for b in beats_in_bar[::2]:
                    result.add(b)
                i += 1
            elif d == "sparse":
                # Solo downbeat — clip lunghe (1 battuta)
                result.add(bar_frames[i])
                i += 1
            else:
                # Ogni 2 battute — clip molto lunghe
                result.add(bar_frames[i])
                i += 2

        # Assicura primo e ultimo
        if bar_frames:
            result.add(bar_frames[0])
            result.add(bar_frames[-1])
        return sorted(result)

    else:
        return list(beat_frames)


# ─── Pattern metadata ───

CUT_PATTERNS = [
    ("energy_map", "Energy Map (Auto)"),
    ("every_beat", "Every Beat"),
    ("every_bar", "Every Bar (4/4)"),
    ("beat_upbeat", "Beat + Upbeat"),
    ("half_time", "Half Time"),
    ("fast_to_slow", "Fast → Slow"),
    ("slow_to_fast", "Slow → Fast"),
    ("buildup", "Buildup"),
    ("wedding", "Wedding / Slow"),
    ("random_energy_fast", "Random Energy Fast"),
    ("random_energy_slow", "Random Energy Slow"),
]


def build_edit_sequence_from_markers(marker_frames, clips_info, timeline_fps,
                                      clip_order="sequential",
                                      trim_start_s=0, trim_end_s=0,
                                      unique_clips=False):
    """Costruisce la sequenza di clip basandosi sulle posizioni dei marker.

    I marker sono la fonte di verita: le durate dei segmenti sulla timeline
    sono calcolate dalla differenza tra marker consecutivi.

    Per allineare i tagli ai marker:
    1. Prepende frame 0 se il primo marker non e' all'inizio, cosi il primo
       clip riempie lo spazio prima del primo beat.
    2. Usa correzione errore cumulativa per evitare drift da arrotondamento
       FPS (es. 29.97 sorgente su timeline 50fps).

    Args:
        marker_frames: lista ordinata di frame timeline dei marker
        clips_info: lista di dict con chiavi:
            - media_pool_item: oggetto MediaPoolItem di Resolve
            - frames: int, frame totali del clip (fps sorgente)
            - best_frame: int, frame piu nitido (fps sorgente)
            - clip_fps: float, fps del clip sorgente
        timeline_fps: frame rate della timeline (float)
        clip_order: "sequential" o "random"
        trim_start_s: secondi da tagliare dall'inizio di ogni clip
        trim_end_s: secondi da tagliare dalla fine di ogni clip

    Returns:
        lista di dict {mediaPoolItem, startFrame, endFrame}
        startFrame/endFrame sono in frame del clip sorgente.
    """
    if not marker_frames or len(marker_frames) < 2 or not clips_info:
        return []

    try:
        from app.licensing import storage as _cfg
        _v = getattr(_cfg, '_MODULE_SIG', '') == "e4a7c1f8d93b2065"
        _v = _v and (_cfg._auth(4919) == (4919 ^ 0x3f7a9c2e1b5d0847))
        if not _v or (_cfg.is_trial_expired() and not _cfg.load_license()):
            return []
    except Exception:
        return []

    if clip_order == "random":
        clips = list(clips_info)
        random.shuffle(clips)
    else:
        clips = list(clips_info)

    # Ordina i marker per sicurezza
    sorted_markers = sorted(marker_frames)

    # Se il primo marker non e' all'inizio della timeline, prependi frame 0
    # cosi il primo clip riempie lo spazio prima del primo beat e tutti i
    # tagli successivi cadono esattamente sulle posizioni dei marker.
    if sorted_markers[0] > 0:
        sorted_markers.insert(0, 0)

    import math

    entries = []
    clip_idx = 0
    num_clips = len(clips)
    # Conta quante volte abbiamo ciclato tutte le clip (per re-shuffle)
    _cycle_count = 0

    # Playhead per clip: traccia dove siamo arrivati nella clip per non
    # ripetere lo stesso segmento. Chiave = indice clip, valore = frame corrente.
    clip_playheads = {}

    # Posizione assoluta sulla timeline (frame accumulati reali).
    # Confrontata con la posizione target (dal marker) ad ogni segmento
    # per compensare immediatamente qualsiasi drift da arrotondamento FPS.
    tl_cursor = 0
    tl_origin = sorted_markers[0]

    for i in range(len(sorted_markers) - 1):
        # Posizione target assoluta alla fine di questo segmento
        target_tl_end = sorted_markers[i + 1] - tl_origin
        # Frame timeline necessari = differenza tra target e posizione reale
        needed_tl = target_tl_end - tl_cursor
        if needed_tl <= 0:
            continue

        if unique_clips and clip_idx >= num_clips:
            break

        # Re-shuffle ogni volta che abbiamo usato tutte le clip,
        # evitando che la clip appena usata sia la prima del nuovo ciclo
        if clip_order == "random" and clip_idx > 0 and clip_idx % num_clips == 0:
            _cycle_count += 1
            last_used = clips[(clip_idx - 1) % num_clips]
            random.shuffle(clips)
            # Se la prima clip del nuovo ciclo e' uguale all'ultima usata, swappa
            if num_clips > 1 and clips[0] is last_used:
                swap_idx = random.randint(1, num_clips - 1)
                clips[0], clips[swap_idx] = clips[swap_idx], clips[0]
            clip_playheads.clear()

        actual_clip_idx = clip_idx % num_clips
        clip = clips[actual_clip_idx]
        clip_idx += 1

        total_frames = clip["frames"]
        mpi = clip["media_pool_item"]
        clip_fps = clip.get("clip_fps", timeline_fps) or timeline_fps

        # Protezione divisione per zero
        if timeline_fps <= 0:
            timeline_fps = 24.0
        if clip_fps <= 0:
            clip_fps = timeline_fps

        # Calcola frame sorgente necessari.
        # Resolve conforma: 1 secondo sorgente = 1 secondo timeline.
        # Per clip con FPS diverso servono piu/meno frame sorgente.
        fps_ratio = clip_fps / timeline_fps
        same_fps = abs(fps_ratio - 1.0) < 0.001

        if same_fps:
            segment_frames = max(1, needed_tl)
        else:
            # Prova floor e ceil, scegli quello che da' esattamente needed_tl
            # frame sulla timeline (minimizza l'errore di arrotondamento).
            exact_src = needed_tl * fps_ratio
            src_lo = max(1, math.floor(exact_src))
            src_hi = max(1, math.ceil(exact_src))
            tl_lo = int(src_lo * timeline_fps / clip_fps)
            tl_hi = int(src_hi * timeline_fps / clip_fps)
            if abs(tl_lo - needed_tl) <= abs(tl_hi - needed_tl):
                segment_frames = src_lo
            else:
                segment_frames = src_hi

        # Trim in frame sorgente
        trim_start_f = round(trim_start_s * clip_fps)
        trim_end_f = round(trim_end_s * clip_fps)

        # Range usabile dopo trim
        usable_start = trim_start_f
        usable_end = total_frames - trim_end_f

        if usable_end <= usable_start:
            usable_start = 0
            usable_end = total_frames

        usable_range = usable_end - usable_start

        # Se il clip trimmato e' troppo corto, usa il clip intero (ignora trim)
        if segment_frames > usable_range:
            usable_start = 0
            usable_end = total_frames
            usable_range = total_frames

        if segment_frames >= usable_range:
            start_frame = usable_start
            end_frame = usable_end
        else:
            if clip_order == "random":
                # Punto di ingresso casuale nella clip
                max_start = usable_end - segment_frames
                start_frame = random.randint(usable_start, max(usable_start, max_start))
            else:
                # Playhead sequenziale: ogni volta prende il segmento successivo
                playhead = clip_playheads.get(actual_clip_idx, usable_start)
                if playhead + segment_frames > usable_end:
                    playhead = usable_start
                start_frame = playhead
                clip_playheads[actual_clip_idx] = start_frame + segment_frames

            end_frame = start_frame + segment_frames

        # Aggiorna cursore timeline con i frame REALMENTE occupati
        actual_source = end_frame - start_frame
        if same_fps:
            tl_cursor += actual_source
        else:
            tl_cursor += int(actual_source * timeline_fps / clip_fps)

        entries.append({
            "mediaPoolItem": mpi,
            "startFrame": start_frame,
            "endFrame": end_frame,
            "clip_fps": clip_fps,
        })

    return entries
