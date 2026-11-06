"""トークンと鍵の扱いの単体テスト。"""
import base64
import json
import time

import pytest
from fastapi import HTTPException

from app import auth


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def signed(claims: object) -> str:
    """正しい鍵で署名した、中身だけがおかしいトークンを作る。"""
    body = b64(json.dumps(claims).encode("utf-8"))
    return f"{body}.{auth._sign(body)}"


def rejected(token: str) -> int:
    with pytest.raises(HTTPException) as caught:
        auth.read_student_token(token)
    return caught.value.status_code


def test_issued_token_round_trips():
    claims = auth.read_student_token(auth.issue_student_token("c" * 16, "s" * 16))
    assert (claims["class"], claims["student"], claims["typ"]) == ("c" * 16, "s" * 16, "student")


@pytest.mark.parametrize(
    "token",
    ["", "abc", "a.b.c", "!!!.???", "トークン.署名", "x" * 2000, "a." + "A" * 43],
)
def test_malformed_tokens_are_401_not_500(token):
    assert rejected(token) == 401


def test_body_cannot_be_swapped_under_a_valid_signature():
    good = auth.issue_student_token("c" * 16, "s" * 16)
    _, signature = good.split(".")
    other_body = b64(json.dumps({"v": 1, "typ": "student", "class": "x" * 16, "student": "y" * 16, "exp": 2**40}).encode())
    assert rejected(f"{other_body}.{signature}") == 401


@pytest.mark.parametrize(
    "claims",
    [
        ["not", "an", "object"],
        {"v": 1, "typ": "teacher", "class": "c", "student": "s", "exp": 2**40},
        {"v": 2, "typ": "student", "class": "c", "student": "s", "exp": 2**40},
        {"v": 1, "typ": "student", "class": 1, "student": "s", "exp": 2**40},
        {"v": 1, "typ": "student", "class": "c", "student": "s", "exp": "never"},
        {"v": 1, "typ": "student", "class": "c", "student": "s", "exp": True},
        {"v": 1, "typ": "student", "class": "c", "student": "s"},
    ],
)
def test_signed_but_wrong_shape_is_rejected(claims):
    assert rejected(signed(claims)) == 401


def test_expired_token_is_rejected():
    claims = {"v": 1, "typ": "student", "class": "c", "student": "s", "exp": int(time.time()) - 1}
    with pytest.raises(HTTPException) as caught:
        auth.read_student_token(signed(claims))
    assert caught.value.detail == "入室の期限が切れました"


def test_each_purpose_gets_its_own_key():
    keys = {auth.derive_key(purpose) for purpose in (auth.PURPOSE_TOKEN, auth.PURPOSE_CODE, auth.PURPOSE_CLIENT)}
    assert len(keys) == 3
    assert auth.derive_key(auth.PURPOSE_CODE) == auth.derive_key(auth.PURPOSE_CODE)


def test_code_hash_ignores_case_and_spaces_but_not_the_code():
    assert auth.code_hash(" abcd2345 ") == auth.code_hash("ABCD2345")
    assert auth.code_hash("ABCD2345") != auth.code_hash("ABCD2346")


def test_hashes_change_with_the_secret(monkeypatch):
    before = auth.code_hash("ABCD2345")
    monkeypatch.setenv("SESSION_SECRET", "t" * 40)
    assert auth.code_hash("ABCD2345") != before


def test_short_secret_fails_closed(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "short")
    with pytest.raises(HTTPException) as caught:
        auth.issue_student_token("c", "s")
    assert caught.value.status_code == 503
