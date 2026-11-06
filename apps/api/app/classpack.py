"""授業パッケージ。授業前にクラウドで作り、ネットが落ちても教員PCで授業を続けるために持ち出す。

中身は1つの課題の授業に要るものだけ：名簿、生徒ごとの問いと正解、コードの照合値。
授業中に要るのは採点と順番の計算だけなので、コードの実行も AI もいらない。

守り方
- 署名：クラウドが ECDSA P-256 で署名し、教員PCは公開鍵で確かめてから使う。改ざんや偽のパッケージを拒む。
  本番の鍵は Cloud KMS に置き、秘密鍵はアプリの外に出さない
- 暗号化：AES-256-GCM。鍵は取り出すたびに作る「解除コード」から導き、ファイルには入れない
- 照合値：コードは scrypt（クラスごとの塩）でしか持たない。ファイルが漏れても総当たりに年単位かかる
- 期限：課題の保存期間か発行から7日の早いほう。過ぎたものは教員PCが受け付けない
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

FORMAT = "mushitori-class-package-v1"
SEAL_PREFIX = "MUSHITORI-PACK-1."
MAX_LIFETIME_SEC = 7 * 24 * 60 * 60
UNLOCK_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
UNLOCK_GROUPS = 5
UNLOCK_GROUP_LENGTH = 5
# 照合値の計算の重さ。1回およそ数十ミリ秒、メモリ16MB。総当たりを現実的でなくする
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class PackageError(ValueError):
    """パッケージが使えない。理由は教員に見せてよい言葉で書く。"""


# --- コードの照合値 ---------------------------------------------------------


def _stretch(code: str, salt: bytes) -> str:
    return hashlib.scrypt(code.strip().upper().encode("utf-8"), salt=salt, maxmem=64 * 1024 * 1024, **SCRYPT).hex()


def make_verifiers(class_code: str, personal_codes: dict[str, str]) -> dict:
    """クラスを作るときに1回だけ計算する。personal_codes は生徒ID→個人コード。"""
    salt = secrets.token_bytes(16)
    return {
        "salt": salt.hex(),
        "class_code": _stretch(class_code, salt),
        # クラスで塩が共通なので、入室のたびに scrypt を1回計算すれば誰かが分かる
        "students": {_stretch(code, salt): student_id for student_id, code in personal_codes.items()},
    }


def match_class_code(verifiers: dict, class_code: str) -> bool:
    return hmac.compare_digest(_stretch(class_code, bytes.fromhex(verifiers["salt"])), verifiers["class_code"])


def match_student(verifiers: dict, personal_code: str) -> str | None:
    stretched = _stretch(personal_code, bytes.fromhex(verifiers["salt"]))
    found = None
    for verifier, student_id in verifiers["students"].items():
        if hmac.compare_digest(stretched, verifier):
            found = student_id
    return found


# --- 署名 -------------------------------------------------------------------


class Signer(Protocol):
    key_id: str

    def sign(self, digest: bytes) -> bytes:
        """SHA-256 のダイジェストに ECDSA P-256 で署名し、DER で返す。"""

    def public_key_pem(self) -> str: ...


class LocalSigner:
    """鍵ファイル（Secret Manager から渡す PEM）か、手元の開発用にその場で作った鍵で署名する。"""

    def __init__(self, private_key_pem: str | None = None) -> None:
        if private_key_pem:
            key = serialization.load_pem_private_key(private_key_pem.encode("ascii"), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
                raise ValueError("PACKAGE_SIGNING_KEY は EC P-256 の秘密鍵にしてください")
            self._key = key
        else:
            self._key = ec.generate_private_key(ec.SECP256R1())
        self.key_id = "local:" + hashlib.sha256(self.public_key_pem().encode("ascii")).hexdigest()[:16]

    def sign(self, digest: bytes) -> bytes:
        return self._key.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))

    def public_key_pem(self) -> str:
        return self._key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


class KmsSigner:
    """Cloud KMS の非対称鍵（EC_SIGN_P256_SHA256）で署名する。秘密鍵は KMS の外に出ない。

    通信の途中で壊れていないことを、Google の推奨どおり CRC32C で確かめる。
    """

    def __init__(self, key_version: str, client=None) -> None:
        if client is None:
            from google.cloud import kms

            client = kms.KeyManagementServiceClient()
        self._client = client
        self._name = key_version
        self.key_id = "kms:" + key_version
        self._public_pem: str | None = None

    def sign(self, digest: bytes) -> bytes:
        import google_crc32c

        response = self._client.asymmetric_sign(
            request={"name": self._name, "digest": {"sha256": digest}, "digest_crc32c": google_crc32c.value(digest)}
        )
        if not response.verified_digest_crc32c or response.name != self._name:
            raise RuntimeError("Cloud KMS がダイジェストを正しく受け取れませんでした")
        if google_crc32c.value(response.signature) != int(response.signature_crc32c):
            raise RuntimeError("Cloud KMS からの署名が途中で壊れました")
        return response.signature

    def public_key_pem(self) -> str:
        if self._public_pem is None:
            import google_crc32c

            response = self._client.get_public_key(request={"name": self._name})
            if google_crc32c.value(response.pem.encode("ascii")) != int(response.pem_crc32c):
                raise RuntimeError("Cloud KMS からの公開鍵が途中で壊れました")
            self._public_pem = response.pem
        return self._public_pem


_dev_signer: LocalSigner | None = None


def default_signer() -> Signer | None:
    """本番は Cloud KMS か鍵ファイル。どちらもなく、手元の開発でもなければ None（パッケージは作らない）。"""
    global _dev_signer
    kms_key = os.environ.get("PACKAGE_SIGNING_KMS_KEY", "").strip()
    if kms_key:
        return KmsSigner(kms_key)
    pem = os.environ.get("PACKAGE_SIGNING_KEY", "").strip()
    if pem:
        return LocalSigner(pem)
    if os.environ.get("APP_ENV") == "local":
        _dev_signer = _dev_signer or LocalSigner()
        return _dev_signer
    return None


def verify(public_key_pem: str, payload: bytes, signature: bytes) -> bool:
    key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        return False
    try:
        key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


# --- 封をする・開ける --------------------------------------------------------


def new_unlock_code() -> str:
    groups = ["".join(secrets.choice(UNLOCK_ALPHABET) for _ in range(UNLOCK_GROUP_LENGTH)) for _ in range(UNLOCK_GROUPS)]
    return "-".join(groups)


def _key_from_unlock(unlock_code: str) -> bytes:
    normalized = "".join(character for character in unlock_code.upper() if character in UNLOCK_ALPHABET)
    if len(normalized) != UNLOCK_GROUPS * UNLOCK_GROUP_LENGTH:
        raise PackageError("解除コードの形が正しくありません")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"mushitori-pack-v1").derive(normalized.encode("ascii"))


def seal(payload: dict, signer: Signer) -> tuple[str, str]:
    """署名してから暗号化する。封をした文字列と、解除コードを返す。解除コードはどこにも保存しない。"""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = signer.sign(hashlib.sha256(body).digest())
    signed = json.dumps(
        {"payload": base64.b64encode(body).decode("ascii"), "sig": base64.b64encode(signature).decode("ascii"), "key_id": signer.key_id}
    ).encode("utf-8")
    unlock_code = new_unlock_code()
    nonce = secrets.token_bytes(12)
    sealed = nonce + AESGCM(_key_from_unlock(unlock_code)).encrypt(nonce, signed, SEAL_PREFIX.encode("ascii"))
    return SEAL_PREFIX + base64.urlsafe_b64encode(sealed).decode("ascii"), unlock_code


def open_sealed(sealed: str, unlock_code: str, public_key_pem: str, now: float | None = None) -> dict:
    """復号し、署名、形式、期限を確かめる。どれかが違えば PackageError。"""
    if not sealed.startswith(SEAL_PREFIX):
        raise PackageError("授業パッケージのファイルではありません")
    try:
        raw = base64.urlsafe_b64decode(sealed[len(SEAL_PREFIX):].strip())
        signed = json.loads(AESGCM(_key_from_unlock(unlock_code)).decrypt(raw[:12], raw[12:], SEAL_PREFIX.encode("ascii")))
        body = base64.b64decode(signed["payload"])
        signature = base64.b64decode(signed["sig"])
    except PackageError:
        raise
    except Exception:
        # 解除コードの誤りとファイルの破損は区別しない
        raise PackageError("解除コードが違うか、ファイルが壊れています") from None
    if not verify(public_key_pem, body, signature):
        raise PackageError("署名を確かめられません。このサービスが作ったパッケージではありません")
    payload = json.loads(body)
    if payload.get("format") != FORMAT:
        raise PackageError("対応していない形式のパッケージです")
    if (now if now is not None else time.time()) > payload["not_after"]:
        raise PackageError("パッケージの期限が切れています。クラウドで作り直してください")
    return payload


def build_payload(store, assignment, now: float) -> dict:
    """1つの課題の授業に要るものだけを集める。提出コードの原本や実行の記録の全体は入れない。"""
    classroom = store.get_class(assignment.class_id)
    verifiers = store.offline_verifiers(assignment.class_id)
    if verifiers is None:
        raise PackageError("このクラスはオフラインの授業に対応していません。クラスを作り直してください")
    statuses = store.submission_statuses(assignment.id)
    quizzes, answer_keys = {}, {}
    for student_id in classroom.student_numbers:
        quiz = store.get_quiz(assignment.id, student_id)
        key = store.get_answer_key(assignment.id, student_id)
        if quiz is not None and key is not None:
            quizzes[student_id] = {name: quiz[name] for name in ("questions", "code", "stdin")}
            answer_keys[student_id] = {name: key[name] for name in ("questions", "trace")}
    expire_at = assignment.expire_at or now + MAX_LIFETIME_SEC
    return {
        "format": FORMAT,
        "package_id": secrets.token_hex(8),
        "issued_at": now,
        "not_after": min(expire_at, now + MAX_LIFETIME_SEC),
        "assignment": {
            "id": assignment.id,
            "title": assignment.title,
            "time_limit_sec": assignment.time_limit_sec,
            "question_count": assignment.question_count,
            "weights": assignment.weights,
            "expire_at": assignment.expire_at,
        },
        "class": {"id": classroom.id, "name": classroom.name, "student_numbers": classroom.student_numbers},
        "verifiers": verifiers,
        "statuses": {sid: {"status": item.get("status"), "reason": item.get("reason")} for sid, item in statuses.items()},
        "quizzes": quizzes,
        "answer_keys": answer_keys,
    }
