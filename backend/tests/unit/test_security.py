"""Unit tests for security module."""

import os
import time
from app.security import (
    create_captcha, create_token, decode_token, hash_password,
    verify_captcha, verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "test-password-123"
        encoded = hash_password(pw)
        assert encoded.startswith("pbkdf2_sha256$210000$")
        assert verify_password(pw, encoded)

    def test_verify_wrong_password(self):
        encoded = hash_password("correct")
        assert not verify_password("wrong", encoded)

    def test_verify_empty(self):
        assert not verify_password("anything", "")

    def test_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salts
        assert verify_password("same", h1)
        assert verify_password("same", h2)


class TestJWT:
    def test_create_and_decode(self):
        token = create_token(42, "ADMIN")
        assert token.count(".") == 2
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == 42
        assert payload["role"] == "ADMIN"

    def test_decode_invalid_token(self):
        assert decode_token("bad.token.here") is None
        assert decode_token("a.b") is None
        assert decode_token("") is None

    def test_decode_tampered(self):
        token = create_token(1, "STUDENT")
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1] + ".tampered"
        assert decode_token(tampered) is None

    def test_tokens_are_valid(self):
        t1 = create_token(1, "ADMIN")
        t2 = create_token(1, "ADMIN")
        assert decode_token(t1) is not None
        assert decode_token(t2) is not None


class TestCaptcha:
    def test_signed_captcha_is_single_use(self):
        challenge = create_captcha()
        left, right = [int(value.strip()) for value in challenge["question"].split("=")[0].split("+")]
        answer = str(left + right)
        assert verify_captcha(challenge["captcha_token"], answer)
        assert not verify_captcha(challenge["captcha_token"], answer)

    def test_wrong_captcha_answer_is_rejected(self):
        challenge = create_captcha()
        assert not verify_captcha(challenge["captcha_token"], "999")
