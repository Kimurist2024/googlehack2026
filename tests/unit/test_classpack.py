"""授業パッケージの署名・暗号化と、コードの照合値の単体テスト。"""
import json
import time
from types import SimpleNamespace

import google_crc32c
import pytest

from app import classpack
from app.classpack import KmsSigner, LocalSigner, PackageError


def payload(not_after=None):
    return {"format": classpack.FORMAT, "not_after": not_after or time.time() + 3600, "quizzes": {"s": {"code": "x = 1"}}}


def test_sealed_package_round_trips():
    signer = LocalSigner()
    sealed, unlock = classpack.seal(payload(), signer)
    assert sealed.startswith(classpack.SEAL_PREFIX)
    assert classpack.open_sealed(sealed, unlock, signer.public_key_pem())["quizzes"] == {"s": {"code": "x = 1"}}


def test_contents_are_not_readable_without_the_unlock_code():
    sealed, _ = classpack.seal(payload(), LocalSigner())
    assert "x = 1" not in sealed
    with pytest.raises(PackageError):
        classpack.open_sealed(sealed, classpack.new_unlock_code(), LocalSigner().public_key_pem())


def test_unlock_code_ignores_case_and_separators():
    signer = LocalSigner()
    sealed, unlock = classpack.seal(payload(), signer)
    assert classpack.open_sealed(sealed, unlock.lower().replace("-", " "), signer.public_key_pem())


def test_package_from_another_key_is_rejected():
    sealed, unlock = classpack.seal(payload(), LocalSigner())
    with pytest.raises(PackageError, match="署名"):
        classpack.open_sealed(sealed, unlock, LocalSigner().public_key_pem())


def test_tampered_ciphertext_is_rejected():
    signer = LocalSigner()
    sealed, unlock = classpack.seal(payload(), signer)
    tampered = sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:]
    with pytest.raises(PackageError):
        classpack.open_sealed(tampered, unlock, signer.public_key_pem())


def test_expired_package_is_rejected():
    signer = LocalSigner()
    sealed, unlock = classpack.seal(payload(not_after=time.time() - 1), signer)
    with pytest.raises(PackageError, match="期限"):
        classpack.open_sealed(sealed, unlock, signer.public_key_pem())


@pytest.mark.parametrize("text", ["", "PK\x03\x04", classpack.SEAL_PREFIX + "!!!"])
def test_garbage_is_a_package_error(text):
    with pytest.raises(PackageError):
        classpack.open_sealed(text, classpack.new_unlock_code(), LocalSigner().public_key_pem())


def test_verifiers_match_only_the_right_codes():
    verifiers = classpack.make_verifiers("CLASS234", {"s1": "AAAA2345", "s2": "BBBB2345"})
    assert "CLASS234" not in json.dumps(verifiers) and "AAAA2345" not in json.dumps(verifiers)
    assert classpack.match_class_code(verifiers, " class234 ")
    assert not classpack.match_class_code(verifiers, "CLASS235")
    assert classpack.match_student(verifiers, "bbbb2345") == "s2"
    assert classpack.match_student(verifiers, "CCCC2345") is None


def test_each_class_gets_its_own_salt():
    first = classpack.make_verifiers("CLASS234", {"s": "AAAA2345"})
    second = classpack.make_verifiers("CLASS234", {"s": "AAAA2345"})
    assert first["salt"] != second["salt"] and first["class_code"] != second["class_code"]


class FakeKms:
    """Cloud KMS の代わり。本物の鍵の代わりに手元の鍵で署名し、CRC32C も本物と同じ形で返す。"""

    def __init__(self, corrupt=False):
        self.local = LocalSigner()
        self.corrupt = corrupt
        self.requests = []

    def asymmetric_sign(self, request):
        self.requests.append(request)
        signature = self.local.sign(request["digest"]["sha256"])
        crc = google_crc32c.value(signature) + (1 if self.corrupt else 0)
        return SimpleNamespace(signature=signature, signature_crc32c=crc, verified_digest_crc32c=True, name=request["name"])

    def get_public_key(self, request):
        pem = self.local.public_key_pem()
        return SimpleNamespace(pem=pem, pem_crc32c=google_crc32c.value(pem.encode("ascii")))


KEY = "projects/p/locations/asia-northeast1/keyRings/r/cryptoKeys/package/cryptoKeyVersions/1"


def test_kms_signer_signs_a_digest_and_checks_integrity():
    kms = FakeKms()
    signer = KmsSigner(KEY, client=kms)
    sealed, unlock = classpack.seal(payload(), signer)
    assert classpack.open_sealed(sealed, unlock, signer.public_key_pem())
    request = kms.requests[0]
    assert request["name"] == KEY and len(request["digest"]["sha256"]) == 32 and "digest_crc32c" in request


def test_corrupted_kms_signature_is_not_used():
    with pytest.raises(RuntimeError):
        classpack.seal(payload(), KmsSigner(KEY, client=FakeKms(corrupt=True)))


def test_production_without_a_key_makes_no_packages(monkeypatch):
    for name in ("PACKAGE_SIGNING_KMS_KEY", "PACKAGE_SIGNING_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert classpack.default_signer() is None
