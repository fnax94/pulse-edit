"""Validazione licenza via AB Tools License Server."""

import urllib.request
import ssl
import json
import platform
import hashlib
import certifi
from app.i18n import t

try:
    from app.__version__ import __version__ as _PE_VERSION
except Exception:
    _PE_VERSION = "unknown"

LICENSE_SERVER = "https://license-server.abtools.workers.dev"
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _get_instance_id():
    """Genera un ID univoco per questa macchina."""
    node = platform.node()
    mac_id = hashlib.sha256(node.encode()).hexdigest()[:16]
    return f"pulseedit-{mac_id}"


def _short_platform():
    """Compact platform tag for telemetry: e.g. 'macOS-14.4-arm64' or 'Windows-11'."""
    sys_name = platform.system() or "?"
    if sys_name == "Darwin":
        sys_name = "macOS"
    rel = (platform.release() or "").split(".")[0]
    arch = platform.machine() or ""
    parts = [sys_name]
    if rel: parts.append(rel)
    if arch: parts.append(arch)
    return "-".join(parts)[:32]


def verify_license(license_key):
    """Attiva e verifica la licenza. Ritorna (valid, message)."""
    key = license_key.strip()
    machine_id = _get_instance_id()

    # Try activate
    result, error = _api_call("/activate", {
        "license_key": key,
        "machine_id": machine_id,
        "expected_product": "pulseedit",
    })

    if error:
        return False, error

    if result.get("valid"):
        return True, t("license_activated")

    err = result.get("error", "")

    # Already activated on another machine
    if "another machine" in err.lower():
        return False, t("key_already_used")

    # Not found
    if "invalid" in err.lower():
        return False, t("key_not_found")

    return False, result.get("error", t("activation_failed"))


def validate_license(license_key):
    """Valida una licenza gia attivata. Ritorna (valid, message)."""
    key = license_key.strip()
    machine_id = _get_instance_id()

    result, error = _api_call("/validate", {
        "license_key": key,
        "machine_id": machine_id,
        "version": _PE_VERSION,
        "platform": _short_platform(),
    })

    if error:
        return False, error

    if result.get("valid"):
        return True, t("license_valid")

    return False, result.get("error", t("license_invalid"))


def deactivate_license(license_key):
    """Deattiva la licenza sul server, libera la macchina. Ritorna (success, message)."""
    key = license_key.strip()
    machine_id = _get_instance_id()

    result, error = _api_call("/deactivate", {
        "license_key": key,
        "machine_id": machine_id,
    })

    if error:
        return False, error

    if result.get("deactivated"):
        return True, t("license_deactivated")

    return False, result.get("error", t("deactivation_failed"))


def _api_call(endpoint, payload):
    """Chiama il license server. Ritorna (result_dict, error_string)."""
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{LICENSE_SERVER}{endpoint}",
            data=data,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "PulseEdit/1.0")

        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            return json.loads(resp.read()), None

    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except (json.JSONDecodeError, Exception):
            body = {}
        if e.code == 404:
            return {}, t("key_not_found")
        if e.code == 403:
            return {}, body.get("error", t("license_invalid"))
        return {}, t("error_generic", msg=body.get("error", str(e.code)))

    except urllib.error.URLError:
        return {}, t("offline_error")
    except Exception as e:
        return {}, t("error_generic", msg=str(e))
