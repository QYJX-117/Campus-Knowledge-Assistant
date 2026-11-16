import os
import base64
import hashlib
import hmac
import json
import uuid
import secrets
import threading
from datetime import datetime, timedelta, timezone
from .config import settings


_used_captchas: set[str] = set()
_captcha_lock = threading.Lock()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, b64_salt, b64_digest = encoded.split("$")
        salt = base64.b64decode(b64_salt)
        expected = base64.b64decode(b64_digest)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(data: str) -> bytes:
    padding = -len(data) % 4
    return base64.urlsafe_b64decode(data.encode() + b"=" * padding)


def create_token(user_id: int, role: str) -> str:
    header = _b64_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    exp = int((datetime.now(timezone.utc) + timedelta(minutes=settings.token_minutes)).timestamp())
    payload = _b64_encode(json.dumps({"sub": user_id, "role": role, "exp": exp}).encode())
    sig_raw = hmac.digest(settings.app_secret.encode(), f"{header}.{payload}".encode(), "sha256")
    return f"{header}.{payload}.{_b64_encode(sig_raw)}"


def create_guest_token(guest_id: str | None = None) -> tuple[str, str]:
    """Create a token for guest users — no real user account in DB."""
    header = _b64_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    exp = int((datetime.now(timezone.utc) + timedelta(minutes=settings.token_minutes)).timestamp())
    guest_id = guest_id or uuid.uuid4().hex
    payload = _b64_encode(json.dumps({"sub": 0, "role": "STUDENT", "guest": True, "guest_id": guest_id, "exp": exp}).encode())
    sig_raw = hmac.digest(settings.app_secret.encode(), f"{header}.{payload}".encode(), "sha256")
    return f"{header}.{payload}.{_b64_encode(sig_raw)}", guest_id


def decode_token(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        expected = _b64_encode(hmac.digest(settings.app_secret.encode(), f"{header}.{payload}".encode(), "sha256"))
        if not hmac.compare_digest(sig.encode(), expected.encode()):
            return None
        data = json.loads(_b64_decode(payload))
        if data.get("exp", 0) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return data
    except Exception:
        return None


def create_captcha() -> dict[str, str]:
    """Create a short-lived signed challenge without exposing its answer."""
    left = secrets.randbelow(8) + 2
    right = secrets.randbelow(8) + 1
    nonce = secrets.token_urlsafe(12)
    answer_digest = hmac.new(
        settings.app_secret.encode(), f"{nonce}:{left + right}".encode(), hashlib.sha256,
    ).hexdigest()
    payload = {
        "nonce": nonce,
        "answer": answer_digest,
        "exp": int(datetime.now(timezone.utc).timestamp()) + settings.captcha_ttl_seconds,
    }
    encoded = _b64_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64_encode(hmac.digest(settings.app_secret.encode(), encoded.encode(), "sha256"))
    return {"captcha_token": f"{encoded}.{signature}", "question": f"{left} + {right} = ?"}


def verify_captcha(token: str, answer: str) -> bool:
    try:
        encoded, signature = token.split(".", 1)
        expected_signature = _b64_encode(hmac.digest(settings.app_secret.encode(), encoded.encode(), "sha256"))
        if not hmac.compare_digest(signature, expected_signature):
            return False
        payload = json.loads(_b64_decode(encoded))
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            return False
        nonce = str(payload.get("nonce", ""))
        answer_digest = hmac.new(
            settings.app_secret.encode(), f"{nonce}:{answer.strip()}".encode(), hashlib.sha256,
        ).hexdigest()
        if not nonce or not hmac.compare_digest(answer_digest, str(payload.get("answer", ""))):
            return False
        with _captcha_lock:
            if nonce in _used_captchas:
                return False
            _used_captchas.add(nonce)
            if len(_used_captchas) > 10_000:
                _used_captchas.clear()
        return True
    except Exception:
        return False
