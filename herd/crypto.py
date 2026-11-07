"""Keys, recovery codes and authenticated encryption.

Design notes
------------
* One random 32-byte key per *store*, never derived from a password the user
  types. It is printed once as a recovery code and can be copied to another
  machine by `hermes sync join`.
* scrypt turns the recovery code into the key material, so a store file that
  leaks is useless without the code (2**15 iterations, 32 MB).
* AES-256-GCM with a store id as associated data: a blob lifted from one store
  into another fails to authenticate instead of decrypting into garbage.
* Object names are keyed hashes (HMAC), so the store cannot even be probed by
  hashing guesses at a known secret.
"""

from __future__ import annotations

import base64
import hmac
import os
import secrets
import string

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"HDR1"
CODE_PREFIX = "HERD-"
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"  # RFC 4648 base32
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1


class BadCode(ValueError):
    """The recovery code does not open this store."""


class TamperedBlob(ValueError):
    """A blob did not authenticate: corrupted, truncated, or from another store."""


def _b32encode(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _b32decode(text: str) -> bytes:
    cleaned = "".join(ch for ch in text.upper() if ch in _ALPHABET)
    cleaned += "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned)


def new_key() -> bytes:
    return secrets.token_bytes(32)


def format_code(key: bytes) -> str:
    body = _b32encode(key)
    groups = "-".join(body[i : i + 4] for i in range(0, len(body), 4))
    return f"{CODE_PREFIX}{groups}"


def parse_code(code: str) -> bytes:
    """Accept the pretty form, lowercase, spaces, or a bare base32 string."""
    text = (code or "").upper().replace(" ", "").replace("\n", "").strip()
    # Drop the display prefix first: H, E, R and D are all legal base32
    # characters, so filtering before the prefix would decode garbage.
    if text.startswith("HERD"):
        text = text[4:].lstrip("-")
    cleaned = "".join(ch for ch in text if ch in _ALPHABET)
    if len(cleaned) < 26:
        raise BadCode("That recovery code looks too short. Copy the whole HERD-… line.")
    try:
        raw = _b32decode(cleaned)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad code
        raise BadCode("That recovery code is not valid. Check for missing characters.") from exc
    if len(raw) < 16:
        raise BadCode("That recovery code is not valid.")
    return raw


def derive_key(code: str | bytes, salt: bytes) -> bytes:
    raw = parse_code(code) if isinstance(code, str) else code
    kdf = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(raw)


def store_check(key: bytes) -> str:
    """A value the store publishes so a wrong code fails before any write."""
    return hmac.new(key, b"herd-store-check-v1", "sha256").hexdigest()


def verify_code(key: bytes, expected: str) -> bool:
    return hmac.compare_digest(store_check(key), str(expected or ""))


def object_id(key: bytes, plaintext: bytes) -> str:
    return hmac.new(key, b"obj\x00" + plaintext, "sha256").hexdigest()


def seal(key: bytes, plaintext: bytes, store_id: str) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, store_id.encode())
    return MAGIC + nonce + ct


def open_sealed(key: bytes, blob: bytes, store_id: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 12 + 16:
        raise TamperedBlob("This file is not a Herd object.")
    nonce, ct = blob[len(MAGIC) : len(MAGIC) + 12], blob[len(MAGIC) + 12 :]
    try:
        return AESGCM(key).decrypt(nonce, ct, store_id.encode())
    except InvalidTag as exc:
        raise TamperedBlob("This object failed its integrity check.") from exc


def random_id(nbytes: int = 12) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(nbytes))
