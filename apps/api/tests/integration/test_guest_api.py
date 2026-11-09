"""体験用の教員（Firebase の匿名ログイン）の試験。app/guest.py を参照。"""
import pytest

from app import auth, guest, service

TEACHER = {"X-Dev-Teacher": "teacher-a"}


@pytest.fixture
def tokens(monkeypatch):
    """Firebase のトークン検証だけを偽物にする。匿名ログインのトークンには、メールアドレスがない。"""
    monkeypatch.setenv("ALLOW_DEMO_SEED", "1")
    monkeypatch.setenv("TEACHER_EMAILS", "teacher@example.com")
    claims = {
        "guest-a": {"uid": "AnonA1", "firebase": {"sign_in_provider": "anonymous", "identities": {}}},
        "guest-b": {"uid": "AnonB2", "firebase": {"sign_in_provider": "anonymous", "identities": {}}},
        "odd-uid": {"uid": "../x", "firebase": {"sign_in_provider": "anonymous", "identities": {}}},
        "teacher": {"email": "teacher@example.com", "email_verified": True, "firebase": {"sign_in_provider": "google.com"}},
    }

    def verify(token):
        if token not in claims:
            raise ValueError("bad token")
        return claims[token]

    monkeypatch.setattr(auth, "verify_firebase_token", verify)
    return lambda token: {"Authorization": f"Bearer {token}"}


@pytest.fixture
def open_guest(monkeypatch):
    monkeypatch.setenv("ALLOW_GUEST_TEACHER", "1")


def test_guest_is_closed_unless_the_flag_is_set(client, tokens):
    assert client.get("/v1/health").json()["guest_teacher"] is False
    assert client.get("/v1/me", headers=tokens("guest-a")).status_code == 403
    assert client.post("/v1/dev/seed", headers=tokens("guest-a")).status_code == 403


def test_guest_runs_the_demo_from_generation_to_followups(client, tokens, open_guest):
    assert client.get("/v1/health").json()["guest_teacher"] is True
    assert client.get("/v1/me", headers=tokens("guest-a")).json() == {"email": None, "guest": True}
    assert client.get("/v1/me", headers=tokens("teacher")).json() == {"email": "teacher@example.com", "guest": False}
    seeded = client.post("/v1/dev/seed", headers=tokens("guest-a"))
    assert seeded.status_code == 201
    created = seeded.json()
    assignment = created["assignment_id"]
    # 体験用のデータは、設定の日数（既定30日）によらず1日で消える
    assert created["expires_at"] - service.now() <= guest.RETENTION_SEC + 5
    assert client.post(f"/v1/assignments/{assignment}:generate", headers=tokens("guest-a")).status_code == 202
    assert client.get(f"/v1/assignments/{assignment}", headers=tokens("guest-a")).json()["state"] == "ready"
    assert client.post(f"/v1/assignments/{assignment}:open", headers=tokens("guest-a")).status_code == 200
    session = client.post("/v1/sessions", json={"class_code": created["class_code"], "personal_code": created["personal_codes"]["1"]})
    student = {"Authorization": "Bearer " + session.json()["token"]}
    quiz = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=student).json()
    answers = {question["id"]: "0" for question in quiz["questions"]}
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers}, headers=student).status_code == 200
    assert client.post(f"/v1/assignments/{assignment}:close", headers=tokens("guest-a")).status_code == 200
    assert client.get(f"/v1/assignments/{assignment}/followups", headers=tokens("guest-a")).status_code == 200


def test_guests_and_teachers_cannot_see_each_others_classes(client, tokens, open_guest):
    created = client.post("/v1/dev/seed", headers=tokens("guest-a")).json()
    assignment = created["assignment_id"]
    for other in (tokens("guest-b"), tokens("teacher"), TEACHER):
        assert client.get(f"/v1/assignments/{assignment}", headers=other).status_code == 404
        assert client.delete(f"/v1/classes/{created['class_id']}", headers=other).status_code == 404
    mine = client.post("/v1/dev/seed", headers=tokens("teacher")).json()
    assert client.get(f"/v1/assignments/{mine['assignment_id']}", headers=tokens("guest-a")).status_code == 404


def test_uid_that_cannot_be_a_document_name_is_rejected(client, tokens, open_guest):
    assert client.get("/v1/me", headers=tokens("odd-uid")).status_code == 403


def test_guest_class_size_is_limited(client, tokens, open_guest):
    numbers = [str(n) for n in range(1, guest.MAX_STUDENTS + 2)]
    too_many = client.post("/v1/classes", json={"name": "体験", "student_numbers": numbers}, headers=tokens("guest-a"))
    assert too_many.status_code == 400
    assert client.post("/v1/classes", json={"name": "体験", "student_numbers": numbers[:-1]}, headers=tokens("guest-a")).status_code == 201
    # 本物の教員には、体験用の制限はかからない
    assert client.post("/v1/classes", json={"name": "1-A", "student_numbers": numbers}, headers=tokens("teacher")).status_code == 201


def test_guest_daily_limits_count_each_guest_and_all_guests(client, tokens, open_guest, monkeypatch):
    monkeypatch.setattr(guest, "LIMITS", {"class": (2, 3), "generate": (1, 2)})
    body = {"name": "体験", "student_numbers": ["1"]}
    assert client.post("/v1/classes", json=body, headers=tokens("guest-a")).status_code == 201
    assert client.post("/v1/classes", json=body, headers=tokens("guest-a")).status_code == 201
    limited = client.post("/v1/classes", json=body, headers=tokens("guest-a"))
    assert limited.status_code == 429 and 0 < int(limited.headers["Retry-After"]) <= guest.DAY_SEC
    # ほかの人は自分の分を使えるが、全員の合計に達したら誰も作れない
    assert client.post("/v1/classes", json=body, headers=tokens("guest-b")).status_code == 201
    assert client.post("/v1/classes", json=body, headers=tokens("guest-b")).status_code == 429
    for _ in range(4):
        assert client.post("/v1/classes", json=body, headers=tokens("teacher")).status_code == 201


def test_guest_generation_has_a_daily_limit(client, tokens, open_guest, monkeypatch):
    monkeypatch.setattr(guest, "LIMITS", {"class": (10, 10), "generate": (1, 5)})
    first = client.post("/v1/dev/seed", headers=tokens("guest-a")).json()["assignment_id"]
    second = client.post("/v1/dev/seed", headers=tokens("guest-a")).json()["assignment_id"]
    assert client.post(f"/v1/assignments/{first}:generate", headers=tokens("guest-a")).status_code == 202
    assert client.post(f"/v1/assignments/{second}:generate", headers=tokens("guest-a")).status_code == 429
    assert client.get(f"/v1/assignments/{second}", headers=tokens("guest-a")).json()["state"] == "draft"
