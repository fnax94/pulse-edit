"""Telemetry anonima per Pulse Edit (Studio + Free).

Cosa fa:
- Invia eventi a https://license-server.abtools.workers.dev/event
- Anonimo: solo device_id (SHA256 hostname truncato), product, version, OS
- Eventi: boot, crash, workflow_success/fail, beat_detect_fail, render_fail
- Opt-out: rispetta il flag in user settings (`telemetry_enabled = false`)
- Best-effort: thread daemon, timeout 4s, errore silenzioso (mai blocca l'app)

Privacy:
- Nessun PII (no email, no path file utente, no contenuto audio/video)
- Stack trace sanitizzato (path utente rimpiazzati con <user>)
- Vedi privacy policy: https://pulseedit.com/privacy
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import socket
import ssl
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from typing import Any, Optional

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

ENDPOINT = "https://license-server.abtools.workers.dev/event"
REQ_TIMEOUT_SECS = 4


def _prefs_dir(product: str) -> str:
    """User-data dir per il prodotto (Pulse Edit Studio vs Free)."""
    sub = "PulseEditFree" if product.endswith("free") else "PulseEdit"
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, sub)
    return os.path.expanduser(f"~/Library/Application Support/{sub}")


def _prefs_path(product: str) -> str:
    return os.path.join(_prefs_dir(product), "telemetry.json")


def load_opt_out(product: str) -> bool:
    """Legge la preferenza utente. Default: telemetria ON (opt-out)."""
    try:
        with open(_prefs_path(product), "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("enabled", True))
    except Exception:
        return True  # default ON


def save_opt_out(product: str, enabled: bool) -> None:
    """Salva preferenza utente."""
    try:
        d = _prefs_dir(product)
        os.makedirs(d, exist_ok=True)
        with open(_prefs_path(product), "w", encoding="utf-8") as f:
            json.dump({"enabled": bool(enabled)}, f)
    except Exception:
        pass

# Read product name + version from app.__version__ if available
try:
    from app.__version__ import __version__ as _APP_VERSION
except Exception:
    _APP_VERSION = "unknown"

# Inferito dal modulo che importa: per PE Free vs Studio passare PRODUCT a init()
_PRODUCT = "pulseedit"

# Internal state
_enabled = True   # rispettato via init(enabled=...) — opt-out
_excepthook_installed = False
_excepthook_original: Optional[Any] = None
_logging_handler_installed = False
_recent_log_sends: list = []  # timestamps for rate-limit
_LOG_RATE_LIMIT_PER_MIN = 15  # max 15 logging.ERROR forwards / minute


def _device_id() -> str:
    """Anonimo, stabile per macchina, NON usabile per re-identificare l'utente."""
    try:
        host = platform.node() or socket.gethostname() or "unknown"
    except Exception:
        host = "unknown"
    digest = hashlib.sha256(host.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:24]


def _platform_tag() -> str:
    sys_name = platform.system() or "?"
    if sys_name == "Darwin":
        sys_name = "macOS"
    rel = (platform.release() or "").split(".")[0]
    arch = platform.machine() or ""
    return "-".join(p for p in (sys_name, rel, arch) if p)[:32]


_HOME_PATH_RE = re.compile(
    r"(/Users/[^/\s]+|/home/[^/\s]+|C:\\Users\\[^\\\s]+|/private/var/folders/[^/\s]+/[^/\s]+)",
    re.IGNORECASE,
)


def _sanitize_stack(text: str) -> str:
    """Sostituisce path home/temp con `<user>` per privacy."""
    if not text:
        return ""
    return _HOME_PATH_RE.sub("<user>", text)[:6000]


def init(product: str = "pulseedit", enabled: bool = True, install_excepthook: bool = True) -> None:
    """Inizializza la telemetria.

    Args:
      product: identifier prodotto ("pulseedit" Studio o "pulseedit-free")
      enabled: opt-out (False = telemetria disabilitata da user settings)
      install_excepthook: True per catturare automaticamente le exception non gestite
    """
    global _PRODUCT, _enabled, _excepthook_installed, _excepthook_original
    _PRODUCT = product
    _enabled = bool(enabled)
    if install_excepthook and not _excepthook_installed:
        _excepthook_original = sys.excepthook

        def _hook(exc_type, exc_value, tb):
            try:
                stack_str = "".join(traceback.format_exception(exc_type, exc_value, tb))
                report_event(
                    "crash",
                    {
                        "message": str(exc_value)[:500],
                        "exc_type": str(exc_type.__name__) if exc_type else "Exception",
                        "stack": _sanitize_stack(stack_str),
                    },
                )
            except Exception:
                pass
            # Forward to original handler so the app behaves identically
            if _excepthook_original:
                try:
                    _excepthook_original(exc_type, exc_value, tb)
                except Exception:
                    pass

        sys.excepthook = _hook

        # Anche Tkinter swallow exceptions nei callback: hook anche quelle.
        # customtkinter usa Tk sottostante; sovrascriviamo Tk.report_callback_exception.
        try:
            import tkinter as _tk

            def _tk_hook(self, exc_type, exc_value, tb):
                try:
                    stack_str = "".join(traceback.format_exception(exc_type, exc_value, tb))
                    report_event(
                        "crash",
                        {
                            "message": str(exc_value)[:500],
                            "exc_type": str(exc_type.__name__) if exc_type else "Exception",
                            "stack": _sanitize_stack(stack_str),
                            "context": "tk_callback",
                        },
                    )
                except Exception:
                    pass
                # Default: print to stderr (preserves user-visible behavior)
                try:
                    traceback.print_exception(exc_type, exc_value, tb)
                except Exception:
                    pass

            _tk.Tk.report_callback_exception = _tk_hook
        except Exception:
            pass

        # Threading.Thread non chiama sys.excepthook by default; usa threading.excepthook (Python 3.8+).
        try:
            _thread_excepthook_original = threading.excepthook

            def _thread_hook(args):
                try:
                    stack_str = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
                    report_event(
                        "crash",
                        {
                            "message": str(args.exc_value)[:500],
                            "exc_type": str(args.exc_type.__name__) if args.exc_type else "Exception",
                            "stack": _sanitize_stack(stack_str),
                            "context": "background_thread",
                        },
                    )
                except Exception:
                    pass
                if _thread_excepthook_original:
                    try:
                        _thread_excepthook_original(args)
                    except Exception:
                        pass

            threading.excepthook = _thread_hook
        except Exception:
            pass

        _excepthook_installed = True

    # Logging-level capture: ogni logger.error/exception/critical dell'app diventa
    # automaticamente un workflow_fail event. Cattura quasi tutti gli errori
    # interni anche quando il codice ha già un try/except che li "swallow".
    _install_logging_handler()


def set_enabled(enabled: bool) -> None:
    """Cambia opt-out a runtime (es. quando l'utente toggla in Settings)."""
    global _enabled
    _enabled = bool(enabled)


class _TelemetryLoggingHandler(logging.Handler):
    """Forwarda ogni log record di livello >=ERROR come workflow_fail event.

    Filtro: solo logger del package "app" (no librerie di terzi). Rate-limit a
    15 errori / 60s per device per evitare spam loops.
    """
    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record):
        try:
            # Filtra: solo i nostri logger (logger name starts with 'app' o nostro modulo)
            logger_name = (record.name or '').lower()
            if not (logger_name.startswith('app') or logger_name == 'root' or logger_name == '__main__'):
                return
            # Rate-limit
            now = time.time()
            global _recent_log_sends
            _recent_log_sends = [t for t in _recent_log_sends if now - t < 60]
            if len(_recent_log_sends) >= _LOG_RATE_LIMIT_PER_MIN:
                return
            _recent_log_sends.append(now)

            # Build payload
            msg = self.format(record) if not record.exc_info else ''
            try:
                base_msg = record.getMessage()
            except Exception:
                base_msg = str(record.msg)[:300]
            stack = ''
            if record.exc_info:
                try:
                    stack = ''.join(traceback.format_exception(*record.exc_info))
                except Exception:
                    pass
            meta = {
                'logger': record.name[:64],
                'level': record.levelname,
                'message': str(base_msg)[:500],
            }
            if stack:
                meta['stack'] = _sanitize_stack(stack)
            report_event('workflow_fail', meta)
        except Exception:
            # MAI propagare exception da un logging handler
            pass


def _install_logging_handler():
    global _logging_handler_installed
    if _logging_handler_installed:
        return
    try:
        root = logging.getLogger()
        root.addHandler(_TelemetryLoggingHandler())
        _logging_handler_installed = True
    except Exception:
        pass


def report_event(event: str, meta: Optional[dict] = None) -> None:
    """Manda un evento al server. Non blocca, errori silenziosi."""
    if not _enabled:
        return
    payload = {
        "device_id": _device_id(),
        "product": _PRODUCT,
        "version": _APP_VERSION,
        "platform": _platform_tag(),
        "event": event,
    }
    if meta:
        payload["meta"] = meta
    threading.Thread(target=_post_payload, args=(payload,), daemon=True).start()


def _post_payload(payload: dict) -> None:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": f"PulseEdit/{_APP_VERSION}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=REQ_TIMEOUT_SECS, context=_SSL_CTX) as resp:
            resp.read()
    except Exception:
        # Errore di rete o server — silenzioso. Non blocchiamo mai l'app.
        pass
