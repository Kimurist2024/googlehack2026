"""生徒のデータの保存期間と削除の試験。期限後と削除後に、どの入口からも読めないことを確かめる。"""
import json
import time
from datetime import datetime

import pytest

from app import service
from app.main import DEFAULT_RETENTION_DAYS, MAX_RETENTION_DAYS
from app.store import MemoryStore
from tests.integration.test_api import TEACHER, login, setup_open

DAY = 24 * 60 * 60
OTHER_TEACHER = {"X-Dev-Teacher": "teacher-b"}


def student_data_is_gone(store, assignment_id: str) -> bool:
    if isinstance(store, MemoryStore):
        tables = (store._submissions, store._quizzes, store._answer_keys, store._attempts, store._followups)
        return assignment_id not in store._assignments and all(assignment_id not in table for table in tables)
    reference = store._assignment(assignment_id)
    return not reference.get().exists and not any(True for _ in reference.collections())


def audit_events(output: str) -> list[str]:
    events = []
    for line in output.splitlines():
        try:
            events.append(json.loads(line)["audit"]["event"])
        except (ValueError, KeyError, TypeError):
            continue
    return events


def test_new_assignment_expires_after_the_default_retention(client):
    before = time.time()
    _, assignment = setup_open(client)
    expires_at = client.get(f"/v1/assignments/{assignment}", headers=TEACHER).json()["expires_at"]
    assert before + DEFAULT_RETENTION_DAYS * DAY <= expires_at <= time.time() + DEFAULT_RETENTION_DAYS * DAY


@pytest.mark.parametrize(("value", "days"), [("7", 7), ("0", 1), ("-5", 1), ("9999", MAX_RETENTION_DAYS), ("abc", DEFAULT_RETENTION_DAYS)])
def test_retention_days_is_clamped(client, monkeypatch, value, days):
    monkeypatch.setenv("RETENTION_DAYS", value)
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    expires_at = client.get(f"/v1/assignments/{assignment}", headers=TEACHER).json()["expires_at"]
    assert abs(expires_at - (time.time() + days * DAY)) < 60


def test_expired_assignment_is_unreachable_from_every_entrance(client, monkeypatch):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    later = time.time() + DEFAULT_RETENTION_DAYS * DAY + 1
    monkeypatch.setattr(service, "now", lambda: later)
    # TTL の削除が遅れても、期限を過ぎたデータは教員にも生徒にも見せない
    for path in ("", "/followups", "/export"):
        assert client.get(f"/v1/assignments/{assignment}{path}", headers=TEACHER).status_code == 404
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).status_code == 404
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers).status_code == 404


def test_teacher_can_delete_an_assignment_and_its_student_data(client, store, capsys):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    assert client.delete(f"/v1/assignments/{assignment}", headers=OTHER_TEACHER).status_code == 404
    assert client.delete(f"/v1/assignments/{assignment}", headers=TEACHER).status_code == 204
    assert student_data_is_gone(store, assignment)
    assert client.get(f"/v1/assignments/{assignment}", headers=TEACHER).status_code == 404
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).status_code == 404
    assert client.delete(f"/v1/assignments/{assignment}", headers=TEACHER).status_code == 404
    assert "assignment.deleted" in audit_events(capsys.readouterr().out)


def test_deleting_the_open_assignment_frees_the_class(client):
    created, assignment = setup_open(client)
    client.delete(f"/v1/assignments/{assignment}", headers=TEACHER)
    assert open_assignment_seen_by_student(client, created) is None


def open_assignment_seen_by_student(client, created):
    payload = {"class_code": created["class_code"], "personal_code": created["personal_codes"]["1"]}
    return client.post("/v1/sessions", json=payload).json()["assignment_id"]


def test_assignment_cannot_be_deleted_while_questions_are_being_made(client, store):
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    assert store.begin_generation(assignment, service.now(), 30 * 60)
    assert client.delete(f"/v1/assignments/{assignment}", headers=TEACHER).status_code == 409


def test_teacher_can_delete_a_whole_class(client, store, capsys):
    created, assignment = setup_open(client)
    other_created, other_assignment = setup_open(client)
    headers, _ = login(client, created)
    assert client.delete(f"/v1/classes/{created['class_id']}", headers=OTHER_TEACHER).status_code == 404
    assert client.delete(f"/v1/classes/{created['class_id']}", headers=TEACHER).status_code == 204
    assert student_data_is_gone(store, assignment)
    # 授業コードと個人コードは使えなくなり、配ったトークンでも課題に届かない
    payload = {"class_code": created["class_code"], "personal_code": created["personal_codes"]["1"]}
    assert client.post("/v1/sessions", json=payload).status_code == 401
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).status_code == 404
    assert store.get_class(created["class_id"]) is None
    # 別のクラスには影響しない
    assert client.get(f"/v1/assignments/{other_assignment}", headers=TEACHER).status_code == 200
    login(client, other_created)
    assert "class.deleted" in audit_events(capsys.readouterr().out)


def test_firestore_marks_every_student_document_for_ttl(client, store):
    if isinstance(store, MemoryStore):
        pytest.skip("TTL の印は Firestore だけが持つ")
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers)
    client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER)
    expected = store._assignment(assignment).get().get("expire_at")
    assert isinstance(expected, datetime)
    for name in ("submissions", "quizzes", "answerKeys", "attempts", "followups"):
        documents = list(store._part(assignment, name).stream())
        assert documents, name
        assert all(document.get("expire_at") == expected for document in documents), name
