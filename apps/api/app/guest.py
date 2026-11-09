"""体験用の教員。審査員や見学の人が、ログインせずに教員の画面を一通り試すための役。

Firebase Authentication の匿名ログインを使い、ブラウザごとに別のアカウントにする。
クラスと課題は教員ごとに分けてあるので（app/main.py の owned_class）、体験する人どうしで互いのものは見えない。
本物の教員（TEACHER_EMAILS の許可リスト）とは別の役で、次の制限を付ける。

- 1クラスの人数は MAX_STUDENTS 人まで
- クラスを作る回数と問いを作る回数に、1人あたりと全体の、1日の上限を付ける（Gemini の費用と、インスタンスの負荷を抑える）
- 課題と生徒のデータは RETENTION_SEC で消える（課題の expire_at。Firestore の TTL）

既定では閉じている。ALLOW_GUEST_TEACHER=1 のときだけ開く。
"""
import os
import re

from fastapi import HTTPException

from .fields import DAY_SEC

PREFIX = "guest:"
# Firebase の uid は英数字。保存先の文書の名前に入れるので、それ以外は通さない
UID_PATTERN = r"^[A-Za-z0-9]{1,128}$"
MAX_STUDENTS = 10
RETENTION_SEC = DAY_SEC
# 1日（UTC）の上限。(1人あたり, 体験用の全員の合計)
LIMITS = {"class": (5, 300), "generate": (10, 150)}


def enabled() -> bool:
    return os.environ.get("ALLOW_GUEST_TEACHER") == "1"


def is_anonymous(claims: dict) -> bool:
    firebase = claims.get("firebase")
    return isinstance(firebase, dict) and firebase.get("sign_in_provider") == "anonymous"


def principal(uid: str) -> str | None:
    """匿名ログインの uid から、教員の代わりに使う名前を作る。メールアドレスとは形が違うので混ざらない。"""
    return PREFIX + uid if re.fullmatch(UID_PATTERN, uid) else None


def is_guest(teacher: str) -> bool:
    return teacher.startswith(PREFIX)


def _day(now: float) -> int:
    """数える単位の日（UTC）。"""
    return int(now // DAY_SEC)


def _keys(kind: str, teacher: str, day: int) -> tuple[str, str]:
    return f"{kind}-{day}-{teacher[len(PREFIX):]}", f"{kind}-{day}"


def check(store, kind: str, teacher: str, now: float) -> None:
    """上限に達していれば 429 にする。本物の教員には何もしない。数えるのは、実際に作れたときの use()。"""
    if not is_guest(teacher):
        return
    day = _day(now)
    own_key, total_key = _keys(kind, teacher, day)
    own_limit, total_limit = LIMITS[kind]
    retry = {"Retry-After": str(int((day + 1) * DAY_SEC - now))}
    if store.usage_count(total_key) >= total_limit:
        raise HTTPException(status_code=429, detail="体験用の今日の上限に達しました。日をあらためてお試しください", headers=retry)
    if store.usage_count(own_key) >= own_limit:
        raise HTTPException(status_code=429, detail="体験用で今日使える回数を使い切りました。日をあらためてお試しください", headers=retry)


def use(store, kind: str, teacher: str, now: float) -> None:
    if not is_guest(teacher):
        return
    day = _day(now)
    # 数えた記録は、その日が終わってから1日たてば消してよい
    expire_at = (day + 2) * DAY_SEC
    for key in _keys(kind, teacher, day):
        store.add_usage(key, expire_at)
