#!/usr/bin/env python3
"""Pulse Edit — Auto video editor synced to beats for DaVinci Resolve."""

import sys
import os
import logging
import platform
import customtkinter as ctk
from app.licensing import storage, lemon
from app.gui.main_window import MainWindow
from app.gui.license_dialog import LicenseDialog

def _create_desktop_shortcut():
    if platform.system() != "Windows" or not getattr(sys, 'frozen', False):
        return
    try:
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        shortcut = os.path.join(desktop, "Pulse Edit.lnk")
        if os.path.exists(shortcut):
            return
        exe = sys.executable
        icon = os.path.join(os.path.dirname(exe), "_internal", "icon.ico")
        if not os.path.exists(icon):
            icon = exe
        import subprocess
        ps = f'''$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('{shortcut}'); $s.TargetPath = '{exe}'; $s.WorkingDirectory = '{os.path.dirname(exe)}'; $s.IconLocation = '{icon}'; $s.Save()'''
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10)
    except Exception:
        pass

_create_desktop_shortcut()

if platform.system() == "Windows":
    _log_dir = os.path.join(os.environ.get("APPDATA", ""), "PulseEdit")
else:
    _log_dir = os.path.expanduser("~/Library/Logs/PulseEdit")
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, "pulseedit.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Verify installation integrity
_required_api = ['save_license', 'load_license', 'is_trial_expired',
                 'get_trial_count', 'increment_trial', '_auth']
for _fn in _required_api:
    if not hasattr(storage, _fn):
        print("Error: corrupted installation. Please reinstall Pulse Edit.")
        sys.exit(1)


def check_license():
    """Verifica la licenza. Ritorna True se valida."""
    key = storage.load_license()
    if not key:
        return False

    if not storage.needs_revalidation():
        return True

    valid, _ = lemon.validate_license(key)
    if valid:
        storage._update_cache(key)
        return True

    if storage.is_within_offline_grace():
        return True

    return False


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    licensed = check_license()

    app = MainWindow(licensed=licensed)
    app.mainloop()


if __name__ == "__main__":
    main()
