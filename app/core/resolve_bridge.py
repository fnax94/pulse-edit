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


def _discover_resolve_paths_windows():
    """Auto-discover DaVinci Resolve install path on Windows via registry + filesystem scan."""
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
    #    Scan ALL drives (D:, E:, etc.) not just C:
    scan_roots = set()
    if resolve_root:
        scan_roots.add(resolve_root)
    for base in [_pf, _pf86, _pd]:
        bm = os.path.join(base, "Blackmagic Design")
        if os.path.isdir(bm):
            scan_roots.add(bm)
    try:
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
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
            lines.append(f"  {'[OK]' if exists else '[--]'} {p}")
        lines.append("Library paths searched:")
        for p in _MAC_LIB_PATHS:
            exists = os.path.isdir(p)
            lines.append(f"  {'[OK]' if exists else '[--]'} {p}")
    if _IS_WINDOWS:
        import tempfile as _tf
        lines.append(f"\nLog file: {os.path.join(_tf.gettempdir(), 'pulseedit_debug.log')}")
    else:
        lines.append("\nLog file: /tmp/pulseedit_debug.log")
    return "\n".join(lines)


def _register_python_in_registry():
    """Register bundled python_shim in Windows registry so fusionscript.dll can find it.
    fusionscript.dll checks HKCU\\Software\\Python\\PythonCore\\3.11\\InstallPath at init."""
    app_dir = os.path.dirname(sys.executable)
    shim_dir = os.path.join(app_dir, "python_shim")
    if not os.path.isdir(shim_dir):
        return
    try:
        import winreg
        key_path = r"Software\Python\PythonCore\3.11\InstallPath"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            current = None
            try:
                current, _ = winreg.QueryValueEx(key, "ExecutablePath")
            except FileNotFoundError:
                pass
            if current and os.path.exists(current):
                _log.info(f"Python 3.11 already registered at: {current}")
                return
            shim_exe = os.path.join(shim_dir, "python.exe")
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, shim_dir + os.sep)
            winreg.SetValueEx(key, "ExecutablePath", 0, winreg.REG_SZ, shim_exe)
            winreg.SetValueEx(key, "WindowedExecutablePath", 0, winreg.REG_SZ, shim_exe)
            _log.info(f"Registered python_shim in registry: {shim_dir}")
    except Exception as e:
        _log.warning(f"Could not register python_shim in registry: {e}")


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



def connect(retries=3, delay=1.5):
    """Connette a DaVinci Resolve con retry. Ritorna l'oggetto resolve o None."""
    if not _is_resolve_running():
        _log.warning("Resolve process not detected — trying to connect anyway")

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
        # fusionscript.dll needs python3.exe in PATH during init
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
                            _log.info(f"Found script lib: {lib}")
                            break

    # Pre-flight: try loading fusionscript DLL directly to catch load errors
    if _IS_WINDOWS:
        dll_path = os.environ.get("RESOLVE_SCRIPT_LIB", "")
        if dll_path and os.path.exists(dll_path):
            try:
                import ctypes
                ctypes.CDLL(dll_path)
                _log.info(f"DLL pre-load OK: {dll_path}")
            except OSError as e:
                _log.error(f"DLL pre-load FAILED: {dll_path} — {e}")
                _log.error("This usually means Visual C++ Redistributable is missing. Install from: https://aka.ms/vs/17/release/vc_redist.x64.exe")
            except Exception as e:
                _log.error(f"DLL pre-load unexpected error: {e}")
        else:
            _log.error(f"fusionscript.dll not found at: {dll_path}")

    _log.info(f"ENV RESOLVE_SCRIPT_API = {os.environ.get('RESOLVE_SCRIPT_API', '(not set)')}")
    _log.info(f"ENV RESOLVE_SCRIPT_LIB = {os.environ.get('RESOLVE_SCRIPT_LIB', '(not set)')}")
    _log.info(f"sys.path Resolve entries: {[p for p in sys.path if 'Blackmagic' in p or 'Resolve' in p or 'resolve' in p]}")

    for attempt in range(retries):
        try:
            import DaVinciResolveScript as dvr
            _log.info(f"DaVinciResolveScript imported OK (attempt {attempt + 1})")
            resolve = dvr.scriptapp("Resolve")
            if resolve:
                _log.info(f"Connected to Resolve (attempt {attempt + 1})")
                return resolve
            _log.warning(f"scriptapp returned None (attempt {attempt + 1}/{retries}) — Resolve may be Free edition or scripting disabled")
        except ImportError as e:
            _log.error(f"Cannot import DaVinciResolveScript: {e}")
            _log.error(f"Searched paths: {[p for p in sys.path if 'Blackmagic' in p or 'Resolve' in p or 'resolve' in p]}")
            return None
        except Exception as e:
            _log.warning(f"Connect attempt {attempt + 1}/{retries} failed: {type(e).__name__}: {e}")
        if attempt < retries - 1:
            _time.sleep(delay)

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

def get_audio_tracks(timeline):
    """Ritorna dict {label: track_index} delle tracce audio con clip."""
    tracks = {}
    for t_idx in range(1, timeline.GetTrackCount("audio") + 1):
        items = timeline.GetItemListInTrack("audio", t_idx)
        if items and len(items) > 0:
            name = ""
            for item in items:
                mp = item.GetMediaPoolItem()
                if mp:
                    name = mp.GetClipProperty("Clip Name") or ""
                    break
            label = f"Track {t_idx}: {name} ({len(items)} clip)"
            tracks[label] = t_idx
    return tracks


def find_audio_file(timeline, track_idx):
    """Trova il percorso del file audio del primo clip nella traccia."""
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
    items = timeline.GetItemListInTrack("video", track_index)
    if items and len(items) > 0:
        timeline.DeleteClips(items)
        return len(items)
    return 0


# ─── Beat markers on timeline ───

def place_bar_markers(timeline, bar_times, fps, color="Yellow"):
    """Piazza marker oro sulla timeline per ogni inizio battuta (downbeat).

    Ritorna il numero di marker piazzati.
    """
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
    """
    clips = folder.GetClipList()
    if not clips:
        return []

    video_clips = []
    for clip in clips:
        # Deve avere un file path reale (escludi timeline/compound clip)
        file_path = clip.GetClipProperty("File Path") or ""
        if not file_path or not os.path.exists(file_path):
            continue

        # Controlla che abbia frame video
        frames_str = clip.GetClipProperty("Frames")
        if not frames_str:
            continue
        try:
            frames = int(frames_str)
        except (ValueError, TypeError):
            continue
        if frames <= 0:
            continue

        # Escludi clip solo-audio
        ext = os.path.splitext(file_path)[1].lower()
        audio_only_exts = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}
        if ext in audio_only_exts:
            continue

        video_clips.append(clip)
    return video_clips


def scan_clips_in_folder(folder, timeline_fps):
    """Scansiona clip in una cartella e conta i clip video disponibili.

    DaVinci Resolve conforma tutti i clip al FPS della timeline,
    quindi qualsiasi FPS e' compatibile.

    Ritorna dict con:
        - total: numero totale clip video
        - matched: uguale a total (tutti compatibili)
        - warnings: lista vuota (nessun warning FPS)
    """
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

    return {
        "total": total,
        "matched": total,
        "warnings": [],
    }


def get_clip_info(clip):
    """Ritorna dict con info essenziali di un clip."""
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

    Usa GetItemListInTrack per leggere la posizione effettiva dopo
    ogni piazzamento, e ricalcola i frame sorgente della clip
    successiva per agganciare il marker con precisione al frame.

    Ritorna lista di TimelineItem piazzati.
    """
    import math

    if not clip_entries or not marker_frames:
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
