"""ネットが落ちても授業を止めないための経路の試験。

① クラウドで授業パッケージを作る → ② 教員PC（校内LAN版）で取り込んで授業を続け、結果をクラウドに戻す
→ ③ 生徒の端末にためた解答を、つながってから送る。どの段でも、守りが緩まないことを確かめる。
"""
import os
import socket
import stat
import time

import pytest
from fastapi.testclient import TestClient

from app import audit, classpack, service
from app.lan_store import LanStore
from app.main import create_app
from qgen.ai import TemplateAI
from qgen.sandbox import LocalDevSandbox
from tests.integration.test_api import CODE, TEACHER, login, setup_open

TEACHER_PC = ("127.0.0.1", 50000)
CLASSROOM_DEVICE = ("192.168.10.21", 50000)


def make_package(client, assignment):
    response = client.post(f"/v1/assignments/{assignment}/package", headers=TEACHER)
    assert response.status_code == 200, response.text
    return response.json()


def answers_for(quiz, correct_keys=None):
    return {question["id"]: (correct_keys or {}).get(question["id"], "0") for question in quiz["questions"]}


@pytest.fixture
def lan(monkeypatch, tmp_path):
    """教員PCの校内LAN版を立てる。クラウドとは別の秘密で動き、クラウドの鍵は持たない。"""

    def start(public_key_pem: str):
        for name in ("STORE_BACKEND", "AI_BACKEND", "SANDBOX_BACKEND", "MODEL_ARMOR_TEMPLATE", "PACKAGE_SIGNING_KEY", "PACKAGE_SIGNING_KMS_KEY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("DEPLOY_MODE", "lan")
        monkeypatch.setenv("APP_ENV", "lan")
        monkeypatch.setenv("SESSION_SECRET", "lan-only-secret-" + "y" * 32)
        monkeypatch.setenv("PACKAGE_PUBLIC_KEY", public_key_pem)
        monkeypatch.setenv("LAN_PUBLIC_URL", "https://192.168.10.5:8443")
        monkeypatch.setenv("LAN_DATA_DIR", str(tmp_path))
        app = create_app(LanStore.open_default(), LocalDevSandbox, TemplateAI)
        return TestClient(app, client=TEACHER_PC, base_url="https://testserver"), TestClient(app, client=CLASSROOM_DEVICE, base_url="https://testserver")

    return start


def back_to_cloud(monkeypatch):
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)


# --- ① 授業パッケージ ---------------------------------------------------------


def test_package_is_signed_sealed_and_holds_only_what_class_needs(client):
    created, assignment = setup_open(client)
    package = make_package(client, assignment)
    assert len(package["unlock_code"].split("-")) == classpack.UNLOCK_GROUPS
    assert CODE.splitlines()[0] not in package["sealed"]
    public_key = client.get("/v1/package-key").json()["public_key_pem"]
    payload = classpack.open_sealed(package["sealed"], package["unlock_code"], public_key)
    assert payload["assignment"]["id"] == assignment and len(payload["quizzes"]) == 2
    # コードは照合値（scrypt）だけで、平文もクラウドのハッシュも入らない
    flat = str(payload)
    assert created["class_code"] not in flat and all(code not in flat for code in created["personal_codes"].values())


def test_package_needs_the_owner_and_finished_questions(client):
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER).json()
    draft = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    assert client.post(f"/v1/assignments/{draft}/package", headers=TEACHER).status_code == 409
    _, assignment = setup_open(client)
    assert client.post(f"/v1/assignments/{assignment}/package", headers={"X-Dev-Teacher": "teacher-b"}).status_code == 404


def test_production_without_a_signing_key_refuses(client, monkeypatch, store):
    _, assignment = setup_open(client)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PACKAGE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("PACKAGE_SIGNING_KMS_KEY", raising=False)
    monkeypatch.setattr("app.auth.verify_firebase_token", lambda token: {"email": "teacher-a", "email_verified": True})
    monkeypatch.setenv("TEACHER_EMAILS", "teacher-a")
    response = client.post(f"/v1/assignments/{assignment}/package", headers={"Authorization": "Bearer t"})
    assert response.status_code == 503


def test_issuing_a_package_is_audited(client, capsys):
    _, assignment = setup_open(client)
    make_package(client, assignment)
    output = capsys.readouterr().out
    assert '"package.issued"' in output


# --- ② 校内LAN版で引き継ぐ ---------------------------------------------------


def test_whole_class_continues_on_the_lan_and_results_return_to_the_cloud(client, store, monkeypatch, lan):
    created, assignment = setup_open(client)
    package = make_package(client, assignment)
    public_key = client.get("/v1/package-key").json()["public_key_pem"]

    teacher_pc, device = lan(public_key)
    imported = teacher_pc.post("/v1/edge/import", json={"sealed": package["sealed"], "unlock_code": package["unlock_code"]})
    assert imported.status_code == 201 and imported.json()["student_urls"] == ["https://192.168.10.5:8443"]

    # 生徒は配られた同じコードで、教室の端末から教員PCに入る
    session = device.post("/v1/sessions", json={"class_code": created["class_code"], "personal_code": created["personal_codes"]["1"]})
    assert session.status_code == 200 and session.json()["assignment_id"] == assignment
    headers = {"Authorization": "Bearer " + session.json()["token"]}
    quiz = device.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    submitted = device.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers_for(quiz)}, headers=headers)
    assert submitted.status_code == 200

    assert teacher_pc.post(f"/v1/assignments/{assignment}:close").status_code == 200
    view = teacher_pc.get(f"/v1/assignments/{assignment}/followups").json()
    student_id = view["order"][0]["student_id"]
    teacher_pc.post(f"/v1/assignments/{assignment}/followups/{student_id}", json={"action": "ask_in_class"})
    results = teacher_pc.get(f"/v1/edge/results/{assignment}").json()
    assert results["attempts"][student_id]["answers"]

    back_to_cloud(monkeypatch)
    response = client.post(f"/v1/assignments/{assignment}/edge-results", json=results, headers=TEACHER)
    assert response.json() == {"imported": 1, "skipped": 0}
    attempt = store.get_attempt(assignment, student_id)
    assert attempt["via"] == "lan" and attempt["submitted_at"] is not None
    assert store.followups(assignment)[student_id]["action"] == "ask_in_class"


def test_cloud_regrades_lan_results_with_its_own_answer_key(client, store, monkeypatch):
    _, assignment = setup_open(client)
    student_id = next(iter(store.get_class(store.get_assignment(assignment).class_id).student_numbers))
    key = store.get_answer_key(assignment, student_id)
    right = {qid: item["answer"] for qid, item in key["questions"].items()}
    now = time.time()
    results = {
        "format": "mushitori-results-v1",
        "assignment_id": assignment,
        "attempts": {student_id: {"started_at": now - 60, "submitted_at": now, "answers": right}, "f" * 16: {"started_at": now, "submitted_at": now}},
    }
    assert client.post(f"/v1/assignments/{assignment}/edge-results", json=results, headers=TEACHER).json() == {"imported": 1, "skipped": 1}
    graded = store.get_attempt(assignment, student_id)["graded"]
    assert all(item["correct"] for item in graded)
    # 2回目はクラウドの提出が正なので上書きしない
    assert client.post(f"/v1/assignments/{assignment}/edge-results", json=results, headers=TEACHER).json()["imported"] == 0


def test_every_lan_action_is_imported_into_the_cloud_and_the_student_record(client, store):
    _, assignment = setup_open(client)
    class_id = store.get_assignment(assignment).class_id
    students = [sid for sid in store.get_class(class_id).student_numbers if store.get_answer_key(assignment, sid)]
    # 以前はこの2つがあるとファイル全体が 422 で弾かれた（ask_in_class は上のテストで確かめている）
    actions = ["explained", "not_explained"]
    assert len(students) >= len(actions)
    assert client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER).status_code == 200
    now = time.time()
    results = {
        "format": "mushitori-results-v1",
        "assignment_id": assignment,
        # 校内LANで解答し、教員がその場で処置まで記録した結果
        "attempts": {sid: {"started_at": now - 60, "submitted_at": now, "answers": {}} for sid in students[: len(actions)]},
        "followups": {sid: {"action": action} for sid, action in zip(students, actions)},
    }
    response = client.post(f"/v1/assignments/{assignment}/edge-results", json=results, headers=TEACHER)
    assert response.status_code == 200 and response.json()["imported"] == len(actions)
    followups = store.followups(assignment)
    for sid, action in zip(students, actions):
        assert followups[sid]["action"] == action and followups[sid]["via"] == "lan"
        # 締切のあとの取り込みなので、生徒ごとの記録にも処置が残る（次の課題の材料になる）
        entry = store.get_student_record(class_id, sid)["entries"][-1]
        assert entry["assignment_id"] == assignment and entry["action"]["action"] == action


def test_classroom_devices_cannot_act_as_the_teacher(client, monkeypatch, lan):
    _, assignment = setup_open(client)
    package = make_package(client, assignment)
    teacher_pc, device = lan(client.get("/v1/package-key").json()["public_key_pem"])
    body = {"sealed": package["sealed"], "unlock_code": package["unlock_code"]}
    assert device.post("/v1/edge/import", json=body).status_code == 403
    assert teacher_pc.post("/v1/edge/import", json=body).status_code == 201
    for method, path in (
        ("GET", f"/v1/assignments/{assignment}/followups"),
        ("GET", f"/v1/assignments/{assignment}/export"),
        ("POST", f"/v1/assignments/{assignment}:close"),
        ("GET", f"/v1/edge/results/{assignment}"),
        ("GET", "/v1/edge/status"),
        ("DELETE", f"/v1/assignments/{assignment}"),
    ):
        assert device.request(method, path).status_code == 403, path
    # 偽の X-Forwarded-For で教員PCになりすますこともできない
    assert device.get("/v1/edge/status", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    # 問いを作る操作は教員PCからでも使えない（コードの実行と AI はクラウドでだけ行う）
    assert teacher_pc.post(f"/v1/assignments/{assignment}:generate").status_code == 404
    assert teacher_pc.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}).status_code == 404


def test_lan_rejects_bad_packages_and_cloud_tokens(client, monkeypatch, lan):
    created, assignment = setup_open(client)
    package = make_package(client, assignment)
    cloud_headers, _ = login(client, created)
    teacher_pc, device = lan(client.get("/v1/package-key").json()["public_key_pem"])
    assert teacher_pc.post("/v1/edge/import", json={"sealed": package["sealed"], "unlock_code": classpack.new_unlock_code()}).status_code == 400
    assert teacher_pc.post("/v1/edge/import", json={"sealed": "MUSHITORI-PACK-1.AAAA", "unlock_code": package["unlock_code"]}).status_code == 400
    body = {"sealed": package["sealed"], "unlock_code": package["unlock_code"]}
    assert teacher_pc.post("/v1/edge/import", json=body).status_code == 201
    assert teacher_pc.post("/v1/edge/import", json=body).status_code == 409
    # クラウドが出したトークンは、教員PCでは使えない（秘密が別）
    assert device.post(f"/v1/assignments/{assignment}/attempt:start", headers=cloud_headers).status_code == 401


def test_package_from_another_server_is_rejected(client, monkeypatch, lan):
    _, assignment = setup_open(client)
    package = make_package(client, assignment)
    teacher_pc, _ = lan(classpack.LocalSigner().public_key_pem())
    response = teacher_pc.post("/v1/edge/import", json={"sealed": package["sealed"], "unlock_code": package["unlock_code"]})
    assert response.status_code == 400 and "署名" in response.json()["detail"]


def test_lan_data_survives_a_restart_and_is_encrypted(client, monkeypatch, lan, tmp_path):
    created, assignment = setup_open(client)
    package = make_package(client, assignment)
    public_key = client.get("/v1/package-key").json()["public_key_pem"]
    teacher_pc, _ = lan(public_key)
    teacher_pc.post("/v1/edge/import", json={"sealed": package["sealed"], "unlock_code": package["unlock_code"]})
    data = (tmp_path / "store.bin").read_bytes()
    assert b"total = 0" not in data and b"nums" not in data
    assert stat.S_IMODE(os.stat(tmp_path / "store.bin").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "store.key").st_mode) == 0o600
    # 教員PCを再起動しても、取り込んだ授業がそのまま続けられる
    _, device = lan(public_key)
    session = device.post("/v1/sessions", json={"class_code": created["class_code"], "personal_code": created["personal_codes"]["2"]})
    assert session.status_code == 200 and session.json()["assignment_id"] == assignment


def test_lan_refuses_to_start_with_cloud_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOY_MODE", "lan")
    monkeypatch.setenv("LAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_BACKEND", "gemini")
    with pytest.raises(RuntimeError, match="AI_BACKEND"):
        create_app(LanStore.open_default(), LocalDevSandbox, TemplateAI)


def test_lan_makes_no_outbound_connections(client, monkeypatch, lan):
    """取り込みから入室、解答、締切、声かけ、書き出しまで、外への接続を一度もしない。"""
    created, assignment = setup_open(client)
    package = make_package(client, assignment)
    public_key = client.get("/v1/package-key").json()["public_key_pem"]
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise OSError("外への接続は禁止")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    teacher_pc, device = lan(public_key)
    assert teacher_pc.post("/v1/edge/import", json={"sealed": package["sealed"], "unlock_code": package["unlock_code"]}).status_code == 201
    for number in ("1", "2"):
        session = device.post("/v1/sessions", json={"class_code": created["class_code"], "personal_code": created["personal_codes"][number]}).json()
        headers = {"Authorization": "Bearer " + session["token"]}
        quiz = device.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
        assert device.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers_for(quiz)}, headers=headers).status_code == 200
    teacher_pc.post(f"/v1/assignments/{assignment}:close")
    assert teacher_pc.get(f"/v1/assignments/{assignment}/followups").status_code == 200
    assert teacher_pc.get(f"/v1/assignments/{assignment}/export").status_code == 200
    assert teacher_pc.get(f"/v1/edge/results/{assignment}").status_code == 200
    assert attempts == []


# --- ③ 生徒の端末にためた解答 ------------------------------------------------


def test_answers_sent_after_reconnecting_are_kept_and_marked(client, store, monkeypatch, capsys):
    created, assignment = setup_open(client, time_limit=60)
    headers, _ = login(client, created)
    current = [time.time()]
    monkeypatch.setattr(service, "now", lambda: current[0])
    quiz = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    current[0] += 30 * 60
    late = client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers_for(quiz)}, headers=headers)
    assert late.status_code == 410
    body = {"answers": answers_for(quiz), "answered_at": current[0] - 29 * 60}
    response = client.post(f"/v1/assignments/{assignment}/attempt:submit-offline", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["offline"] is True
    attempt = store.get_attempt(assignment, next(iter(store.attempts(assignment))))
    assert attempt["via"] == "offline" and attempt["submitted_at"] == current[0]
    # 送り直しは同じ結果を返す。2回目の解答で上書きはしない
    again = client.post(f"/v1/assignments/{assignment}/attempt:submit-offline", json={**body, "answers": {}}, headers=headers)
    assert again.status_code == 200 and again.json()["already_submitted"] is True
    assert again.json()["results"] == response.json()["results"]
    assert '"attempt.offline_submitted"' in capsys.readouterr().out


def test_offline_answers_survive_token_expiry_but_not_forever(client, monkeypatch):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    quiz = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    body = {"answers": answers_for(quiz), "answered_at": time.time()}
    # 入室の期限（2時間）を過ぎても、1日以内なら送れる
    real = time.time()
    monkeypatch.setattr(time, "time", lambda: real + 3 * 60 * 60)
    monkeypatch.setattr(service, "now", lambda: real + 3 * 60 * 60)
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).status_code == 401
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit-offline", json=body, headers=headers).status_code == 200


def test_offline_answers_after_a_day_are_refused(client, monkeypatch):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    quiz = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    real = time.time()
    monkeypatch.setattr(time, "time", lambda: real + 27 * 60 * 60)
    monkeypatch.setattr(service, "now", lambda: real + 27 * 60 * 60)
    body = {"answers": answers_for(quiz), "answered_at": real}
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit-offline", json=body, headers=headers).status_code == 401


def test_offline_submit_needs_a_started_attempt(client):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    body = {"answers": {}, "answered_at": time.time()}
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit-offline", json=body, headers=headers).status_code == 409
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit-offline", json=body).status_code == 401


def test_audit_never_records_the_unlock_code(client, capsys):
    _, assignment = setup_open(client)
    package = make_package(client, assignment)
    assert package["unlock_code"] not in capsys.readouterr().out
    assert audit.ALLOWED_FIELDS.isdisjoint({"unlock_code", "sealed"})


def test_resend_after_a_lost_reply_is_reported_as_delivered(client):
    """解答はサーバーに届いたが、返事が途中で失われた場合。端末が送り直しても、届いていたと分かる。"""
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    quiz = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    answers = answers_for(quiz)
    first = client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers}, headers=headers).json()
    resent = client.post(f"/v1/assignments/{assignment}/attempt:submit-offline", json={"answers": answers, "answered_at": time.time()}, headers=headers)
    assert resent.status_code == 200 and resent.json()["already_submitted"] is True
    assert resent.json()["offline"] is False and resent.json()["score"] == first["score"]


def test_lan_store_keeps_student_records_and_explanations_across_restarts(tmp_path):
    from app.lan_store import LanStore

    key = os.urandom(32)
    first = LanStore(tmp_path / "store.bin", key)
    first.save_student_entry("c" * 16, "s" * 16, {"assignment_id": "a" * 16, "title": "合計", "closed_at": 1.0, "spots": []})
    reopened = LanStore(tmp_path / "store.bin", key)
    assert reopened.get_student_record("c" * 16, "s" * 16)["entries"][0]["title"] == "合計"
    assert "合計".encode() not in (tmp_path / "store.bin").read_bytes()
