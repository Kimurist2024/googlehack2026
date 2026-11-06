"""認証。既定では何も通さず、設定がないときは拒否する。

鍵は SESSION_SECRET から用途ごとに導出する（HKDF, RFC 5869）。
1つの用途の値が漏れても、別の用途の鍵としては使えない。
"""
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time

from fastapi import Header, HTTPException, Request

from . import audit

logger = logging.getLogger(__name__)
SESSION_LIFETIME_SEC = 2 * 60 * 60
TOKEN_VERSION = 1
TOKEN_TYPE = "student"
MAX_TOKEN_CHARS = 1024
DEV_TEACHER_PATTERN = r"^[A-Za-z0-9._@+-]{1,64}$"

# 用途ごとの鍵の名前。値を変えると、その用途で作った保存済みの値がすべて使えなくなる
PURPOSE_TOKEN = "student-token-v1"
PURPOSE_CODE = "code-hash-v1"
PURPOSE_CLIENT = "client-key-v1"

_firebase_lock = threading.Lock()


def is_local() -> bool:
    return os.environ.get("APP_ENV") == "local"


def _master_secret() -> bytes:
    value = os.environ.get("SESSION_SECRET", "")
    if len(value) < 32:
        raise HTTPException(status_code=503, detail="SESSION_SECRET が設定されていません")
    return value.encode("utf-8")


def derive_key(purpose: str) -> bytes:
    """HKDF-SHA256 で用途ごとの32バイトの鍵を作る。"""
    pseudo_random_key = hmac.new(b"mushitori-hkdf-salt", _master_secret(), hashlib.sha256).digest()
    return hmac.new(pseudo_random_key, purpose.encode("utf-8") + b"\x01", hashlib.sha256).digest()


def keyed_hash(purpose: str, value: str) -> str:
    return hmac.new(derive_key(purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()


def code_hash(code: str) -> str:
    return keyed_hash(PURPOSE_CODE, code.strip().upper())


def new_code(length: int = 8) -> str:
    # 読み間違えやすい文字は使わない
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64encode(hmac.new(derive_key(PURPOSE_TOKEN), body.encode("ascii"), hashlib.sha256).digest())


def issue_student_token(class_id: str, student_id: str) -> str:
    issued = int(time.time())
    claims = {"v": TOKEN_VERSION, "typ": TOKEN_TYPE, "class": class_id, "student": student_id, "iat": issued, "exp": issued + SESSION_LIFETIME_SEC}
    body = _b64encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def read_student_token(token: str) -> dict:
    """署名、形、期限をすべて確かめる。どこかが違えば理由を区別せず 401 にする。"""
    rejected = HTTPException(status_code=401, detail="認証が必要です")
    if len(token) > MAX_TOKEN_CHARS or not token.isascii():
        raise rejected
    try:
        body, signature = token.split(".")
        # 署名を確かめてから中身を読む。署名のない入力を JSON として解釈しない
        if not hmac.compare_digest(signature.encode("ascii"), _sign(body).encode("ascii")):
            raise rejected
        claims = json.loads(_b64decode(body))
    except (ValueError, binascii.Error, UnicodeError):
        raise rejected from None
    if not isinstance(claims, dict) or claims.get("v") != TOKEN_VERSION or claims.get("typ") != TOKEN_TYPE:
        raise rejected
    if not isinstance(claims.get("class"), str) or not isinstance(claims.get("student"), str):
        raise rejected
    expires = claims.get("exp")
    if not isinstance(expires, int) or isinstance(expires, bool) or expires < time.time():
        raise HTTPException(status_code=401, detail="入室の期限が切れました")
    return claims


def current_student(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証が必要です")
    return read_student_token(authorization[len("Bearer "):])


def _firebase_app():
    """Firebase Admin は1回だけ初期化する。ID トークンの検証にはプロジェクトIDが必要になる。"""
    import firebase_admin

    with _firebase_lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            project = os.environ.get("GOOGLE_CLOUD_PROJECT")
            return firebase_admin.initialize_app(options={"projectId": project} if project else None)


def verify_firebase_token(token: str) -> dict:
    """署名、発行元、期限に加え、失効と無効化も確かめる（check_revoked）。"""
    from firebase_admin import auth as firebase_auth

    return firebase_auth.verify_id_token(token, app=_firebase_app(), check_revoked=True)


def current_teacher(request: Request, authorization: str = Header(default=""), x_dev_teacher: str = Header(default="")) -> str:
    """教員を確かめる。ローカル開発のときだけ、ヘッダーでの指定を認める。"""
    if is_local() and x_dev_teacher:
        if not re.fullmatch(DEV_TEACHER_PATTERN, x_dev_teacher):
            raise HTTPException(status_code=400, detail="X-Dev-Teacher の形が正しくありません")
        return x_dev_teacher
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="教員の認証が必要です")
    try:
        decoded = verify_firebase_token(authorization[len("Bearer "):])
    except Exception as error:
        # 理由は記録にだけ残し、応答では区別しない
        audit.event("teacher.auth_failed", request, severity="WARNING", reason=type(error).__name__)
        raise HTTPException(status_code=401, detail="教員の認証に失敗しました") from None
    allowed = {item.strip().lower() for item in os.environ.get("TEACHER_EMAILS", "").split(",") if item.strip()}
    email = str(decoded.get("email", "")).lower()
    if not decoded.get("email_verified") or email not in allowed:
        audit.event("teacher.not_allowed", request, severity="WARNING", principal=email)
        raise HTTPException(status_code=403, detail="このアカウントは利用できません")
    return email
