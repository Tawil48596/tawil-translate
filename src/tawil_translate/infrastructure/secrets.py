from __future__ import annotations

import os

_SERVICE = "Tawil Translate"


def get_api_key(environment_name: str) -> str:
    value = os.environ.get(environment_name, "")
    if value:
        return value
    try:
        import keyring

        return keyring.get_password(_SERVICE, environment_name) or ""
    except (ImportError, RuntimeError):
        return ""


def set_api_key(environment_name: str, value: str) -> None:
    if not value:
        return
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("keyring is required to securely store the API key") from exc
    keyring.set_password(_SERVICE, environment_name, value)
