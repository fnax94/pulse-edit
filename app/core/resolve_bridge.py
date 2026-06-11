"""Bridge per DaVinci Resolve — esteso per Pulse Edit."""

import sys
import os
import math


# ─── Zoom easing presets ───

ZOOM_EASINGS = [
    ("none", "None"),
    ("linear", "Linear"),
    ("ease_in", "Ease In"),
    ("quad_in", "Quad In"),
    ("cubic_in", "Cubic In"),
    ("ease_out", "Ease Out"),
    ("quad_out", "Quad Out"),
    ("cubic_out", "Cubic Out"),
    ("ease", "Ease"),
    ("quad_ease", "Quad Ease"),
    ("cubic_ease", "Cubic Ease"),
    ("circular_ease", "Circular Ease"),
    ("rebound_in", "Rebound In"),
    ("rebound_out", "Rebound Out"),
    ("elastic_out", "Elastic Out"),
    ("elastic_in", "Elastic In"),
    ("bounce_out", "Bounce Out"),
    ("overshoot_out", "Overshoot"),
]


def _bounce_out(t):
    if t < 1 / 2.75:
        return 7.5625 * t * t
    elif t < 2 / 2.75:
        t -= 1.5 / 2.75
        return 7.5625 * t * t + 0.75
    elif t < 2.5 / 2.75:
        t -= 2.25 / 2.75
        return 7.5625 * t * t + 0.9375
    else:
        t -= 2.625 / 2.75
        return 7.5625 * t * t + 0.984375


def _easing(t, ease_type):
    """Calcola il valore di easing per t in [0,1]. Ritorna progresso in [0,1]."""
    if ease_type == "linear":
        return t
    elif ease_type == "ease_in":
        return 1 - math.cos(t * math.pi / 2)
    elif ease_type == "ease_out":
        return math.sin(t * math.pi / 2)
    elif ease_type == "ease":
        return -(math.cos(math.pi * t) - 1) / 2
    elif ease_type == "quad_in":
        return t * t
    elif ease_type == "quad_out":
        return 1 - (1 - t) ** 2
    elif ease_type == "quad_ease":
        return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2
    elif ease_type == "cubic_in":
        return t ** 3
    elif ease_type == "cubic_out":
        return 1 - (1 - t) ** 3
    elif ease_type == "cubic_ease":
        return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
    elif ease_type == "circular_ease":
        if t < 0.5:
            return (1 - math.sqrt(max(0, 1 - (2 * t) ** 2))) / 2
        else:
            return (math.sqrt(max(0, 1 - (-2 * t + 2) ** 2)) + 1) / 2
    elif ease_type == "rebound_in":
        # Back ease-in: leggero overshoot all'inizio
        s = 1.70158
        return t * t * ((s + 1) * t - s)
    elif ease_type == "rebound_out":
        # Back ease-out: overshoot poi settle
        s = 1.70158
        t2 = t - 1
        return t2 * t2 * ((s + 1) * t2 + s) + 1
    elif ease_type == "elastic_out":
        # Elastic: oscillazione smorzata — molto usato nei reel fashion
        if t == 0 or t == 1:
            return t
        return math.pow(2, -10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1
    elif ease_type == "elastic_in":
        if t == 0 or t == 1:
            return t
        return -math.pow(2, 10 * t - 10) * math.sin((t * 10 - 10.75) * (2 * math.pi) / 3)
    elif ease_type == "bounce_out":
        # Bounce: rimbalzo alla fine — impatto visivo forte
        if t < 1 / 2.75:
            return 7.5625 * t * t
        elif t < 2 / 2.75:
            t -= 1.5 / 2.75
            return 7.5625 * t * t + 0.75
        elif t < 2.5 / 2.75:
            t -= 2.25 / 2.75
            return 7.5625 * t * t + 0.9375
        else:
            t -= 2.625 / 2.75
            return 7.5625 * t * t + 0.984375
    elif ease_type == "overshoot_out":
        # Overshoot forte poi ritorno — effetto "snap"
        s = 2.5  # overshoot piu marcato del rebound
        t2 = t - 1
        return t2 * t2 * ((s + 1) * t2 + s) + 1
    return t


def _sample_easing(ease_type, num_samples=10):
    """Genera punti campione della curva di easing.

    Ritorna lista di (t, value) dove t in [0,1] e value in [0,1].
    """
    points = []
    for i in range(num_samples + 1):
        t = i / num_samples
        v = _easing(t, ease_type)
        points.append((t, v))
    return points

import platform as _platform
import re as _re
import subprocess as _subprocess
import time as _time
import logging as _logging

_log = _logging.getLogger("pulseedit")
_IS_WINDOWS = _platform.system() == "Windows"
_IS_MAC = _platform.system() == "Darwin"

def _config_path():
    if _IS_WINDOWS:
        return os.path.join(os.environ.get("APPDATA", ""), "PulseEdit", "resolve_config.json")
    return os.path.expanduser("~/Library/Application Support/PulseEdit/resolve_config.json")

def load_custom_resolve_path():
    try:
        import json
        with open(_config_path(), "r") as f:
            data = json.load(f)
        return data.get("resolve_path", "")
    except Exception:
        return ""

def save_custom_resolve_path(path):
    import json
    cfg = _config_path()
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w") as f:
        json.dump({"resolve_path": path}, f)
    _log.info(f"Saved custom Resolve path: {path}")

def _find_first_existing(paths):
    return next((p for p in paths if os.path.isdir(p)), paths[0] if paths else "")


def _scan_all_drives_windows(resolve_root, _pf, _pf86, _pd, module_paths, lib_paths):
    """EXPENSIVE all-drive filesystem scan for DaVinciResolveScript.py / fusionscript.dll.

    Probes every drive letter and does a recursive os.walk (depth 5). Each drive's
    I/O is wrapped in try/except so a disconnected / sleeping network or external
    drive that does not respond is skipped instead of hanging. Mutates
    module_paths / lib_paths in place (inserting discovered dirs at the front).
    """
    scan_roots = set()
    if resolve_root:
        scan_roots.add(resolve_root)
    for base in [_pf, _pf86, _pd]:
        try:
            bm = os.path.join(base, "Blackmagic Design")
            if os.path.isdir(bm):
                scan_roots.add(bm)
        except (PermissionError, OSError):
            pass
    try:
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            # Wrap each drive's probing so an unresponsive drive can't hang us.
            try:
                if not os.path.exists(drive):
                    continue
                for subfolder in ["Program Files", "Program Files (x86)", "Blackmagic Design"]:
                    bm = os.path.join(drive, subfolder, "Blackmagic Design")
                    if os.path.isdir(bm):
                        scan_roots.add(bm)
                bm_root = os.path.join(drive, "Blackmagic Design")
                if os.path.isdir(bm_root):
                    scan_roots.add(bm_root)
                for pf in ["Program Files", "Program Files (x86)"]:
                    resolve_dir = os.path.join(drive, pf, "Blackmagic Design", "DaVinci Resolve")
                    if os.path.isdir(resolve_dir):
                        scan_roots.add(resolve_dir)
                # Scan root-level folders that might contain Resolve (e.g. D:\DaVinci)
                try:
                    for entry in os.listdir(drive):
                        if "davinci" in entry.lower() or "resolve" in entry.lower() or "blackmagic" in entry.lower():
                            candidate = os.path.join(drive, entry)
                            if os.path.isdir(candidate):
                                scan_roots.add(candidate)
                except (PermissionError, OSError):
                    pass
            except (PermissionError, OSError):
                continue
    except Exception:
        pass
    for root_dir in scan_roots:
        try:
            for dirpath, dirnames, filenames in os.walk(root_dir):
                if "DaVinciResolveScript.py" in filenames:
                    if dirpath not in module_paths:
                        module_paths.insert(0, dirpath)
                        _log.info(f"Filesystem scan found module: {dirpath}")
                for dll_name in ["fusionscript.dll", "FusionScript.dll", "fusionscript64.dll"]:
                    if dll_name in filenames:
                        if dirpath not in lib_paths:
                            lib_paths.insert(0, dirpath)
                            _log.info(f"Filesystem scan found lib ({dll_name}): {dirpath}")
                        break
                depth = dirpath.replace(root_dir, "").count(os.sep)
                if depth > 5:
                    dirnames.clear()
        except (PermissionError, OSError):
            pass


def _cache_discovered_resolve_root(module_paths):
    """Cache the Resolve install root derived from a scan-discovered module path.

    Walks up from a discovered .../Developer/Scripting/Modules (or similar) dir to
    the install root and saves it to resolve_config.json so the next launch finds
    it via the cheap custom-path branch (step 0) and never runs the all-drive scan
    again. Best-effort: never raises, never overwrites an existing user config.
    """
    try:
        if load_custom_resolve_path():
            return  # don't clobber a user-set path
        for p in module_paths:
            if not (p and os.path.isdir(p)):
                continue
            norm = p.lower().replace("/", os.sep)
            # Trim known module subpaths back to the install root.
            for suffix in [
                os.sep.join(["developer", "scripting", "modules"]),
                os.sep.join(["support", "developer", "scripting", "modules"]),
                os.sep.join(["scripting", "modules"]),
            ]:
                idx = norm.rfind(suffix)
                if idx != -1:
                    root = p[:idx].rstrip("/\\" + os.sep)
                    if root and os.path.isdir(root):
                        save_custom_resolve_path(root)
                        return
    except Exception:
        pass


def _discover_resolve_paths_windows(force_scan=False):
    """Auto-discover DaVinci Resolve install path on Windows via registry + filesystem scan.

    Cheap sources (custom path, registry, hardcoded Program Files paths, env vars)
    always run. The expensive all-drive filesystem scan only runs when force_scan
    is True or when the cheap sources found no existing module path.
    """
    module_paths = []
    lib_paths = []
    resolve_root = None

    # 0. User-configured custom path (highest priority)
    custom = load_custom_resolve_path()
    if custom and os.path.isdir(custom):
        _log.info(f"Using custom Resolve path: {custom}")
        resolve_root = custom
        for sub in ["Developer/Scripting/Modules", "Support/Developer/Scripting/Modules", "Scripting/Modules"]:
            module_paths.append(os.path.join(custom, sub.replace("/", os.sep)))
        for sub in ["Libraries/Fusion", "Fusion", ""]:
            lib_paths.append(os.path.join(custom, sub.replace("/", os.sep)) if sub else custom)

    # 1. Try Windows Registry
    try:
        import winreg
        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for key_path in [
                r"SOFTWARE\Blackmagic Design\DaVinci Resolve",
                r"SOFTWARE\WOW6432Node\Blackmagic Design\DaVinci Resolve",
            ]:
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        for val_name in ["InstallPath", "InstallDir", ""]:
                            try:
                                val, _ = winreg.QueryValueEx(key, val_name)
                                if val and os.path.isdir(val):
                                    resolve_root = val
                                    break
                            except (FileNotFoundError, OSError):
                                pass
                    if resolve_root:
                        break
                except (FileNotFoundError, OSError):
                    pass
            if resolve_root:
                break
    except ImportError:
        pass

    # 2. If registry found a root, derive paths from it
    if resolve_root:
        _log.info(f"Registry found Resolve at: {resolve_root}")
        module_paths.append(os.path.join(resolve_root, "Developer", "Scripting", "Modules"))
        module_paths.append(os.path.join(resolve_root, "Support", "Developer", "Scripting", "Modules"))
        lib_paths.append(os.path.join(resolve_root, "Libraries", "Fusion"))
        lib_paths.append(os.path.join(resolve_root, "Fusion"))
        lib_paths.append(resolve_root)

    # 3. Hardcoded known paths + all drives
    _pd = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    _pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    _ad = os.environ.get("APPDATA", "")
    _pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    base_dirs = [_pf, _pf86]
    try:
        import string
        for letter in string.ascii_uppercase:
            for pf in ["Program Files", "Program Files (x86)"]:
                d = f"{letter}:\\{pf}"
                if os.path.isdir(d) and d not in base_dirs:
                    base_dirs.append(d)
    except Exception:
        pass
    module_paths.extend([
        os.path.join(_pd, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"),
        os.path.join(_ad, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"),
    ])
    for bd in base_dirs:
        module_paths.append(os.path.join(bd, "Blackmagic Design", "DaVinci Resolve", "Developer", "Scripting", "Modules"))
        module_paths.append(os.path.join(bd, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"))
        module_paths.append(os.path.join(bd, "Blackmagic Design", "DaVinci Resolve", "Scripting", "Modules"))
        lib_paths.append(os.path.join(bd, "Blackmagic Design", "DaVinci Resolve", "Libraries", "Fusion"))
        lib_paths.append(os.path.join(bd, "Blackmagic Design", "DaVinci Resolve", "Fusion"))
        lib_paths.append(os.path.join(bd, "Blackmagic Design", "DaVinci Resolve"))

    # 4. Filesystem scan: look for DaVinciResolveScript.py and fusionscript.dll
    #    Scan ALL drives (D:, E:, etc.) not just C:.
    #    EXPENSIVE (probes every drive letter + recursive os.walk) — only run it
    #    when the cheap sources above (registry / hardcoded / custom) did not
    #    already turn up an existing module path. This keeps the import/main
    #    thread from blocking for seconds on disconnected / sleeping network or
    #    external drives. When forced (re-detect) it always runs.
    cheap_found = any(os.path.isdir(p) for p in module_paths)
    if force_scan or not cheap_found:
        _scan_all_drives_windows(resolve_root, _pf, _pf86, _pd, module_paths, lib_paths)
        # Cache the discovered Resolve root so the next launch picks it up via
        # the cheap custom-path branch (step 0) and skips this scan entirely.
        _cache_discovered_resolve_root(module_paths)

    # 5. Env var override
    env_api = os.environ.get("RESOLVE_SCRIPT_API", "")
    if env_api:
        mod = os.path.join(env_api, "Modules")
        if os.path.isdir(mod) and mod not in module_paths:
            module_paths.insert(0, mod)
    env_lib = os.environ.get("RESOLVE_SCRIPT_LIB", "")
    if env_lib and os.path.isdir(os.path.dirname(env_lib)):
        d = os.path.dirname(env_lib)
        if d not in lib_paths:
            lib_paths.insert(0, d)

    # Deduplicate preserving order
    seen_m, seen_l = set(), set()
    module_paths = [p for p in module_paths if not (p in seen_m or seen_m.add(p))]
    lib_paths = [p for p in lib_paths if not (p in seen_l or seen_l.add(p))]

    return module_paths, lib_paths


def _discover_resolve_paths_mac():
    """Auto-discover DaVinci Resolve paths on macOS via known locations + mdfind."""
    module_paths = []
    lib_paths = []
    custom = load_custom_resolve_path()
    if custom and os.path.isdir(custom):
        _log.info(f"Using custom Resolve path: {custom}")
        module_paths.append(os.path.join(custom, "Developer", "Scripting", "Modules"))
        lib_paths.append(os.path.join(custom, "Libraries", "Fusion"))
        lib_paths.append(custom)
    module_paths.extend([
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
        os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
        "/opt/resolve/Developer/Scripting/Modules",
    ])
    lib_paths.extend([
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion",
        "/Applications/DaVinci Resolve Studio.app/Contents/Libraries/Fusion",  # Mac App Store (v1.5.10)
        os.path.expanduser("~/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion"),
        "/opt/resolve/libs/Fusion",
    ])
    # Try mdfind for non-standard installs
    try:
        out = _subprocess.check_output(
            ["mdfind", "kMDItemFSName == 'DaVinciResolveScript.py'"],
            text=True, timeout=5
        ).strip()
        for line in out.splitlines():
            d = os.path.dirname(line)
            if d and d not in module_paths:
                module_paths.insert(0, d)
                _log.info(f"mdfind found module: {d}")
    except Exception:
        pass
    for lib_name in ["libfusionscript.so", "fusionscript.so"]:
        try:
            out = _subprocess.check_output(
                ["mdfind", f"kMDItemFSName == '{lib_name}'"],
                text=True, timeout=5
            ).strip()
            for line in out.splitlines():
                d = os.path.dirname(line)
                if d and d not in lib_paths:
                    lib_paths.insert(0, d)
                    _log.info(f"mdfind found lib ({lib_name}): {d}")
        except Exception:
            pass
    return module_paths, lib_paths


if _IS_WINDOWS:
    _WIN_MODULE_PATHS, _WIN_LIB_PATHS = _discover_resolve_paths_windows()
    FUSION_MODULE_PATH = _find_first_existing(_WIN_MODULE_PATHS)
    FUSION_LIB_PATH = _find_first_existing(_WIN_LIB_PATHS)
else:
    _MAC_MODULE_PATHS, _MAC_LIB_PATHS = _discover_resolve_paths_mac()
    FUSION_MODULE_PATH = _find_first_existing(_MAC_MODULE_PATHS)
    FUSION_LIB_PATH = _find_first_existing(_MAC_LIB_PATHS)


def _is_resolve_running():
    try:
        if _IS_WINDOWS:
            out = _subprocess.check_output(["tasklist"], text=True, timeout=5, creationflags=0x08000000)
            out_lower = out.lower()
            return "resolve" in out_lower
        else:
            out = _subprocess.check_output(["pgrep", "-if", "[Rr]esolve"], text=True, timeout=5)
            return bool(out.strip())
    except Exception:
        return False


# ─── v1.5.10: ambiente Resolve leggibile SENZA connessione IPC ────────────────
# Caso John Kelly (giu 2026): import OK + scriptapp None = Resolve rifiuta
# l'handshake. Le cause (pref External scripting=None, edizione Free, doppio
# install) sono tutte diagnosticabili da file su disco — questi helper le
# espongono a diagnose() e alla telemetria di boot.

_MAS_STUDIO_LIB = "/Applications/DaVinci Resolve Studio.app/Contents/Libraries/Fusion/fusionscript.so"


def _resolve_running_binary():
    """Path del binario Resolve in esecuzione (macOS), '' se non rilevabile."""
    if not _IS_MAC:
        return ""
    try:
        out = _subprocess.check_output(["pgrep", "-ifl", "[Rr]esolve"], text=True, timeout=5)
        marker = ".app/Contents/MacOS/Resolve"
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            cmd = parts[1]
            idx = cmd.find(marker)
            if idx != -1:
                return cmd[: idx + len(marker)]
    except Exception:
        pass
    return ""


def _read_resolve_scripting_mode():
    """Legge System.Scripting.Mode dal config.dat di Resolve (plain text).

    Ritorna (raw, label): ('1', 'Local'), ('0', 'None (external scripting DISABLED)'),
    (None, '<motivo>') se non leggibile. La pref e' quella di
    Preferences → System → General → 'External scripting using'."""
    if not _IS_MAC:
        return None, "unknown (non-mac)"
    cfg = os.path.expanduser("~/Library/Preferences/Blackmagic Design/DaVinci Resolve/config.dat")
    try:
        with open(cfg, "r", errors="ignore") as f:
            content = f.read()
    except FileNotFoundError:
        return None, "config.dat not found"
    except Exception as e:
        return None, f"unreadable ({type(e).__name__})"
    m = _re.search(r"System\.Scripting\.Mode\s*=\s*\"?(\w+)\"?", content)
    if not m:
        return None, "not present in config.dat"
    raw = m.group(1).strip()
    labels = {"0": "None (external scripting DISABLED)", "1": "Local", "2": "Network"}
    return raw, labels.get(raw, raw)


def _read_resolve_edition_from_log():
    """Edizione+versione DR dall'ultima riga 'Running DaVinci Resolve …' del log
    di Resolve (es. 'DaVinci Resolve Studio v20.3.2.0009'). '' se non leggibile.
    La free logga senza 'Studio' — unico modo per distinguerle su macOS (i bundle
    dmg free e Studio sono identici: stesso path, nome e bundle-id)."""
    if not _IS_MAC:
        return ""
    log_p = os.path.expanduser(
        "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/logs/davinci_resolve.log")
    try:
        last = ""
        with open(log_p, "r", errors="ignore") as f:
            # Log potenzialmente grande (cresce finche' Resolve gira): leggi solo
            # gli ultimi 4MB — la riga 'Running…' appare a ogni avvio di Resolve.
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4 * 1024 * 1024))
            for line in f:
                if "Running DaVinci Resolve" in line:
                    last = line.strip()
        if last:
            m = _re.search(r"Running (DaVinci Resolve[^,\n]*)", last)
            return (m.group(1).strip() if m else last)[:120]
    except Exception:
        pass
    return ""


def _installed_resolve_bundles():
    """Bundle DaVinci installati in /Applications (rileva doppi install dmg+MAS)."""
    if not _IS_MAC:
        return []
    candidates = [
        "/Applications/DaVinci Resolve/DaVinci Resolve.app",
        "/Applications/DaVinci Resolve Studio.app",
        "/Applications/DaVinci Resolve.app",
    ]
    return [p for p in candidates if os.path.isdir(p)]


def run_health_check():
    """Startup health check — logs status of critical dependencies.

    Returns dict with status of each check:
        ffmpeg_ok: bool
        ffmpeg_path: str
        resolve_script_ok: bool
        resolve_script_path: str
    Called at boot to log state; NOT a dialog.
    """
    result = {
        "ffmpeg_ok": False,
        "ffmpeg_path": "",
        "resolve_script_ok": False,
        "resolve_script_path": "",
    }

    # Check ffmpeg
    try:
        from app.core.beat_detector import get_ffmpeg_path
        ffmpeg_path = get_ffmpeg_path()
        result["ffmpeg_path"] = ffmpeg_path
        result["ffmpeg_ok"] = os.path.exists(ffmpeg_path)
        _log.info(f"Health check — ffmpeg: {'OK' if result['ffmpeg_ok'] else 'NOT FOUND'} at {ffmpeg_path}")
    except Exception as e:
        _log.error(f"Health check — ffmpeg error: {e}")

    # Check DaVinciResolveScript.py
    search_paths = _MAC_MODULE_PATHS if _IS_MAC else (_WIN_MODULE_PATHS if _IS_WINDOWS else [])
    for mp in search_paths:
        dvr_path = os.path.join(mp, "DaVinciResolveScript.py")
        if os.path.exists(dvr_path):
            result["resolve_script_ok"] = True
            result["resolve_script_path"] = dvr_path
            break

    _log.info(f"Health check — DaVinciResolveScript: {'OK' if result['resolve_script_ok'] else 'NOT FOUND'}"
              f" at {result['resolve_script_path'] or '(none)'}")

    # v1.5.10 — contesto Resolve senza IPC: edizione (Studio/free), pref external
    # scripting e doppi install. Vanno in telemetria di boot: mai piu' casi
    # support ciechi sull'edizione (caso John Kelly).
    try:
        result["resolve_running"] = _is_resolve_running()
        result["resolve_edition"] = _read_resolve_edition_from_log()
        _mode_raw, _mode_label = _read_resolve_scripting_mode()
        result["resolve_scripting_mode"] = _mode_raw if _mode_raw is not None else _mode_label
        result["resolve_installs"] = len(_installed_resolve_bundles())
        _log.info(f"Health check — DR edition: {result['resolve_edition'] or '(unknown)'} | "
                  f"scripting mode: {result['resolve_scripting_mode']} | installs: {result['resolve_installs']}")
    except Exception as e:
        _log.warning(f"Health check — resolve env probe failed: {e}")

    return result


def diagnose():
    """Returns a diagnostic string describing what was found/not found for Resolve scripting."""
    lines = [f"OS: {_platform.system()} {_platform.release()}"]
    lines.append(f"Resolve running: {_is_resolve_running()}")
    if _IS_WINDOWS:
        lines.append("Module paths searched:")
        for p in _WIN_MODULE_PATHS:
            exists = os.path.isdir(p)
            dvr = os.path.exists(os.path.join(p, "DaVinciResolveScript.py"))
            lines.append(f"  {'[OK]' if exists else '[--]'} {p} {'(DaVinciResolveScript.py found)' if dvr else ''}")
        lines.append("Library paths searched:")
        for p in _WIN_LIB_PATHS:
            exists = os.path.isdir(p)
            dll = os.path.exists(os.path.join(p, "fusionscript.dll"))
            lines.append(f"  {'[OK]' if exists else '[--]'} {p} {'(fusionscript.dll found)' if dll else ''}")
        lines.append(f"RESOLVE_SCRIPT_API = {os.environ.get('RESOLVE_SCRIPT_API', '(not set)')}")
        lines.append(f"RESOLVE_SCRIPT_LIB = {os.environ.get('RESOLVE_SCRIPT_LIB', '(not set)')}")
    else:
        lines.append("Module paths searched:")
        for p in _MAC_MODULE_PATHS:
            exists = os.path.isdir(p)
            dvr = os.path.exists(os.path.join(p, "DaVinciResolveScript.py"))
            lines.append(f"  {'[OK]' if exists else '[--]'} {p} {'(DaVinciResolveScript.py found)' if dvr else ''}")
        lines.append("Library paths searched:")
        for p in _MAC_LIB_PATHS:
            exists = os.path.isdir(p)
            so_ok = os.path.exists(os.path.join(p, "fusionscript.so")) or os.path.exists(os.path.join(p, "libfusionscript.so"))
            lines.append(f"  {'[OK]' if exists else '[--]'} {p} {'(fusionscript.so found)' if so_ok else ''}")
    try:
        from app.__version__ import __version__ as _app_ver
    except Exception:
        _app_ver = "unknown"
    lines.append(f"\nApp version: {_app_ver}")
    lines.append(f"Python: {_platform.python_version()} ({_platform.machine()})")
    lines.append(f"macOS: {_platform.mac_ver()[0] if hasattr(_platform, 'mac_ver') else 'N/A'}")
    lines.append(f"Frozen: {getattr(sys, 'frozen', False)}")
    lines.append(f"Executable: {sys.executable}")
    if hasattr(sys, '_MEIPASS'):
        lines.append(f"_MEIPASS: {sys._MEIPASS}")

    lines.append(f"\n--- Environment ---")
    lines.append(f"RESOLVE_SCRIPT_API: {os.environ.get('RESOLVE_SCRIPT_API', '(not set)')}")
    lines.append(f"RESOLVE_SCRIPT_LIB: {os.environ.get('RESOLVE_SCRIPT_LIB', '(not set)')}")
    lines.append(f"sys.path (resolve): {[p for p in sys.path if 'Resolve' in p or 'resolve' in p or 'Blackmagic' in p]}")

    lines.append(f"\n--- fusionscript check ---")
    fs_lib = os.environ.get('RESOLVE_SCRIPT_LIB', '')
    if fs_lib and os.path.exists(fs_lib):
        try:
            import subprocess as _sp
            _arch = _sp.check_output(["file", fs_lib], text=True, timeout=5).strip()
            lines.append(f"fusionscript: {_arch}")
        except Exception:
            lines.append(f"fusionscript: exists at {fs_lib}")
    else:
        for _fsp in ["/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
                     "/opt/resolve/libs/Fusion/fusionscript.so"]:
            if os.path.exists(_fsp):
                try:
                    import subprocess as _sp
                    _arch = _sp.check_output(["file", _fsp], text=True, timeout=5).strip()
                    lines.append(f"fusionscript: {_arch}")
                except Exception:
                    lines.append(f"fusionscript: found at {_fsp}")
                break
        else:
            lines.append("fusionscript: NOT FOUND")

    lines.append(f"\n--- Entitlements self-check ---")
    try:
        import subprocess as _sp
        _ent = _sp.check_output(["codesign", "-d", "--entitlements", "-", sys.executable], stderr=_sp.STDOUT, text=True, timeout=5)
        if "disable-library-validation" in _ent:
            lines.append("disable-library-validation: YES")
        else:
            lines.append("disable-library-validation: NO (may cause fusionscript load failure)")
        if "allow-unsigned-executable-memory" in _ent:
            lines.append("allow-unsigned-executable-memory: YES")
    except Exception as _e:
        lines.append(f"entitlements check: {_e}")

    lines.append(f"\n--- Import test ---")
    try:
        import DaVinciResolveScript as _dvr_test
        lines.append("DaVinciResolveScript: IMPORTED OK")
        try:
            _r = _dvr_test.scriptapp("Resolve")
            if _r:
                lines.append(f"scriptapp('Resolve'): CONNECTED")
                try:
                    lines.append(f"Resolve version: {_r.GetVersionString()}")
                except Exception:
                    pass
            else:
                # NB: main_window._show_diagnostics matcha ESATTAMENTE la
                # stringa "scriptapp('Resolve'): None" per il tip dedicato —
                # se cambi la quotatura qui, aggiorna anche il match li'.
                lines.append(f"scriptapp('Resolve'): None")
                # v1.5.10 — import OK + scriptapp None = Resolve RIFIUTA l'IPC
                # (non e' "Resolve non trovato" e NON dipende da progetto aperto).
                lines.append("  → Resolve REFUSED the scripting connection (library loaded fine).")
                _so_file = getattr(_dvr_test, "__file__", "") or "(unknown)"
                lines.append(f"  fusionscript loaded from: {_so_file}")
                _bin = _resolve_running_binary()
                if _bin:
                    lines.append(f"  Resolve binary running:   {_bin}")
                    def _bundle_root(p):
                        i = p.find(".app/")
                        return p[: i + 4] if i != -1 else ""
                    if (_bundle_root(_so_file) and _bundle_root(_bin)
                            and _bundle_root(_so_file) != _bundle_root(_bin)):
                        lines.append("  [!] MISMATCH: loaded library belongs to a DIFFERENT install "
                                     "than the running app — remove the duplicate install.")
                _mode_label = _read_resolve_scripting_mode()[1]
                lines.append(f"  External scripting pref:  {_mode_label}")
                _edition = _read_resolve_edition_from_log()
                if _edition:
                    lines.append(f"  Resolve edition (DR log): {_edition}")
                    if "Studio" not in _edition:
                        lines.append("  [!] FREE edition detected — external scripting requires "
                                     "DaVinci Resolve STUDIO.")
                _bundles = _installed_resolve_bundles()
                if len(_bundles) > 1:
                    lines.append(f"  [!] Multiple Resolve installs: {', '.join(_bundles)}")
                lines.append("  FIX: DaVinci Resolve → Preferences → System → General →")
                lines.append("       'External scripting using' = Local → Save → RESTART Resolve.")
                lines.append("       (Requires the STUDIO edition — check menu DaVinci Resolve → About.)")
        except Exception as _e:
            lines.append(f"scriptapp error: {type(_e).__name__}: {_e}")
    except ImportError as _e:
        lines.append(f"DaVinciResolveScript: IMPORT FAILED")
        lines.append(f"  error: {_e}")
        lines.append(f"  This usually means fusionscript.so cannot be loaded.")
        lines.append(f"  Check: DaVinci Resolve Studio (not Free) is required.")
    except Exception as _e:
        lines.append(f"DaVinciResolveScript: ERROR — {type(_e).__name__}: {_e}")

    lines.append(f"\n--- ffmpeg ---")
    try:
        from app.core.beat_detector import get_ffmpeg_path
        _ffp = get_ffmpeg_path()
        lines.append(f"path: {_ffp}")
        lines.append(f"exists: {os.path.exists(_ffp)}")
        if os.path.exists(_ffp):
            try:
                import subprocess as _sp
                _ver = _sp.check_output([_ffp, "-version"], text=True, timeout=5).split('\n')[0]
                lines.append(f"version: {_ver}")
            except Exception as _e:
                lines.append(f"exec test: FAILED — {_e}")
        else:
            lines.append("ffmpeg NOT FOUND in bundle — contact support")
    except Exception as _e:
        lines.append(f"ffmpeg error: {_e}")

    log_path = os.path.expanduser("~/Library/Logs/PulseEdit/pulseedit.log") if not _IS_WINDOWS else os.path.join(os.environ.get("TEMP", ""), "pulseedit_debug.log")
    lines.append(f"\nLog file: {log_path}")
    lines.append("Send a screenshot of this dialog to support for troubleshooting.")
    return "\n".join(lines)


def _register_python_in_registry():
    """Register the bundled python_shim Python in HKCU so fusionscript.dll finds OUR
    Python — NOT a user-installed conflicting Python (Anaconda, Python.org, etc).

    Why this matters: fusionscript.dll on Windows reads HKCU\\Software\\Python\\PythonCore\\<ver>\\InstallPath
    to discover where Python lives, then loads python3.dll from there. If the customer has a
    conflicting Python install registered, fusionscript loads THAT one and silently fails
    init with 'initialization of fusionscript failed without raising an exception'.

    Fix: ALWAYS overwrite HKCU pointing at our python_shim/, for multiple Python versions
    (3.10/3.11/3.12/3.13) since Resolve major versions vary which one they probe.
    """
    app_dir = os.path.dirname(sys.executable)
    shim_dir = os.path.join(app_dir, "python_shim")
    internal_dir = os.path.join(app_dir, "_internal")

    # Prefer python_shim (full embeddable) over _internal (PyInstaller — may lack python3.dll)
    target_dir = shim_dir if os.path.isdir(shim_dir) else internal_dir
    if not os.path.isdir(target_dir):
        _log.warning("Neither python_shim nor _internal found — cannot register Python")
        return

    python_exe = os.path.join(target_dir, "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    try:
        import winreg
        # Register multiple versions — fusionscript.dll across Resolve releases probes different keys.
        # We OVERWRITE existing values: a customer's pre-installed Python is the most common cause
        # of "Resolve not detected" failures.
        for ver in ("3.10", "3.11", "3.12", "3.13"):
            key_path = fr"Software\Python\PythonCore\{ver}\InstallPath"
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, target_dir + os.sep)
                    winreg.SetValueEx(key, "ExecutablePath", 0, winreg.REG_SZ, python_exe)
                    winreg.SetValueEx(key, "WindowedExecutablePath", 0, winreg.REG_SZ, python_exe)
            except OSError as e:
                _log.warning(f"Could not register {ver}: {e}")
        _log.info(f"Registered HKCU Python 3.10–3.13 -> {target_dir}")

        # Set PYTHONHOME so the embeddable distribution boots correctly when fusionscript.dll
        # initializes its embedded Python interpreter.
        os.environ["PYTHONHOME"] = target_dir

        # Mirror python3.dll into _internal as belt-and-suspenders (some load orders look there)
        if internal_dir != target_dir and os.path.isdir(internal_dir):
            p3_dst = os.path.join(internal_dir, "python3.dll")
            p3_src = os.path.join(shim_dir, "python3.dll")
            if not os.path.exists(p3_dst) and os.path.exists(p3_src):
                try:
                    import shutil
                    shutil.copy2(p3_src, p3_dst)
                    _log.info("Copied python3.dll into _internal")
                except OSError as e:
                    _log.warning(f"Could not copy python3.dll: {e}")
    except Exception as e:
        _log.warning(f"Could not register Python in registry: {e}")


def _ensure_python3_on_path():
    """Make python311.dll and python3.exe findable for fusionscript.dll on Windows.
    Checks python_shim/ (embeddable bundle) and _internal/ (PyInstaller)."""
    app_dir = os.path.dirname(sys.executable)
    for subdir in ["python_shim", "_internal"]:
        d = os.path.join(app_dir, subdir)
        if os.path.isdir(d):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass
            _log.info(f"Added {subdir} to DLL search path: {d}")
    _register_python_in_registry()



class _SubprocessProxy:
    """Proxy that delegates Resolve API calls to a subprocess worker.
    Used on Windows when fusionscript.dll can't initialize inside PyInstaller.
    Mimics the Resolve API so main_window.py works unchanged."""

    def __init__(self, process):
        self._proc = process
        self._is_proxy = True
        self._info = {}

    def _send(self, cmd, **args):
        import json
        msg = json.dumps({"cmd": cmd, "args": args}) + "\n"
        try:
            self._proc.stdin.write(msg)
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            if not line:
                _log.error("Worker process died")
                return {"ok": False, "error": "worker died"}
            return json.loads(line)
        except Exception as e:
            _log.error(f"Worker communication error: {e}")
            return {"ok": False, "error": str(e)}

    def alive(self):
        return self._proc.poll() is None

    def kill(self):
        try:
            self._proc.terminate()
        except Exception:
            pass

    def _refresh(self):
        self._info = self._send("refresh")
        return self._info

    def GetProjectManager(self):
        return self

    def GetCurrentProject(self):
        self._refresh()
        if self._info.get("ok") and self._info.get("project"):
            return self
        return None

    def GetCurrentTimeline(self):
        if self._info.get("timeline"):
            return self
        return None

    def GetName(self):
        return self._info.get("project", "") or self._info.get("timeline", "")

    def GetSetting(self, key):
        if key == "timelineFrameRate":
            return self._info.get("fps", "24")
        return ""

    def GetMediaPool(self):
        return self

    def GetTrackCount(self, track_type):
        return 0

    def GetStartFrame(self):
        resp = self._send("get_timeline_start_frame")
        return resp.get("frame", 0)

    def AddMarker(self, frame, color, name, note, duration):
        resp = self._send("add_marker", frame=frame, color=color, name=name, note=note)
        return resp.get("ok", False)

    def DeleteMarkerAtFrame(self, frame):
        return True

    def GetMarkers(self):
        return {}

    def GetItemListInTrack(self, track_type, track_idx):
        return []

    def DeleteClips(self, items):
        pass

    def GetTrackName(self, track_type, track_idx):
        return ""

    def AppendToTimeline(self, items):
        return []

    def GetEnd(self):
        return 0

    def GetStart(self):
        return 0

    def GetCurrentVideoItem(self):
        return None


_worker_proxy = None


def _proxy_send(cmd, **args):
    """Safe wrapper around _worker_proxy._send.
    If the subprocess worker isn't running (Resolve closed, init failed,
    or worker died), returns a sentinel error dict instead of crashing.
    Callers already use resp.get("...") with defaults, so they degrade
    gracefully (e.g. get_audio_tracks returns {})."""
    if _worker_proxy is None:
        return {"ok": False, "error": "worker_not_initialized"}
    return _worker_proxy._send(cmd, **args)


def _start_subprocess_worker():
    """Launch resolve_worker.py in python_shim/python.exe and return a proxy."""
    import json
    app_dir = os.path.dirname(sys.executable)
    shim_python = os.path.join(app_dir, "python_shim", "python.exe")
    if not os.path.exists(shim_python):
        _log.error(f"python_shim not found: {shim_python}")
        return None

    worker_script = os.path.join(app_dir, "resolve_worker.py")
    if not os.path.exists(worker_script):
        worker_script = os.path.join(app_dir, "_internal", "app", "core", "resolve_worker.py")
    if not os.path.exists(worker_script):
        worker_script = os.path.join(os.path.dirname(__file__), "resolve_worker.py")
    if not os.path.exists(worker_script):
        _log.error(f"resolve_worker.py not found")
        return None

    _log.info(f"Starting subprocess worker: {shim_python} {worker_script}")
    try:
        proc = _subprocess.Popen(
            [shim_python, worker_script],
            stdin=_subprocess.PIPE,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            text=True,
            creationflags=0x08000000,
        )
        ready_line = proc.stdout.readline()
        if not ready_line:
            _log.error("Worker failed to start")
            proc.terminate()
            return None
        ready = json.loads(ready_line)
        if ready.get("ready"):
            _log.info("Subprocess worker ready")
            return _SubprocessProxy(proc)
        _log.error(f"Worker not ready: {ready}")
        proc.terminate()
        return None
    except Exception as e:
        _log.error(f"Failed to start worker: {e}")
        return None


# --- macOS Tahoe (26+) Full Disk Access workaround ---------------------------
# Standard copy of Blackmagic's DaVinciResolveScript.py wrapper. It only loads
# fusionscript.so (via RESOLVE_SCRIPT_LIB or the default /Applications path) —
# it does NOT read anything else under /Library. We stage our own copy in a
# user-writable folder so PE can import it WITHOUT touching
# /Library/Application Support/Blackmagic, which macOS Tahoe (26+) blocks via TCC
# unless the app has Full Disk Access. fusionscript.so lives in /Applications,
# which is readable without FDA.
_RESOLVE_SHIM_SRC = '''import sys
import os

def load_dynamic(module_name, file_path):
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.ExtensionFileLoader(module_name, file_path)
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

script_module = None
try:
    import fusionscript as script_module
except ImportError:
    lib_path = os.getenv("RESOLVE_SCRIPT_LIB")
    if lib_path and os.path.exists(lib_path):
        try:
            script_module = load_dynamic("fusionscript", lib_path)
        except ImportError:
            pass
    if not script_module:
        # /Applications first (readable without Full Disk Access on Tahoe),
        # then the legacy /Library location as a last resort.
        candidates = [
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
            "/Applications/DaVinci Resolve Studio.app/Contents/Libraries/Fusion/fusionscript.so",
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/fusionscript.so",
        ]
        for cand in candidates:
            if os.path.exists(cand):
                try:
                    script_module = load_dynamic("fusionscript", cand)
                    break
                except ImportError:
                    continue

if script_module:
    sys.modules[__name__] = script_module
else:
    raise ImportError("Could not locate fusionscript module dependency")
'''


def _ensure_resolve_shim():
    """Scrive la copia bundlata del modulo DaVinciResolveScript in una cartella
    scrivibile dell'utente e ne ritorna il path (o None se fallisce).

    Serve a importare lo scripting di Resolve SENZA leggere
    /Library/Application Support/Blackmagic, cartella che macOS Tahoe (26+)
    blocca via TCC quando manca il Full Disk Access (caso "DaVinci Resolve not
    found" con Studio installato)."""
    try:
        base = os.path.expanduser("~/Library/Application Support/PulseEdit/resolve_shim")
        os.makedirs(base, exist_ok=True)
        target = os.path.join(base, "DaVinciResolveScript.py")
        try:
            current = open(target).read()
        except OSError:
            current = None
        if current != _RESOLVE_SHIM_SRC:
            with open(target, "w") as f:
                f.write(_RESOLVE_SHIM_SRC)
        return base
    except Exception as e:
        _log.warning(f"Could not stage bundled Resolve shim: {e}")
        return None


# v1.5.10 — motivo dell'ultimo fallimento di connect(), per messaggi UI distinti:
#   'not_running'   Resolve non in esecuzione
#   'import_failed' modulo scripting non importabile (caso Tahoe TCC / install rotta)
#   'ipc_refused'   import OK ma Resolve rifiuta l'handshake (pref scripting=None,
#                   edizione free, doppio install) — caso John Kelly
LAST_ERROR = None

# RESOLVE_SCRIPT_LIB: ricordiamo se l'abbiamo settata NOI, cosi' i Refresh
# successivi possono rivalutarla (prima era sticky: una scelta sbagliata al
# primo giro — es. .so dell'install sbagliato con mdfind — restava per sempre).
_lib_set_by_us = False


def connect(retries=3, delay=1.5):
    """Connette a DaVinci Resolve con retry. Ritorna l'oggetto resolve o None.

    In caso di fallimento setta il modulo-level LAST_ERROR (vedi sopra)."""
    global _worker_proxy, LAST_ERROR, _lib_set_by_us
    LAST_ERROR = None

    resolve_running = _is_resolve_running()
    if not resolve_running:
        _log.warning("Resolve process not detected — trying to connect anyway")

    # Se RESOLVE_SCRIPT_LIB l'abbiamo scelta noi in un connect() precedente,
    # azzerala e rivaluta da capo (un Refresh deve poter correggere la scelta).
    if _lib_set_by_us and os.environ.get("RESOLVE_SCRIPT_LIB"):
        os.environ.pop("RESOLVE_SCRIPT_LIB", None)
        _lib_set_by_us = False

    # Add all known module paths to sys.path
    if _IS_WINDOWS:
        all_module_paths = _WIN_MODULE_PATHS
    else:
        all_module_paths = _MAC_MODULE_PATHS

    for mp in all_module_paths:
        if os.path.isdir(mp) and mp not in sys.path:
            sys.path.insert(0, mp)
            _log.info(f"Added module path: {mp}")

    if FUSION_MODULE_PATH not in sys.path:
        sys.path.insert(0, FUSION_MODULE_PATH)
    _log.info(f"Primary module path: {FUSION_MODULE_PATH} (exists: {os.path.isdir(FUSION_MODULE_PATH)})")

    if _IS_WINDOWS:
        for lp in _WIN_LIB_PATHS:
            if os.path.isdir(lp):
                current_path = os.environ.get("PATH", "")
                if lp not in current_path:
                    os.environ["PATH"] = lp + os.pathsep + current_path
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(lp)
        _ensure_python3_on_path()
        if not os.environ.get("RESOLVE_SCRIPT_API", ""):
            for mp in _WIN_MODULE_PATHS:
                script_api = os.path.dirname(mp)
                if os.path.isdir(script_api):
                    os.environ["RESOLVE_SCRIPT_API"] = script_api
                    break
        if not os.environ.get("RESOLVE_SCRIPT_LIB", ""):
            for lp in _WIN_LIB_PATHS:
                dll = os.path.join(lp, "fusionscript.dll")
                if os.path.exists(dll):
                    os.environ["RESOLVE_SCRIPT_LIB"] = dll
                    break
    else:
        os.environ.setdefault("DYLD_LIBRARY_PATH", FUSION_LIB_PATH)
        if _IS_MAC:
            for mp in _MAC_MODULE_PATHS:
                script_api = os.path.dirname(mp)
                if os.path.isdir(script_api):
                    os.environ.setdefault("RESOLVE_SCRIPT_API", script_api)
                    break
            if not os.environ.get("RESOLVE_SCRIPT_LIB", ""):
                for lp in _MAC_LIB_PATHS:
                    for lib_name in ["libfusionscript.so", "fusionscript.so"]:
                        lib = os.path.join(lp, lib_name)
                        if os.path.exists(lib):
                            os.environ["RESOLVE_SCRIPT_LIB"] = lib
                            _lib_set_by_us = True
                            _log.info(f"Found script lib: {lib}")
                            break

    _log.info(f"ENV RESOLVE_SCRIPT_API = {os.environ.get('RESOLVE_SCRIPT_API', '(not set)')}")
    _log.info(f"ENV RESOLVE_SCRIPT_LIB = {os.environ.get('RESOLVE_SCRIPT_LIB', '(not set)')}")

    # macOS Tahoe (26+) safe import: stage our bundled DaVinciResolveScript copy
    # in a user-writable folder and put it FIRST on sys.path, so the import below
    # never needs to read /Library/Application Support/Blackmagic (TCC-blocked
    # without Full Disk Access). It loads fusionscript.so from /Applications.
    # Additive: if staging fails we just fall through to the standard paths.
    if _IS_MAC:
        if not os.environ.get("RESOLVE_SCRIPT_LIB", ""):
            # v1.5.10: considera anche il bundle Mac App Store (DaVinci Resolve
            # Studio.app) — prima era invisibile e con doppio install lo shim
            # caricava il .so dell'install sbagliato.
            for _std_lib in [
                "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
                _MAS_STUDIO_LIB,
            ]:
                if os.path.exists(_std_lib):
                    os.environ["RESOLVE_SCRIPT_LIB"] = _std_lib
                    _lib_set_by_us = True
                    break
        _shim_dir = _ensure_resolve_shim()
        if _shim_dir and _shim_dir not in sys.path:
            sys.path.insert(0, _shim_dir)
            _log.info(f"Resolve shim staged (Tahoe-safe import): {_shim_dir}")

    # Try direct import first (works on macOS and Windows with system Python)
    direct_failed = False
    imported_ok = False
    for attempt in range(retries):
        try:
            import DaVinciResolveScript as dvr
            imported_ok = True
            _log.info(f"DaVinciResolveScript imported OK (attempt {attempt + 1})")
            resolve = dvr.scriptapp("Resolve")
            if resolve:
                _log.info(f"Connected to Resolve directly (attempt {attempt + 1})")
                return resolve
            _log.warning(f"scriptapp returned None (attempt {attempt + 1}/{retries})")
        except ImportError as e:
            _log.error(f"Cannot import DaVinciResolveScript: {e}")
            if not _IS_WINDOWS:
                LAST_ERROR = 'import_failed'
                return None
            direct_failed = True
            break
        except SystemError as e:
            _log.warning(f"Direct import failed (PyInstaller conflict): {e}")
            direct_failed = True
            break
        except Exception as e:
            _log.warning(f"Connect attempt {attempt + 1}/{retries} failed: {type(e).__name__}: {e}")
            direct_failed = True
            break
        if attempt < retries - 1:
            _time.sleep(delay)

    # Fallback: subprocess worker (Windows only, PyInstaller frozen apps)
    if _IS_WINDOWS and direct_failed and getattr(sys, 'frozen', False):
        _log.info("Falling back to subprocess worker for Resolve connection")
        if _worker_proxy and _worker_proxy.alive():
            _worker_proxy.kill()
        _worker_proxy = _start_subprocess_worker()
        if _worker_proxy:
            resp = _proxy_send("connect")
            if resp.get("ok"):
                _log.info(f"Connected to Resolve via subprocess worker")
                return _worker_proxy
            _log.error(f"Subprocess worker connect failed: {resp.get('error')}")
        # Classifica: worker partito ma connect rifiutato = IPC; worker mai
        # partito = problema d'ambiente, non di Resolve.
        if not resolve_running:
            LAST_ERROR = 'not_running'
        elif _worker_proxy:
            LAST_ERROR = 'ipc_refused'
        else:
            LAST_ERROR = 'import_failed'
        return None

    # v1.5.10: classifica il fallimento per la UI (vedi LAST_ERROR in testa).
    if imported_ok and resolve_running:
        LAST_ERROR = 'ipc_refused'
        _log.error("All connection attempts failed — Resolve is RUNNING and the module "
                   "imported, but scriptapp refused (external scripting off / free edition "
                   "/ duplicate install). See Diagnostics.")
    elif not resolve_running:
        LAST_ERROR = 'not_running'
        _log.error("All connection attempts failed — Resolve process not detected")
    else:
        LAST_ERROR = 'import_failed'
        _log.error("All connection attempts failed")
    return None


# ─── Timeline offset ───

def get_timeline_start_frame(timeline):
    """Ritorna il frame di inizio della timeline (es. 86400 per 01:00:00:00 a 24fps).
    Tutti i marker e clip posizionati sono offset da questo valore."""
    try:
        return int(timeline.GetStartFrame())
    except Exception:
        return 0


# ─── Audio (identico a Beat Markers) ───

def _is_proxy(obj):
    # Cannot use hasattr here — Resolve's PyRemoteObject has a magic __getattr__
    # that responds True to any attribute name, so hasattr(obj, '_is_proxy')
    # is True even for real Resolve API objects. Use isinstance against the
    # actual proxy class instead.
    return isinstance(obj, _SubprocessProxy)


def get_audio_tracks(timeline):
    """Ritorna dict {label: track_index} delle tracce audio con clip."""
    if _is_proxy(timeline):
        resp = _proxy_send("get_audio_tracks")
        return resp.get("tracks", {}) if resp.get("ok") else {}
    tracks = {}
    total = timeline.GetTrackCount("audio")
    _log.info(f"get_audio_tracks: timeline reports {total} audio tracks")
    for t_idx in range(1, total + 1):
        items = timeline.GetItemListInTrack("audio", t_idx)
        n_items = len(items) if items else 0
        track_name = timeline.GetTrackName("audio", t_idx) if hasattr(timeline, "GetTrackName") else ""
        _log.info(f"get_audio_tracks: A{t_idx} '{track_name}' -> {n_items} items")
        if items and len(items) > 0:
            name = ""
            for item in items:
                mp = item.GetMediaPoolItem()
                if mp:
                    name = mp.GetClipProperty("Clip Name") or ""
                    break
            label = f"Track {t_idx}: {name} ({len(items)} clip)"
            tracks[label] = t_idx
    if not tracks:
        _log.warning(f"get_audio_tracks: returned empty (timeline had {total} audio tracks but none with clips)")
    return tracks


def find_audio_file(timeline, track_idx):
    """Trova il percorso del file audio del primo clip nella traccia."""
    if _is_proxy(timeline):
        resp = _proxy_send("find_audio_file", track_idx=track_idx)
        path = resp.get("path") if resp.get("ok") else None
        return path, [] if path else None
    items = timeline.GetItemListInTrack("audio", track_idx)
    if not items:
        return None, None

    for item in items:
        mp = item.GetMediaPoolItem()
        if not mp:
            continue
        fp = mp.GetClipProperty("File Path")

        if fp and os.path.exists(fp):
            return fp, items

    return None, items


# ─── Video tracks ───

def get_video_tracks(timeline):
    """Ritorna dict {label: track_index} delle tracce video."""
    if _is_proxy(timeline):
        resp = _proxy_send("get_video_tracks")
        return resp.get("tracks", {}) if resp.get("ok") else {}
    tracks = {}
    count = timeline.GetTrackCount("video")
    for t_idx in range(1, count + 1):
        name = timeline.GetTrackName("video", t_idx)
        items = timeline.GetItemListInTrack("video", t_idx)
        n_items = len(items) if items else 0
        if name:
            label = f"V{t_idx}: {name} ({n_items} clip)"
        else:
            label = f"V{t_idx} ({n_items} clip)"
        tracks[label] = t_idx
    return tracks


def clear_video_track(timeline, track_index):
    """Rimuovi tutti i clip da una traccia video. Ritorna quanti rimossi."""
    if _is_proxy(timeline):
        resp = _proxy_send("clear_video_track", track_idx=track_index)
        return resp.get("removed", 0) if resp.get("ok") else 0
    items = timeline.GetItemListInTrack("video", track_index)
    if items and len(items) > 0:
        timeline.DeleteClips(items)
        return len(items)
    return 0


# ─── Beat markers on timeline ───

def place_bar_markers(timeline, bar_times, fps, color="Yellow"):
    """Piazza marker oro sulla timeline per ogni inizio battuta (downbeat)."""
    if _is_proxy(timeline):
        added = 0
        for i, bt in enumerate(bar_times):
            frame = round(bt * fps)
            _proxy_send("add_marker", frame=frame, color=color,
                                name="Bar", note=f"Bar {i + 1}")
            added += 1
        return added
    added = 0
    for i, bt in enumerate(bar_times):
        frame = round(bt * fps)
        note = f"Bar {i + 1}"
        if timeline.AddMarker(frame, color, "Bar", note, 1):
            added += 1
    return added


def place_upbeat_markers(timeline, upbeat_times, fps, color="Red"):
    """Piazza marker per gli upbeat (levare) sulla timeline.

    Ritorna il numero di marker piazzati.
    """
    added = 0
    for i, ut in enumerate(upbeat_times):
        frame = round(ut * fps)
        note = f"Upbeat {i + 1}"
        if timeline.AddMarker(frame, color, "Upbeat", note, 1):
            added += 1
    return added


def clear_timeline_markers(timeline):
    """Rimuovi tutti i marker dalla timeline. Ritorna quanti rimossi."""
    if _is_proxy(timeline):
        resp = _proxy_send("clear_timeline_markers")
        return resp.get("removed", 0) if resp.get("ok") else 0
    markers = timeline.GetMarkers()
    if not markers:
        return 0
    removed = 0
    for frame_id in list(markers.keys()):
        if timeline.DeleteMarkerAtFrame(frame_id):
            removed += 1
    return removed


# ─── Media Pool folders & clips ───

def get_media_pool_folders(resolve):
    """Ritorna dict {display_name: Folder} delle cartelle nel Media Pool."""
    if _is_proxy(resolve):
        resp = _proxy_send("get_media_pool_folders")
        if resp.get("ok"):
            return {name: name for name in resp.get("folders", [])}
        return {}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {}
    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()

    result = {"Root": root}
    _collect_folders(root, "", result)
    return result


def _collect_folders(folder, prefix, result):
    """Raccoglie ricorsivamente le sottocartelle."""
    subs = folder.GetSubFolderList()
    if not subs:
        return
    for sub in subs:
        name = sub.GetName()
        path = f"{prefix}/{name}" if prefix else name
        result[path] = sub
        _collect_folders(sub, path, result)


def get_clips_from_folder(folder, timeline_fps=None):
    """Ritorna lista di MediaPoolItem video da una cartella.

    DaVinci Resolve conforma automaticamente tutti i clip al FPS della timeline,
    quindi non filtriamo per FPS — clip con qualsiasi frame rate funzionano.
    In proxy mode, ritorna dicts con 'id' per riferimento al worker.
    """
    if isinstance(folder, str) and _worker_proxy and _worker_proxy.alive():
        resp = _proxy_send("get_clips_from_folder", folder=folder, fps=timeline_fps)
        return resp.get("clips", []) if resp.get("ok") else []
    clips = folder.GetClipList()
    if not clips:
        return []

    video_clips = []
    for clip in clips:
        file_path = clip.GetClipProperty("File Path") or ""
        if not file_path or not os.path.exists(file_path):
            continue
        frames_str = clip.GetClipProperty("Frames")
        if not frames_str:
            continue
        try:
            frames = int(frames_str)
        except (ValueError, TypeError):
            continue
        if frames <= 0:
            continue
        ext = os.path.splitext(file_path)[1].lower()
        audio_only_exts = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}
        if ext in audio_only_exts:
            continue
        video_clips.append(clip)
    return video_clips


def scan_clips_in_folder(folder, timeline_fps):
    """Scansiona clip in una cartella e conta i clip video disponibili."""
    if isinstance(folder, str) and _worker_proxy and _worker_proxy.alive():
        resp = _proxy_send("scan_clips_in_folder", folder=folder)
        if resp.get("ok"):
            return {"total": resp.get("total", 0), "matched": resp.get("matched", 0), "warnings": []}
        return {"total": 0, "matched": 0, "warnings": []}
    clips = folder.GetClipList()
    if not clips:
        return {"total": 0, "matched": 0, "warnings": []}

    total = 0
    audio_only_exts = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}

    for clip in clips:
        file_path = clip.GetClipProperty("File Path") or ""
        if not file_path or not os.path.exists(file_path):
            continue
        frames_str = clip.GetClipProperty("Frames")
        if not frames_str:
            continue
        try:
            frames = int(frames_str)
        except (ValueError, TypeError):
            continue
        if frames <= 0:
            continue
        ext = os.path.splitext(file_path)[1].lower()
        if ext in audio_only_exts:
            continue
        total += 1

    return {"total": total, "matched": total, "warnings": []}


def get_clip_info(clip):
    """Ritorna dict con info essenziali di un clip."""
    if isinstance(clip, dict) and "id" in clip:
        return {
            "name": clip.get("name", ""),
            "file_path": clip.get("file_path", ""),
            "frames": clip.get("frames", 0),
            "fps": clip.get("fps", 24.0),
            "media_pool_item": clip,
        }
    fps_str = clip.GetClipProperty("FPS") or "24"
    try:
        fps = float(fps_str)
    except (ValueError, TypeError):
        fps = 24.0

    return {
        "name": clip.GetClipProperty("Clip Name") or clip.GetClipProperty("File Name") or "",
        "file_path": clip.GetClipProperty("File Path") or "",
        "frames": int(clip.GetClipProperty("Frames") or 0),
        "fps": fps,
        "media_pool_item": clip,
    }


# ─── Timeline placement ───

def place_clips_on_timeline(media_pool, clip_entries, track_index):
    """Piazza clip sulla timeline usando AppendToTimeline.

    clip_entries: lista di dict {mediaPoolItem, startFrame, endFrame}
    Ritorna lista di TimelineItem piazzati.
    """
    placed = []
    for i, entry in enumerate(clip_entries):
        clip_info = {
            "mediaPoolItem": entry["mediaPoolItem"],
            "startFrame": entry["startFrame"],
            "endFrame": entry["endFrame"],
        }
        result = media_pool.AppendToTimeline([clip_info])
        if result:
            placed.extend(result)
    return placed


def place_clips_precise(media_pool, timeline, clip_entries, track_index,
                        marker_frames, timeline_fps):
    """Piazza clip una alla volta leggendo la posizione reale da Resolve.

    In proxy mode, delega tutto al subprocess worker.

    Usa GetItemListInTrack per leggere la posizione effettiva dopo
    ogni piazzamento, e ricalcola i frame sorgente della clip
    successiva per agganciare il marker con precisione al frame.

    Ritorna lista di TimelineItem piazzati.
    """
    import math

    if not clip_entries or not marker_frames:
        return []

    # Subprocess proxy mode: delegate entirely to worker
    if _is_proxy(timeline):
        try:
            from app.licensing import storage as _cfg
            _k = 0x3f7a9c2e1b5d0847
            _v = getattr(_cfg, '_MODULE_SIG', '') == "e4a7c1f8d93b2065"
            _v = _v and (_cfg._auth(7331) == (7331 ^ _k))
            if not _v or (_cfg.is_trial_expired() and not _cfg.load_license()):
                return []
        except Exception:
            return []
        serialized = []
        for e in clip_entries:
            mpi = e["mediaPoolItem"]
            clip_id = mpi.get("id", "") if isinstance(mpi, dict) else ""
            serialized.append({
                "clip_id": clip_id,
                "startFrame": e["startFrame"],
                "endFrame": e["endFrame"],
                "clip_fps": e.get("clip_fps", timeline_fps),
            })
        resp = _proxy_send("place_clips",
                                   entries=serialized,
                                   track_idx=track_index,
                                   marker_frames=marker_frames,
                                   fps=timeline_fps)
        if resp.get("ok"):
            return resp.get("items", [])
        return []

    try:
        from app.licensing import storage as _cfg
        _k = 0x3f7a9c2e1b5d0847
        _v = getattr(_cfg, '_MODULE_SIG', '') == "e4a7c1f8d93b2065"
        _v = _v and (_cfg._auth(7331) == (7331 ^ _k))
        if not _v or (_cfg.is_trial_expired() and not _cfg.load_license()):
            return []
    except Exception:
        return []

    tl_start = get_timeline_start_frame(timeline)

    sorted_markers = sorted(marker_frames)
    if sorted_markers[0] > 0:
        sorted_markers.insert(0, 0)

    for i, entry in enumerate(clip_entries):
        mpi = entry["mediaPoolItem"]
        start_f = entry["startFrame"]
        end_f = entry["endFrame"]
        clip_fps = entry.get("clip_fps", timeline_fps) or timeline_fps

        target_marker_idx = i + 1
        if target_marker_idx < len(sorted_markers):
            target_end_abs = sorted_markers[target_marker_idx] + tl_start
        else:
            target_end_abs = None

        # Dal secondo clip in poi: leggi posizione REALE dalla timeline
        if i > 0 and target_end_abs is not None:
            try:
                items_on_track = timeline.GetItemListInTrack("video", track_index)
                if items_on_track and len(items_on_track) > 0:
                    last_item = items_on_track[-1]
                    actual_pos = int(last_item.GetEnd())
                    needed_tl = target_end_abs - actual_pos

                    if needed_tl > 0:
                        fps_ratio = clip_fps / timeline_fps
                        same_fps = abs(fps_ratio - 1.0) < 0.01

                        if same_fps:
                            new_segment = needed_tl
                        else:
                            exact_src = needed_tl * fps_ratio
                            src_lo = max(1, math.floor(exact_src))
                            src_hi = max(1, math.ceil(exact_src))
                            tl_lo = int(src_lo * timeline_fps / clip_fps)
                            tl_hi = int(src_hi * timeline_fps / clip_fps)
                            if abs(tl_lo - needed_tl) <= abs(tl_hi - needed_tl):
                                new_segment = src_lo
                            else:
                                new_segment = src_hi

                        end_f = start_f + new_segment
            except Exception:
                pass

        result = media_pool.AppendToTimeline([{
            "mediaPoolItem": mpi,
            "startFrame": start_f,
            "endFrame": end_f,
            "mediaType": 1,
            "trackIndex": track_index,
        }])

        if not result:
            continue

    # Ritorna gli items reali dalla timeline
    try:
        final_items = timeline.GetItemListInTrack("video", track_index)
        return list(final_items) if final_items else []
    except Exception:
        return []


def add_transitions(timeline, track_index, transition_type="Cross Dissolve",
                     duration_frames=8):
    """Aggiunge transizioni tra i clip su una traccia video.

    transition_type: tipo di transizione Resolve
    duration_frames: durata della transizione in frame
    Ritorna quante transizioni aggiunte.
    """
    items = timeline.GetItemListInTrack("video", track_index)
    if not items or len(items) < 2:
        return 0

    added = 0
    for i in range(len(items) - 1):
        try:
            # AddTransition su timeline: tra item[i] e item[i+1]
            # L'API usa il punto di edit (fine clip corrente)
            end_frame = items[i].GetEnd()
            result = timeline.AddTransition(
                "video", track_index, end_frame,
                transition_type, duration_frames
            )
            if result:
                added += 1
        except Exception:
            pass
    return added


def apply_beat_zoom(timeline, track_index, zoom_pct, bar_frames=None,
                    easing_type="ease_out", zoom_dir="out"):
    """Applica zoom animato sui clip usando Fusion Transform con keyframe.

    zoom_pct: percentuale di zoom (es. 5 = 1.05x)
    bar_frames: frame dei downbeat (0-based). Se forniti, zoom solo su quei
                clip. Se None, alterna zoom su clip pari/dispari.
    easing_type: tipo di curva easing (vedi ZOOM_EASINGS)
    zoom_dir: "out" (zoom→normal) o "in" (normal→zoom)
    """
    if easing_type == "none":
        return 0

    items = timeline.GetItemListInTrack("video", track_index)
    if not items:
        return 0

    zoom_value = 1.0 + (zoom_pct / 100.0)
    applied = 0
    tl_offset = get_timeline_start_frame(timeline)

    if bar_frames:
        bar_set = set(bf + tl_offset for bf in bar_frames)

    for i, item in enumerate(items):
        if bar_frames:
            start = int(item.GetStart())
            should_zoom = any(abs(start - bf) <= 2 for bf in bar_set)
        else:
            should_zoom = (i % 2 == 0)

        if not should_zoom:
            continue

        duration = int(item.GetEnd()) - int(item.GetStart())
        if duration < 2:
            continue

        try:
            if _apply_fusion_zoom(item, zoom_value, duration, easing_type, zoom_dir):
                applied += 1
            else:
                item.SetProperty("ZoomX", zoom_value)
                item.SetProperty("ZoomY", zoom_value)
                applied += 1
        except Exception:
            try:
                item.SetProperty("ZoomX", zoom_value)
                item.SetProperty("ZoomY", zoom_value)
                applied += 1
            except Exception:
                pass

    return applied


# ─── Fusion node helpers ───
# Chain: MediaIn → [TimeSpeed] → [Transform] → MediaOut


def _get_or_create_comp(item):
    """Load existing Fusion comp or create a new one.

    Verifica che la comp abbia MediaIn1 e MediaOut1 con output valido.
    Riprova fino a 8 volte con delay crescente.
    """
    import time
    comp_names = item.GetFusionCompNameList()
    comp = None
    if comp_names:
        comp = item.LoadFusionCompByName(comp_names[0])
    if not comp:
        comp = item.AddFusionComp()
    if not comp:
        return None
    # Aspetta che MediaIn1/MediaOut1 siano pronti
    for attempt in range(8):
        mi = comp.FindTool("MediaIn1")
        mo = comp.FindTool("MediaOut1")
        if mi and mo:
            # Aspetta un extra frame per assicurare che i nodi abbiano output
            if attempt == 0:
                time.sleep(0.1)
            return comp
        time.sleep(0.2 + attempt * 0.15)
    return comp


def _find_tools(comp):
    """Find TimeSpeed and Transform nodes in a comp."""
    ts, xfm = None, None
    tools = comp.GetToolList(False) or {}
    for _, tool in tools.items():
        try:
            reg = tool.GetAttrs("TOOLS_RegID")
            if reg == "TimeSpeed":
                ts = tool
            elif reg == "Transform":
                xfm = tool
        except Exception:
            pass
    return ts, xfm


def _reconnect_chain(comp, ts, xfm):
    """Reconnect: MediaIn → [TimeSpeed] → [Transform] → MediaOut.

    Ritenta fino a 3 volte se la connessione non va a buon fine.
    Verifica ogni connessione individualmente.
    """
    import time
    for attempt in range(3):
        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")
        if not media_in or not media_out:
            time.sleep(0.3)
            continue
        try:
            # Connetti uno alla volta con verifica
            prev = media_in
            if ts:
                try:
                    ts.Input = prev
                except Exception:
                    time.sleep(0.2)
                    ts.Input = prev
                prev = ts
            if xfm:
                try:
                    xfm.Input = prev
                except Exception:
                    time.sleep(0.2)
                    xfm.Input = prev
                prev = xfm
            try:
                media_out.Input = prev
            except Exception:
                time.sleep(0.2)
                media_out.Input = prev
            return True
        except Exception:
            time.sleep(0.3)
    return False


# ─── Zoom ───


def remove_zoom(item):
    """Remove Fusion zoom (Transform) from a timeline item."""
    removed = False
    try:
        comp_names = item.GetFusionCompNameList() or []
        for name in comp_names:
            comp = item.LoadFusionCompByName(name)
            if not comp:
                continue
            ts, xfm = _find_tools(comp)
            if xfm:
                xfm.Delete()
                removed = True
            _reconnect_chain(comp, ts, None)
            if not ts:
                try:
                    item.DeleteFusionCompByName(name)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        item.SetProperty("ZoomX", 1.0)
        item.SetProperty("ZoomY", 1.0)
    except Exception:
        pass
    return removed


def _apply_fusion_zoom(item, zoom_value, duration, easing_type, zoom_dir="out"):
    """Applica zoom keyframato via Fusion Transform.Size.

    zoom_dir="out": zoom_value → 1.0
    zoom_dir="in": 1.0 → zoom_value
    zoom_dir="in_out": 1.0 → zoom_value → 1.0
    """
    try:
        comp = _get_or_create_comp(item)
        if not comp:
            return False
        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")
        if not media_in or not media_out:
            return False

        ts, existing_xfm = _find_tools(comp)

        if existing_xfm:
            xfm = existing_xfm
        else:
            xfm = comp.AddTool("Transform", 1, 0)
            if not xfm:
                return False

        _reconnect_chain(comp, ts, xfm)

        delta = zoom_value - 1.0
        xfm.Size = comp.BezierSpline()

        if zoom_dir == "in_out":
            half = duration // 2
            points_in = _sample_easing(easing_type, num_samples=8)
            for t_val, v in points_in:
                frame = int(t_val * max(1, half - 1))
                xfm.Size[frame] = max(1.0, 1.0 + delta * v)
            points_out = _sample_easing(easing_type, num_samples=8)
            for t_val, v in points_out:
                frame = half + int(t_val * max(1, (duration - half) - 1))
                xfm.Size[frame] = max(1.0, zoom_value - delta * v)
        else:
            points = _sample_easing(easing_type, num_samples=10)
            for t_val, v in points:
                frame = int(t_val * (duration - 1))
                if zoom_dir == "in":
                    size = 1.0 + delta * v
                else:
                    size = zoom_value - delta * v
                xfm.Size[frame] = max(1.0, size)

        return True
    except Exception:
        return False


# ─── Speed Ramp ───


def remove_speed_ramp(item):
    """Remove Fusion speed ramp (TimeSpeed) from a timeline item."""
    removed = False
    try:
        comp_names = item.GetFusionCompNameList() or []
        for name in comp_names:
            comp = item.LoadFusionCompByName(name)
            if not comp:
                continue
            ts, xfm = _find_tools(comp)
            if ts:
                ts.Delete()
                removed = True
            _reconnect_chain(comp, None, xfm)
            if not xfm:
                try:
                    item.DeleteFusionCompByName(name)
                except Exception:
                    pass
    except Exception:
        pass
    return removed


def _apply_fusion_speed_ramp(item, speed_value, duration, easing_type,
                             ramp_dir="in", speed_from=None,
                             freeze_frames=0, optical_flow=False):
    """Applica speed ramp via Fusion TimeSpeed.Speed.

    speed_from: velocita di partenza/arrivo (default 1.0).
                Se > 1.0 crea effetto fast→slow→fast.
    speed_value: velocita target (il punto piu lento/veloce del ramp).
    freeze_frames: frame di pausa (speed=0) nel punto di transizione.
    optical_flow: se True, imposta Resolve Optical Flow per slowmo fluido.

    ramp_dir="in":     speed_from → speed_value
    ramp_dir="out":    speed_value → speed_from
    ramp_dir="in_out": speed_from → speed_value → speed_from
    """
    try:
        # ── Optical Flow: imposta interpolazione retime ──
        if optical_flow:
            try:
                item.SetProperty("Retime Process", 1)  # 0=Nearest, 1=Optical Flow
            except Exception:
                pass

        comp = _get_or_create_comp(item)
        if not comp:
            return False
        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")
        if not media_in or not media_out:
            return False

        existing_ts, xfm = _find_tools(comp)

        if existing_ts:
            ts = existing_ts
        else:
            ts = comp.AddTool("TimeSpeed", 1, 0)
            if not ts:
                return False

        _reconnect_chain(comp, ts, xfm)

        base = speed_from if speed_from is not None else 1.0
        delta = speed_value - base
        ts.Speed = comp.BezierSpline()

        if ramp_dir == "in_out":
            # Calcola spazio per freeze frame al centro
            freeze = min(freeze_frames, duration // 4)
            ramp_in = (duration - freeze) // 2
            ramp_out = duration - freeze - ramp_in

            # Ramp in: base → speed_value
            points_in = _sample_easing(easing_type, num_samples=8)
            for t_val, v in points_in:
                frame = int(t_val * max(1, ramp_in - 1))
                speed = base + delta * v
                ts.Speed[frame] = speed

            # Freeze frame al centro
            if freeze > 0:
                for f in range(ramp_in, ramp_in + freeze):
                    ts.Speed[f] = 0.0

            # Ramp out: speed_value → base
            offset = ramp_in + freeze
            points_out = _sample_easing(easing_type, num_samples=8)
            for t_val, v in points_out:
                frame = offset + int(t_val * max(1, ramp_out - 1))
                speed = speed_value - delta * v
                ts.Speed[frame] = speed
        else:
            # Freeze frame: al punto di transizione
            freeze = min(freeze_frames, duration // 4)
            ramp_dur = duration - freeze

            points = _sample_easing(easing_type, num_samples=10)

            if ramp_dir == "out":
                # speed_value → [freeze] → base
                for t_val, v in points:
                    frame = int(t_val * max(1, ramp_dur - 1))
                    speed = speed_value - delta * v
                    ts.Speed[frame] = speed
                if freeze > 0:
                    for f in range(ramp_dur, ramp_dur + freeze):
                        ts.Speed[f] = 0.0
            else:  # "in"
                # base → [freeze at target] → fine
                if freeze > 0:
                    # Ramp prima, freeze dopo
                    for t_val, v in points:
                        frame = int(t_val * max(1, ramp_dur - 1))
                        speed = base + delta * v
                        ts.Speed[frame] = speed
                    for f in range(ramp_dur, ramp_dur + freeze):
                        ts.Speed[f] = 0.0
                else:
                    for t_val, v in points:
                        frame = int(t_val * (duration - 1))
                        speed = base + delta * v
                        ts.Speed[frame] = speed

        return True
    except Exception:
        return False


def apply_clip_effects(item, zoom_params=None, speed_params=None):
    """Applica zoom e/o speed ramp a una clip in una singola apertura della comp.

    Evita il problema 'no frame available' causato dall'aprire la comp due volte.

    zoom_params: dict con zoom_value, duration, easing_type, zoom_dir (o None)
    speed_params: dict con speed_value, duration, easing_type, ramp_dir,
                  speed_from, freeze_frames, optical_flow (o None)
    """
    if not zoom_params and not speed_params:
        return True

    try:
        # Optical Flow (prima di aprire la comp)
        if speed_params and speed_params.get("optical_flow"):
            try:
                item.SetProperty("Retime Process", 1)
            except Exception:
                pass

        comp = _get_or_create_comp(item)
        if not comp:
            return False
        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")
        if not media_in or not media_out:
            return False

        existing_ts, existing_xfm = _find_tools(comp)

        # Prima connetti la catena base, poi aggiungi nodi
        # Questo assicura che MediaIn→MediaOut sia stabile
        _reconnect_chain(comp, existing_ts, existing_xfm)

        # ── Zoom (Transform) ──
        xfm = existing_xfm
        if zoom_params:
            zp = zoom_params
            if not xfm:
                xfm = comp.AddTool("Transform", 1, 0)
                if xfm:
                    import time; time.sleep(0.15)  # attendi inizializzazione nodo
            if xfm:
                delta = zp["zoom_value"] - 1.0
                dur = zp["duration"]
                xfm.Size = comp.BezierSpline()

                if zp.get("zoom_dir") == "in_out":
                    half = dur // 2
                    for t_val, v in _sample_easing(zp["easing_type"], 8):
                        frame = int(t_val * max(1, half - 1))
                        xfm.Size[frame] = max(1.0, 1.0 + delta * v)
                    for t_val, v in _sample_easing(zp["easing_type"], 8):
                        frame = half + int(t_val * max(1, (dur - half) - 1))
                        xfm.Size[frame] = max(1.0, zp["zoom_value"] - delta * v)
                else:
                    for t_val, v in _sample_easing(zp["easing_type"], 10):
                        frame = int(t_val * (dur - 1))
                        if zp.get("zoom_dir") == "in":
                            size = 1.0 + delta * v
                        else:
                            size = zp["zoom_value"] - delta * v
                        xfm.Size[frame] = max(1.0, size)

        # ── Speed Ramp (TimeSpeed) ──
        ts = existing_ts
        if speed_params:
            sp = speed_params
            if not ts:
                ts = comp.AddTool("TimeSpeed", 1, 0)
                if ts:
                    import time; time.sleep(0.15)  # attendi inizializzazione nodo
            if ts:
                base = sp.get("speed_from") or 1.0
                sv = sp["speed_value"]
                delta_s = sv - base
                dur = sp["duration"]
                freeze_frames = sp.get("freeze_frames", 0)
                etype = sp["easing_type"]
                rdir = sp.get("ramp_dir", "in")

                # Clip frames totali per ancoraggio finale
                total_clip = sp.get("clip_frames", dur + 10)

                ts.Speed = comp.BezierSpline()

                # Frame 0: velocità base esplicita
                ts.Speed[0] = base

                if rdir == "in_out":
                    freeze = min(freeze_frames, dur // 4)
                    ramp_in = (dur - freeze) // 2
                    ramp_out = dur - freeze - ramp_in
                    for t_val, v in _sample_easing(etype, 8):
                        frame = int(t_val * max(1, ramp_in - 1))
                        ts.Speed[frame] = base + delta_s * v
                    if freeze > 0:
                        for f in range(ramp_in, ramp_in + freeze):
                            ts.Speed[f] = 0.0
                    offset = ramp_in + freeze
                    for t_val, v in _sample_easing(etype, 8):
                        frame = offset + int(t_val * max(1, ramp_out - 1))
                        ts.Speed[frame] = sv - delta_s * v
                else:
                    freeze = min(freeze_frames, dur // 4)
                    ramp_dur = dur - freeze
                    points = _sample_easing(etype, 10)
                    if rdir == "out":
                        for t_val, v in points:
                            frame = int(t_val * max(1, ramp_dur - 1))
                            ts.Speed[frame] = sv - delta_s * v
                        if freeze > 0:
                            for f in range(ramp_dur, ramp_dur + freeze):
                                ts.Speed[f] = 0.0
                    else:
                        if freeze > 0:
                            for t_val, v in points:
                                frame = int(t_val * max(1, ramp_dur - 1))
                                ts.Speed[frame] = base + delta_s * v
                            for f in range(ramp_dur, ramp_dur + freeze):
                                ts.Speed[f] = 0.0
                        else:
                            for t_val, v in points:
                                frame = int(t_val * (dur - 1))
                                ts.Speed[frame] = base + delta_s * v

                # Ancora: forza velocità 1.0 dal frame dopo il ramp fino alla fine
                # Così Fusion non cerca frame oltre quelli disponibili
                anchor_frame = dur + 1
                if anchor_frame < total_clip:
                    ts.Speed[anchor_frame] = 1.0
                    ts.Speed[total_clip - 1] = 1.0

        # Riconnetti catena finale — se fallisce, rimuovi nodi orfani
        if not _reconnect_chain(comp, ts, xfm):
            # Pulizia: rimuovi nodi creati che non sono collegati
            if ts and not existing_ts:
                try:
                    ts.Delete()
                except Exception:
                    pass
            if xfm and not existing_xfm:
                try:
                    xfm.Delete()
                except Exception:
                    pass
            # Ricollegamento diretto MediaIn → MediaOut
            try:
                mi = comp.FindTool("MediaIn1")
                mo = comp.FindTool("MediaOut1")
                if mi and mo:
                    mo.Input = mi
            except Exception:
                pass
            return False
        return True

    except Exception:
        return False
