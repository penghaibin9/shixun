"""Small HMAC capability helper for server-to-server delegated access.

The payload is visible to the bearer, but any edit invalidates the signature.  It
must therefore contain identifiers only and never secrets or log contents.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from hashlib import sha256
from hmac import compare_digest, new as new_hmac
import json


def _encode(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_capability(payload: dict, secret: str) -> str:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _encode(body)
    signature = new_hmac(secret.encode("utf-8"), encoded.encode("ascii"), sha256).digest()
    return f"{encoded}.{_encode(signature)}"


def verify_capability(token: str, secret: str) -> dict:
    try:
        encoded, supplied = token.split(".", 1)
        expected = new_hmac(secret.encode("utf-8"), encoded.encode("ascii"), sha256).digest()
        if not compare_digest(_decode(supplied), expected):
            raise ValueError("invalid signature")
        payload = json.loads(_decode(encoded))
    except (ValueError, TypeError, UnicodeDecodeError, Base64Error, json.JSONDecodeError) as exc:
        raise ValueError("invalid signed capability") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid signed capability payload")
    return payload
