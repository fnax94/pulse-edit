"""In-app update checker for Pulse Edit Studio.

Checks the public GitHub releases API for the latest published version and
reports whether a newer one than the running build exists. The result is used
by the GUI to show a non-blocking "update available" prompt with a download
link to the website.

Design notes:
- Network/parse errors are ALWAYS swallowed — an update check must never break
  or block the app. On any failure we simply report "no update".
- The repo `fnax94/pulse-edit` is public, so the releases API needs no token.
- Tags look like `pulse-edit-v1.5.9`; we compare the numeric (major, minor, patch).
"""

import json
import re
import ssl
import urllib.request
import logging

_log = logging.getLogger("pulseedit.updater")

_RELEASES_API = "https://api.github.com/repos/fnax94/pulse-edit/releases/latest"
DOWNLOAD_URL = "https://pulseedit.com"
_TAG_PREFIX = "pulse-edit-v"

try:
    _SSL_CTX = ssl.create_default_context()
except Exception:
    _SSL_CTX = None


def _parse_version(s):
    """'1.5.9' or 'pulse-edit-v1.5.9' -> (1, 5, 9). None if unparseable."""
    if not s:
        return None
    s = s.strip()
    if s.startswith(_TAG_PREFIX):
        s = s[len(_TAG_PREFIX):]
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", s)
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def _is_newer(latest, current):
    """True only if `latest` parses to a strictly higher version than `current`."""
    lv, cv = _parse_version(latest), _parse_version(current)
    if not lv or not cv:
        return False
    return lv > cv


def check_for_update(current_version, timeout=6):
    """Return {'latest': '1.5.9', 'url': DOWNLOAD_URL} if a newer release exists,
    otherwise None. Never raises."""
    try:
        req = urllib.request.Request(_RELEASES_API, headers={
            "User-Agent": "PulseEdit-Updater",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
        tag = data.get("tag_name", "")
        parsed = _parse_version(tag)
        if parsed and _is_newer(tag, current_version):
            return {"latest": ".".join(str(x) for x in parsed), "url": DOWNLOAD_URL}
    except Exception as e:
        _log.info(f"update check skipped: {type(e).__name__}: {e}")
    return None
