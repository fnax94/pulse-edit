"""Storage licenza + trial counter multi-location (cross-platform)."""

import subprocess
import time
import json
import os
import platform
import hashlib

APP_NAME = "PulseEdit"
IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    _APPDATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PulseEdit")
    CACHE_FILE = os.path.join(_APPDATA, "license_cache.json")
else:
    CACHE_FILE = os.path.expanduser("~/Library/Application Support/PulseEdit/license_cache.json")

REVALIDATION_DAYS = 7
OFFLINE_GRACE_DAYS = 30

_MODULE_SIG = "e4a7c1f8d93b2065"
_XOR_KEY = 0x3f7a9c2e1b5d0847


def _auth(c):
    return c ^ _XOR_KEY

TRIAL_LIMIT = 4

if IS_WINDOWS:
    _TRIAL_LOCATIONS = [
        os.path.join(os.environ.get("APPDATA", ""), ".pe_session"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), ".com.pulseedit.analytics"),
        os.path.join(os.environ.get("TEMP", ""), ".pe_prefs.dat"),
    ]
else:
    _TRIAL_LOCATIONS = [
        os.path.expanduser("~/Library/Application Support/.pe_session"),
        os.path.expanduser("~/Library/Caches/.com.pulseedit.analytics"),
        os.path.expanduser("~/Library/Preferences/.pe_prefs.dat"),
    ]
_TRIAL_KEYCHAIN_SERVICE = "com.pulseedit.session"


# --- Windows Credential Manager (ctypes) ---

def _win_save_credential(service, value):
    """Save a credential to Windows Credential Manager."""
    import ctypes
    import ctypes.wintypes as wt
    advapi32 = ctypes.windll.advapi32

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wt.DWORD),
            ("Type", wt.DWORD),
            ("TargetName", wt.LPWSTR),
            ("Comment", wt.LPWSTR),
            ("LastWritten", wt.FILETIME),
            ("CredentialBlobSize", wt.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wt.DWORD),
            ("AttributeCount", wt.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wt.LPWSTR),
            ("UserName", wt.LPWSTR),
        ]

    blob = value.encode("utf-16-le")
    blob_array = (ctypes.c_byte * len(blob))(*blob)
    cred = CREDENTIAL()
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = f"{APP_NAME}_{service}"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = blob_array
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = APP_NAME
    return advapi32.CredWriteW(ctypes.byref(cred), 0)


def _win_load_credential(service):
    """Load a credential from Windows Credential Manager."""
    import ctypes
    import ctypes.wintypes as wt
    advapi32 = ctypes.windll.advapi32

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wt.DWORD),
            ("Type", wt.DWORD),
            ("TargetName", wt.LPWSTR),
            ("Comment", wt.LPWSTR),
            ("LastWritten", wt.FILETIME),
            ("CredentialBlobSize", wt.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wt.DWORD),
            ("AttributeCount", wt.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wt.LPWSTR),
            ("UserName", wt.LPWSTR),
        ]

    pcred = ctypes.POINTER(CREDENTIAL)()
    ok = advapi32.CredReadW(f"{APP_NAME}_{service}", 1, 0, ctypes.byref(pcred))
    if not ok:
        return None
    try:
        blob_size = pcred.contents.CredentialBlobSize
        blob = ctypes.string_at(pcred.contents.CredentialBlob, blob_size)
        return blob.decode("utf-16-le")
    finally:
        advapi32.CredFree(pcred)


def _win_delete_credential(service):
    """Delete a credential from Windows Credential Manager."""
    import ctypes
    advapi32 = ctypes.windll.advapi32
    advapi32.CredDeleteW(f"{APP_NAME}_{service}", 1, 0)


# --- License storage (platform-specific) ---

def save_license(key):
    """Salva la licenza (Keychain su macOS, Credential Manager su Windows)."""
    if IS_WINDOWS:
        ok = _win_save_credential("license", key)
        if ok:
            _update_cache(key)
        return bool(ok)
    else:
        try:
            subprocess.run(
                ["security", "delete-generic-password", "-a", APP_NAME, "-s", "license"],
                capture_output=True, timeout=10
            )
            result = subprocess.run(
                ["security", "add-generic-password", "-a", APP_NAME, "-s", "license", "-w", key],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                _update_cache(key)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False


def load_license():
    """Carica la licenza. Ritorna la chiave o None."""
    if IS_WINDOWS:
        return _win_load_credential("license")
    else:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", APP_NAME, "-s", "license", "-w"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            pass
        return None


def remove_license():
    """Rimuovi la licenza."""
    if IS_WINDOWS:
        _win_delete_credential("license")
    else:
        try:
            subprocess.run(
                ["security", "delete-generic-password", "-a", APP_NAME, "-s", "license"],
                capture_output=True, timeout=10
            )
        except subprocess.TimeoutExpired:
            pass
    try:
        os.remove(CACHE_FILE)
    except OSError:
        pass


def needs_revalidation():
    """Controlla se la licenza deve essere rivalidata online."""
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        last_check = cache.get("last_check", 0)
        days_since = (time.time() - last_check) / 86400
        return days_since > REVALIDATION_DAYS
    except (FileNotFoundError, json.JSONDecodeError):
        return True


def is_within_offline_grace():
    """Controlla se siamo ancora nel periodo di grazia offline."""
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        last_check = cache.get("last_check", 0)
        days_since = (time.time() - last_check) / 86400
        return days_since <= OFFLINE_GRACE_DAYS
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def _update_cache(key):
    """Aggiorna il file cache con timestamp corrente."""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    cache = {"key": key, "last_check": time.time()}
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


# --- Trial counter (multi-location, tamper-resistant) ---

def _encode_count(n):
    token = hashlib.sha256(f"pe_{n}_salt47".encode()).hexdigest()[:12]
    return json.dumps({"v": n, "t": token})


def _decode_count(data):
    try:
        obj = json.loads(data)
        n = obj["v"]
        token = hashlib.sha256(f"pe_{n}_salt47".encode()).hexdigest()[:12]
        if obj.get("t") == token:
            return n
    except Exception:
        pass
    return None


def _read_file_count(path):
    try:
        with open(path, "r") as f:
            return _decode_count(f.read())
    except Exception:
        return None


def _write_file_count(path, n):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(_encode_count(n))
    except Exception:
        pass


def _read_keychain_count():
    if IS_WINDOWS:
        val = _win_load_credential(_TRIAL_KEYCHAIN_SERVICE)
        if val:
            return _decode_count(val)
        return None
    else:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", APP_NAME,
                 "-s", _TRIAL_KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return _decode_count(result.stdout.strip())
        except subprocess.TimeoutExpired:
            pass
        return None


def _write_keychain_count(n):
    if IS_WINDOWS:
        _win_save_credential(_TRIAL_KEYCHAIN_SERVICE, _encode_count(n))
    else:
        try:
            subprocess.run(
                ["security", "delete-generic-password", "-a", APP_NAME,
                 "-s", _TRIAL_KEYCHAIN_SERVICE],
                capture_output=True, timeout=10
            )
            subprocess.run(
                ["security", "add-generic-password", "-a", APP_NAME,
                 "-s", _TRIAL_KEYCHAIN_SERVICE, "-w", _encode_count(n)],
                capture_output=True, timeout=10
            )
        except subprocess.TimeoutExpired:
            pass


def get_trial_count():
    """Get trial usage count (MAX across all locations)."""
    counts = []
    kc = _read_keychain_count()
    if kc is not None:
        counts.append(kc)
    for path in _TRIAL_LOCATIONS:
        fc = _read_file_count(path)
        if fc is not None:
            counts.append(fc)
    best = max(counts) if counts else 0
    _sync_all(best)
    return best


def increment_trial():
    """Increment trial counter. Returns new count."""
    current = get_trial_count()
    new_count = current + 1
    _sync_all(new_count)
    return new_count


def trial_remaining():
    """Returns how many trial uses remain."""
    return max(0, TRIAL_LIMIT - get_trial_count())


def is_trial_expired():
    """Returns True if trial is exhausted."""
    return get_trial_count() >= TRIAL_LIMIT


def _sync_all(n):
    """Write count to ALL storage locations."""
    _write_keychain_count(n)
    for path in _TRIAL_LOCATIONS:
        _write_file_count(path, n)
