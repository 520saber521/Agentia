from __future__ import annotations

import base64
import hashlib
import hmac
import os
from itertools import cycle

_SECRET_ENV = "AGENTHUB_KEY_SECRET"
_PREFIX = "enc:v1:"
_DEFAULT_SECRET = "agenthub-local-dev-secret"


def _secret() -> bytes:
    value = os.getenv(_SECRET_ENV) or _DEFAULT_SECRET
    return hashlib.sha256(value.encode("utf-8")).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key_byte for byte, key_byte in zip(data, cycle(key)))


def encrypt_secret(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    nonce = os.urandom(16)
    key = hmac.new(_secret(), nonce, hashlib.sha256).digest()
    cipher = _xor(raw.encode("utf-8"), key)
    payload = base64.urlsafe_b64encode(nonce + cipher).decode("ascii")
    return f"{_PREFIX}{payload}"


def decrypt_secret(value: str | None) -> str:
    raw = value or ""
    if not raw:
        return ""
    if not raw.startswith(_PREFIX):
        return raw
    try:
        data = base64.urlsafe_b64decode(raw[len(_PREFIX):].encode("ascii"))
        nonce, cipher = data[:16], data[16:]
        key = hmac.new(_secret(), nonce, hashlib.sha256).digest()
        return _xor(cipher, key).decode("utf-8")
    except Exception:
        return ""


def mask_secret(value: str | None) -> str:
    plain = decrypt_secret(value)
    if not plain:
        return ""
    if len(plain) <= 8:
        return "••••"
    return f"{plain[:4]}••••{plain[-4:]}"
