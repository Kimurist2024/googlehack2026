"""認証。既定では何も通さず、設定がないときは拒否する。"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Header, HTTPException

SESSION_LIFETIME_SEC = 2 * 60 * 60


def is_local() -> bool:
    return os.environ.get("APP_ENV") == "local"


def _secret() -> bytes:
    value = os.environ.get("SESSION_SECRET", "")
    if len(value) < 32:
        raise HTTPException(status_code=503, detail="SESSION_SECRET が設定されていません")
    return value.encode("utf-8")


def code_hash(code: str) -> str:
    return hmac.new(_secret(), code.strip().upper().encode("utf-8"), hashlib.sha256).hexdigest()


def new_code(length: int = 8) -> str:
    # 読み間違えやすい文字は使わない
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def issue_student_token(class_id: str, student_id: str) -> str:
    claims = {"class": class_id, "student": student_id, "exp": int(time.time()) + SESSION_LIFETIME_SEC}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii")
    signature = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def read_student_token(token: str) -> dict:
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="認証が必要です") from None
    expected = hmac.new(_secret(), body.encode("ascii", "ignore"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="認証が必要です")
    claims = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    if claims.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="入室の期限が切れました")
    return claims


def current_student(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証が必要です")
    return read_student_token(authorization[len("Bearer "):])


def current_teacher(authorization: str = Header(default=""), x_dev_teacher: str = Header(default="")) -> str:
    """教員を確かめる。ローカル開発のときだけ、ヘッダーでの指定を認める。"""
    if is_local() and x_dev_teacher:
        return x_dev_teacher
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="教員の認証が必要です")
    try:
        from firebase_admin import auth as firebase_auth

        decoded = firebase_auth.verify_id_token(authorization[len("Bearer "):])
    except Exception:
        raise HTTPException(status_code=401, detail="教員の認証に失敗しました") from None
    allowed = {item.strip().lower() for item in os.environ.get("TEACHER_EMAILS", "").split(",") if item.strip()}
    email = str(decoded.get("email", "")).lower()
    if not decoded.get("email_verified") or email not in allowed:
        raise HTTPException(status_code=403, detail="このアカウントは利用できません")
    return email
