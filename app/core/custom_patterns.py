"""Custom cut patterns — salva e carica pattern utente."""

import json
import os

import platform as _platform
if _platform.system() == "Windows":
    PATTERNS_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PulseEdit", "patterns")
else:
    PATTERNS_DIR = os.path.expanduser("~/Library/Application Support/PulseEdit/patterns")


def _ensure_dir():
    os.makedirs(PATTERNS_DIR, exist_ok=True)


def save_pattern(name, cut_indices):
    """Salva un pattern custom.

    name: nome del pattern
    cut_indices: lista di indici beat dove tagliare
                 (es. [0, 1, 3, 4, 8] = taglia al beat 0,1,3,4,8)
    """
    _ensure_dir()
    data = {"name": name, "cuts": cut_indices}
    path = os.path.join(PATTERNS_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def load_pattern(name):
    """Carica un pattern custom. Ritorna lista di indici o None."""
    path = os.path.join(PATTERNS_DIR, f"{name}.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data.get("cuts", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def list_patterns():
    """Ritorna lista di nomi pattern disponibili."""
    _ensure_dir()
    names = []
    for f in sorted(os.listdir(PATTERNS_DIR)):
        if f.endswith(".json"):
            names.append(f[:-5])
    return names


def delete_pattern(name):
    """Elimina un pattern custom."""
    path = os.path.join(PATTERNS_DIR, f"{name}.json")
    try:
        os.remove(path)
    except OSError:
        pass


def apply_custom_pattern(beat_frames, cut_indices):
    """Applica un pattern custom ai beat frames.

    cut_indices: lista di indici (0-based) dei beat da usare.
    Se un indice supera il numero di beat, viene ciclato.
    """
    n = len(beat_frames)
    if not n or not cut_indices:
        return list(beat_frames)

    result = set()
    for idx in cut_indices:
        actual = idx % n
        result.add(beat_frames[actual])
    return sorted(result)
