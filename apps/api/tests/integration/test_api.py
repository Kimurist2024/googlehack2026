"""APIの通し試験。実行環境は手元の合成コードだけを動かす。"""
import io
import zipfile
from unittest.mock import Mock

import pytest

import pytest
from fastapi.testclient import TestClient

from app import auth, service
from app.main import LOGIN_FAILURES_PER_MIN, create_app
from qgen.ai import TemplateAI
from qgen.sandbox import LocalDevSandbox

TEACHER = {"X-Dev-Teacher": "teacher-a"}
CODE = """nums = [3, 8, 2, 5]
total = 0
for n in nums:
    if n > 2:
        total = total + n
print(total)
"""


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def setup_open(client, numbers=("1", "2"), code=CODE, time_limit=300):
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": list(numbers)}, headers=TEACHER).json()
    assignment = client.post(
        "/v1/assignments",
        json={"class_id": created["class_id"], "title": "合計", "learning_goal": "繰り返し", "time_limit_sec": time_limit},
        headers=TEACHER,
    ).json()["assignment_id"]
    uploaded = client.post(
        f"/v1/assignments/{assignment}/submissions",
        files={"file": ("s.zip", make_zip({f"{n}.py": code for n in numbers}), "application/zip")},
        headers=TEACHER,
    )
    assert uploaded.json()["accepted"] == len(numbers)
    assert client.post(f"/v1/assignments/{assignment}:generate", headers=TEACHER).status_code == 202
    assert client.get(f"/v1/assignments/{assignment}", headers=TEACHER).json()["state"] == "ready"
    assert client.post(f"/v1/assignments/{assignment}:open", headers=TEACHER).status_code == 200
    return created, assignment


def login(client, created, number="1"):
    response = client.post("/v1/sessions", json={"class_code": created["class_code"], "personal_code": created["personal_codes"][number]})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}, response.json()


def test_full_flow_from_upload_to_followups(client):
    created, assignment = setup_open(client)
    headers, session = login(client, created)
    assert session["assignment_id"] == assignment

    started = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    assert len(started["questions"]) == 3 and started["code"] == CODE
    assert started["remaining_sec"] > 290

    # 正解は解答前の応答に含まれない
    assert '"answer"' not in str(started).replace("'", '"')

    wrong = {question["id"]: "0" for question in started["questions"]}
    result = client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": wrong}, headers=headers).json()
    assert result["score"] == 0 and result["total"] == 3
    assert result["results"][0]["explanation"] and result["trace"]
    assert "成績" in result["notice"]

    assert client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER).status_code == 200
    view = client.get(f"/v1/assignments/{assignment}/followups?budget_sec=90", headers=TEACHER).json()
    assert view["order"][0]["number"] == "1" and view["order"][0]["in_budget"] is True
    review = view["order"][0]["review"]
    assert review["overview"] and review["by"] == "template"
    # 行を指す誤答があれば、その行を先に挙げる。出力の予測は行を指せないので最後に置く
    assert review["spots"][0]["line"] and review["spots"][0]["unexplained"]
    assert all(spot["question"] for spot in review["spots"])
    assert view["order"][0]["question"] == review["spots"][0]["question"]
    assert [item["given"] for item in view["order"][0]["evidence"]] == ["0", "0", "0"]
    assert [row["number"] for row in view["not_attempted"]] == ["2"]

    student_id = view["order"][0]["student_id"]
    saved = client.post(
        f"/v1/assignments/{assignment}/followups/{student_id}",
        json={"action": "ask_in_class", "duration_ms": 12000},
        headers=TEACHER,
    )
    assert saved.status_code == 200
    assert client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()["tau_sec"] == 12.0
    exported = client.get(f"/v1/assignments/{assignment}/export", headers=TEACHER).text
    assert "ask_in_class" in exported and "山田" not in exported


def test_followup_prefers_a_wrong_question_with_a_line_number(client):
    created, assignment = setup_open(client, numbers=("1",))
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers)
    client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER)
    row = client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()["order"][0]
    assert "行目" in row["question"]


def test_acted_students_do_not_use_up_the_budget(client):
    created, assignment = setup_open(client)
    for number in ("1", "2"):
        headers, _ = login(client, created, number)
        client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
        client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers)
    client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER)
    url = f"/v1/assignments/{assignment}/followups?budget_sec=30"
    before = client.get(url, headers=TEACHER).json()["order"]
    assert [row["in_budget"] for row in before] == [True, False]
    client.post(
        f"/v1/assignments/{assignment}/followups/{before[0]['student_id']}",
        json={"action": "ask_in_class", "duration_ms": 30000},
        headers=TEACHER,
    )
    after = client.get(url, headers=TEACHER).json()["order"]
    assert [row["in_budget"] for row in after] == [False, True]


def test_correct_answers_score_full_marks(client):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    # 正解はサーバー内部からだけ取得できる
    store = client.app.state.store
    record = store.get_assignment(assignment)
    student_id = next(sid for sid, number in store.get_class(record.class_id).student_numbers.items() if number == "1")
    answers = {qid: item["answer"] for qid, item in store.get_answer_key(assignment, student_id)["questions"].items()}
    result = client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers}, headers=headers).json()
    assert result["score"] == result["total"]


def test_submit_twice_is_rejected(client):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers).status_code == 200
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers).status_code == 409
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).status_code == 409


def test_restart_keeps_the_original_clock(client, monkeypatch):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    current = [1000.0]
    monkeypatch.setattr(service, "now", lambda: current[0])
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()["remaining_sec"] == 300
    current[0] += 100
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()["remaining_sec"] == 200


def test_late_submission_is_rejected_using_server_time(client, monkeypatch):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    current = [1000.0]
    monkeypatch.setattr(service, "now", lambda: current[0])
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    current[0] += 311
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers).status_code == 410


def test_unusable_program_goes_to_the_separate_list(client):
    created, assignment = setup_open(client, numbers=("1",), code="while True:\n    pass\n")
    headers, _ = login(client, created)
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).status_code == 409
    view = client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()
    assert view["excluded"][0]["reason"] == "too_long" and view["order"] == []


def test_teacher_endpoints_require_authentication(client):
    assert client.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}).status_code == 401


def test_dev_header_is_ignored_outside_local(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    response = client.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}, headers=TEACHER)
    assert response.status_code == 401


def test_other_teacher_cannot_read_assignment(client):
    _, assignment = setup_open(client)
    other = {"X-Dev-Teacher": "teacher-b"}
    assert client.get(f"/v1/assignments/{assignment}/followups", headers=other).status_code == 404
    assert client.post(f"/v1/assignments/{assignment}:close", headers=other).status_code == 404


@pytest.mark.parametrize("operation", ["upload", "followups", "action", "export"])
@pytest.mark.parametrize("other_teacher", [False, True])
def test_teacher_request_reads_the_class_once(client, store, monkeypatch, operation, other_teacher):
    created = client.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    student_id = next(iter(store.get_class(created["class_id"]).student_numbers))
    read = Mock(wraps=store.get_class)
    monkeypatch.setattr(store, "get_class", read)
    url = f"/v1/assignments/{assignment}"
    headers = {"X-Dev-Teacher": "teacher-b"} if other_teacher else TEACHER
    if operation == "upload":
        response = client.post(f"{url}/submissions", files={"file": ("s.zip", make_zip({"1.py": CODE}), "application/zip")}, headers=headers)
    elif operation == "action":
        response = client.post(f"{url}/followups/{student_id}", json={"action": "ask_in_class"}, headers=headers)
    else:
        response = client.get(f"{url}/{operation}", headers=headers)
    read.assert_called_once_with(created["class_id"])
    if other_teacher:
        assert response.status_code == 404
        assert store.submissions(assignment) == {} and store.followups(assignment) == {}
    else:
        assert response.status_code == 200
        if operation == "upload":
            assert response.json() == {"accepted": 1, "problems": []}
        elif operation == "action":
            assert response.json() == {"saved": True}


def test_class_ownership_is_checked_again_on_the_next_request(client, store, monkeypatch):
    created = client.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    original = store.get_class
    owner = ["teacher-a"]
    def read(class_id):
        classroom = original(class_id)
        classroom.teacher = owner[0]
        return classroom
    monkeypatch.setattr(store, "get_class", read)
    url = f"/v1/assignments/{assignment}/followups"
    assert client.get(url, headers=TEACHER).status_code == 200
    owner[0] = "teacher-b"
    assert client.get(url, headers=TEACHER).status_code == 404


def test_student_token_cannot_reach_another_class(client):
    created, _ = setup_open(client)
    other_created = client.post("/v1/classes", json={"name": "1-B", "student_numbers": ["9"]}, headers=TEACHER).json()
    other_assignment = client.post(
        "/v1/assignments", json={"class_id": other_created["class_id"], "title": "x"}, headers=TEACHER
    ).json()["assignment_id"]
    headers, _ = login(client, created)
    assert client.post(f"/v1/assignments/{other_assignment}/attempt:start", headers=headers).status_code == 404


def test_tampered_token_is_rejected(client):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    original = headers["Authorization"]
    replacement = "0" if original[-1] != "0" else "1"
    tampered = {"Authorization": original[:-1] + replacement}
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=tampered).status_code == 401


def test_wrong_codes_are_rejected_and_rate_limited(client):
    created, _ = setup_open(client)
    payload = {"class_code": created["class_code"], "personal_code": "WRONGCODE"}
    statuses = [client.post("/v1/sessions", json=payload).status_code for _ in range(LOGIN_FAILURES_PER_MIN + 1)]
    assert statuses[:-1] == [401] * LOGIN_FAILURES_PER_MIN and statuses[-1] == 429
    # 上限に達したあとは、正しいコードでも1分待つまで入れない
    correct = {"class_code": created["class_code"], "personal_code": created["personal_codes"]["1"]}
    assert client.post("/v1/sessions", json=correct).status_code == 429


def test_whole_class_from_one_address_can_enter(client):
    """教室の40人が同じ接続元から続けて入っても止めない。"""
    numbers = [str(number) for number in range(1, 41)]
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": numbers}, headers=TEACHER).json()
    for number in numbers:
        body = {"class_code": created["class_code"], "personal_code": created["personal_codes"][number]}
        assert client.post("/v1/sessions", json=body).status_code == 200


def test_a_few_typos_do_not_block_the_class(client):
    numbers = [str(number) for number in range(1, 41)]
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": numbers}, headers=TEACHER).json()
    wrong = {"class_code": created["class_code"], "personal_code": "WRONGCODE"}
    for number in numbers:
        if int(number) % 4 == 0:  # 4人に1人が一度打ち間違える
            assert client.post("/v1/sessions", json=wrong).status_code == 401
        body = {"class_code": created["class_code"], "personal_code": created["personal_codes"][number]}
        assert client.post("/v1/sessions", json=body).status_code == 200


def test_names_are_not_accepted_as_student_numbers(client):
    response = client.post("/v1/classes", json={"name": "x", "student_numbers": ["山田"]}, headers=TEACHER)
    assert response.status_code == 422


def test_no_problem_requires_a_reason(client):
    created, assignment = setup_open(client)
    view = client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()
    assert view["order"] == []
    student_id = next(iter(client.app.state.store.submissions(assignment)))
    url = f"/v1/assignments/{assignment}/followups/{student_id}"
    assert client.post(url, json={"action": "no_problem"}, headers=TEACHER).status_code == 422
    assert client.post(url, json={"action": "no_problem", "reason": "説明できた"}, headers=TEACHER).status_code == 200


def test_zip_problems_are_reported_without_failing(client):
    created = client.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    data = make_zip({"1.py": CODE, "9.py": CODE, "a.txt": "x", "../../evil.py": CODE})
    body = client.post(
        f"/v1/assignments/{assignment}/submissions", files={"file": ("s.zip", data, "application/zip")}, headers=TEACHER
    ).json()
    assert body["accepted"] == 1 and len(body["problems"]) == 3


def test_not_a_zip_is_rejected(client):
    created = client.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    response = client.post(f"/v1/assignments/{assignment}/submissions", files={"file": ("s.zip", b"nope", "application/zip")}, headers=TEACHER)
    assert response.status_code == 400


class BrokenSandbox:
    def analyze(self, code, stdin):
        raise RuntimeError("API unavailable")


def test_sandbox_failure_marks_submission_and_does_not_hang(monkeypatch, store):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    app_client = TestClient(create_app(store, BrokenSandbox, TemplateAI))
    seeded = app_client.post("/v1/dev/seed", headers=TEACHER).json()
    assignment = seeded["assignment_id"]
    app_client.post(f"/v1/assignments/{assignment}:generate", headers=TEACHER)
    status = app_client.get(f"/v1/assignments/{assignment}", headers=TEACHER).json()
    assert status["state"] == "ready" and status["submissions"] == {"failed": 6}


def test_sandbox_setup_failure_returns_to_draft(monkeypatch, store):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)

    def factory():
        raise RuntimeError("no credentials")

    app_client = TestClient(create_app(store, factory, TemplateAI), raise_server_exceptions=False)
    seeded = app_client.post("/v1/dev/seed", headers=TEACHER).json()
    assignment = seeded["assignment_id"]
    app_client.post(f"/v1/assignments/{assignment}:generate", headers=TEACHER)
    assert app_client.get(f"/v1/assignments/{assignment}", headers=TEACHER).json()["state"] == "draft"


def test_demo_seed_exists_only_locally(client, monkeypatch):
    created = client.post("/v1/dev/seed", headers=TEACHER)
    assert created.status_code == 201 and len(created.json()["personal_codes"]) == 6
    assignment = created.json()["assignment_id"]
    assert client.post(f"/v1/assignments/{assignment}:generate", headers=TEACHER).status_code == 202
    status = client.get(f"/v1/assignments/{assignment}", headers=TEACHER).json()
    assert status["submissions"] == {"ready": 4, "excluded": 2}
    monkeypatch.setenv("APP_ENV", "production")
    assert client.post("/v1/dev/seed", headers=TEACHER).status_code == 401


def test_missing_secret_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SESSION_SECRET")
    response = client.post("/v1/classes", json={"name": "x", "student_numbers": ["1"]}, headers=TEACHER)
    assert response.status_code == 503


def test_two_instances_share_the_whole_flow(client, store):
    """Cloud Run の複数インスタンスを想定し、先生と生徒で別のアプリを通す。"""
    other = TestClient(create_app(store, LocalDevSandbox, TemplateAI))
    created, assignment = setup_open(client)
    headers, _ = login(other, created)
    quiz = other.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    answers = {question["id"]: "まちがい" for question in quiz["questions"]}
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers}, headers=headers).status_code == 200
    assert other.post(f"/v1/assignments/{assignment}:close", headers=TEACHER).status_code == 200
    view = client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()
    assert [row["score"] for row in view["order"]] == [0]
    assert view["order"][0]["question"]
    assert [item["number"] for item in view["not_attempted"]] == ["2"]


def test_export_follows_the_roster_order(client):
    numbers = ("3", "10", "1", "2")
    created, assignment = setup_open(client, numbers=numbers)
    rows = client.get(f"/v1/assignments/{assignment}/export", headers=TEACHER).text.splitlines()[1:]
    assert [row.split(",")[0] for row in rows] == list(numbers)


def test_regeneration_does_not_serve_the_old_quiz(client):
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "合計"}, headers=TEACHER).json()["assignment_id"]
    url = f"/v1/assignments/{assignment}"
    for code in (CODE, "import os\nprint(os.getcwd())\n"):
        files = {"file": ("s.zip", make_zip({"1.py": code}), "application/zip")}
        assert client.post(f"{url}/submissions", files=files, headers=TEACHER).json()["accepted"] == 1
        assert client.post(f"{url}:generate", headers=TEACHER).status_code == 202
    assert client.post(f"{url}:open", headers=TEACHER).status_code == 200
    headers, _ = login(client, created)
    assert client.post(f"{url}/attempt:start", headers=headers).status_code == 409


def test_unknown_weight_kind_is_rejected(client):
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER).json()
    body = {"class_id": created["class_id"], "title": "合計", "weights": {"__x__": 1.0}}
    assert client.post("/v1/assignments", json=body, headers=TEACHER).status_code == 422


def test_answer_too_long_for_storage_is_rejected(client):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    quiz = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
    answers = {quiz["questions"][0]["id"]: "あ" * 20_001}
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers}, headers=headers).status_code == 422


def test_health_is_reachable_on_cloud_run_paths(client):
    assert client.get("/v1/health").json()["status"] == "ok"


@pytest.fixture
def firebase_teacher(monkeypatch):
    """本番の設定で、Firebase のトークン検証だけを偽物にする。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TEACHER_EMAILS", "teacher@example.com")
    tokens = {
        "good": {"email": "teacher@example.com", "email_verified": True},
        "other": {"email": "someone@example.com", "email_verified": True},
        "unverified": {"email": "teacher@example.com", "email_verified": False},
    }

    def verify(token):
        if token not in tokens:
            raise ValueError("bad token")
        return tokens[token]

    monkeypatch.setattr(auth, "verify_firebase_token", verify)
    return lambda token: {"Authorization": f"Bearer {token}"}


def test_me_tells_the_page_whether_the_account_is_a_teacher(client, firebase_teacher):
    assert client.get("/v1/me", headers=firebase_teacher("good")).json() == {"email": "teacher@example.com", "guest": False}
    assert client.get("/v1/me", headers=firebase_teacher("other")).status_code == 403
    assert client.get("/v1/me").status_code == 401


def test_only_allowed_verified_teachers_pass(client, firebase_teacher):
    body = {"name": "1-A", "student_numbers": ["1"]}
    assert client.post("/v1/classes", json=body, headers=firebase_teacher("good")).status_code == 201
    assert client.post("/v1/classes", json=body, headers=firebase_teacher("other")).status_code == 403
    assert client.post("/v1/classes", json=body, headers=firebase_teacher("unverified")).status_code == 403
    assert client.post("/v1/classes", json=body, headers=firebase_teacher("forged")).status_code == 401


def test_demo_seed_in_production_needs_the_flag_and_a_login(client, firebase_teacher, monkeypatch):
    assert client.post("/v1/dev/seed", headers=firebase_teacher("good")).status_code == 404
    monkeypatch.setenv("ALLOW_DEMO_SEED", "1")
    assert client.post("/v1/dev/seed").status_code == 401
    assert client.post("/v1/dev/seed", headers=TEACHER).status_code == 401
    created = client.post("/v1/dev/seed", headers=firebase_teacher("good"))
    assert created.status_code == 201 and len(created.json()["personal_codes"]) == 6


def answer_all(client, created, assignment, numbers, answer):
    for number in numbers:
        headers, _ = login(client, created, number)
        quiz = client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).json()
        answers = {question["id"]: answer for question in quiz["questions"]}
        assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers}, headers=headers).status_code == 200


def test_class_summary_needs_three_students(client):
    created, assignment = setup_open(client, numbers=("1", "2"))
    answer_all(client, created, assignment, ("1", "2"), "0")
    client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER)
    view = client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()
    assert view["class_summary"] is None and view["summary_min_students"] == 3


def test_class_summary_counts_wrong_answers_by_question_type(client):
    created, assignment = setup_open(client, numbers=("1", "2", "3"))
    answer_all(client, created, assignment, ("1", "2", "3"), "0")
    client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER)
    summary = client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()["class_summary"]
    assert summary["students"] == 3 and summary["points"]
    assert all(s["answered"] == 3 and s["wrong"] == 3 for s in summary["stats"])
    assert "番号" not in str(summary)


def test_chat_is_only_for_submitted_attempts_and_has_a_limit(client, monkeypatch):
    created, assignment = setup_open(client, numbers=("1",))
    headers, _ = login(client, created)
    url = f"/v1/assignments/{assignment}/attempt:chat"
    assert client.post(url, json={"message": "ヒントをください"}).status_code == 401
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    assert client.post(url, json={"message": "ヒントをください"}, headers=headers).status_code == 409
    client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers)
    monkeypatch.setattr(service, "CHAT_LIMIT", 2)
    first = client.post(url, json={"message": "ヒントをください"}, headers=headers).json()
    assert first["reply"] and first["remaining"] == 1
    history = [{"role": "student", "text": "ヒントをください"}, {"role": "ai", "text": first["reply"]}]
    assert client.post(url, json={"message": "もう少し", "history": history}, headers=headers).json()["remaining"] == 0
    assert client.post(url, json={"message": "もう一回"}, headers=headers).status_code == 429
    assert client.post(url, json={"message": "あ" * 301}, headers=headers).status_code == 422


SHORTHAND = CODE.replace("total = total + n", "total += n")


def open_in_class(client, created, codes: dict[str, str], title="合計"):
    """同じクラスに、次の課題を出して受付を始める。"""
    assignment = client.post(
        "/v1/assignments", json={"class_id": created["class_id"], "title": title, "learning_goal": "繰り返し"}, headers=TEACHER
    ).json()["assignment_id"]
    files = {f"{number}.py": code for number, code in codes.items()}
    client.post(f"/v1/assignments/{assignment}/submissions", files={"file": ("s.zip", make_zip(files), "application/zip")}, headers=TEACHER)
    client.post(f"/v1/assignments/{assignment}:generate", headers=TEACHER)
    assert client.post(f"/v1/assignments/{assignment}:open", headers=TEACHER).status_code == 200
    return assignment


def close_and_view(client, assignment):
    client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER)
    return client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()


def test_records_accumulate_and_a_new_way_of_writing_is_raised(client):
    created, first = setup_open(client, numbers=("1", "2", "3"))
    answer_all(client, created, first, ("1", "2", "3"), "0")
    rows = close_and_view(client, first)["order"]
    assert all(row["review"]["spots"][0]["new"] == [] for row in rows)  # 最初の課題では「初めて」を判断しない
    assert "最初" in rows[0]["review"]["overview"]

    # 2回目は番号1だけが、これまで使っていなかった += を使う。クラスでもほかに使った人はいない
    second = open_in_class(client, created, {"1": SHORTHAND, "2": CODE, "3": CODE}, title="合計その2")
    answer_all(client, created, second, ("1", "2", "3"), "0")
    rows = {row["number"]: row for row in close_and_view(client, second)["order"]}
    flagged = [spot for spot in rows["1"]["review"]["spots"] if spot["new"]]
    assert flagged and flagged[0]["line"] == 5 and flagged[0]["rare"] == ["`+=` などの累算代入"]
    assert flagged[0]["question"].startswith("5行目の`+=`")
    assert not any(spot["new"] for spot in rows["2"]["review"]["spots"])
    assert "直近1回" in rows["1"]["review"]["overview"]

    record = client.get(f"/v1/assignments/{second}/students/{rows['1']['student_id']}/record", headers=TEACHER).json()
    assert record["number"] == "1" and [entry["title"] for entry in record["entries"]] == ["合計その2", "合計"]
    assert "`+=` などの累算代入" in record["entries"][0]["constructs"] and record["entries"][0]["score"] == 0


def test_closing_again_does_not_duplicate_the_record(client):
    created, assignment = setup_open(client, numbers=("1",))
    answer_all(client, created, assignment, ("1",), "0")
    row = close_and_view(client, assignment)["order"][0]
    service.create_followups(client.app.state.store, client.app.state.store.get_assignment(assignment), TemplateAI())
    record = client.get(f"/v1/assignments/{assignment}/students/{row['student_id']}/record", headers=TEACHER).json()
    assert len(record["entries"]) == 1


def test_teacher_result_is_kept_in_the_student_record(client):
    created, assignment = setup_open(client, numbers=("1",))
    answer_all(client, created, assignment, ("1",), "0")
    row = close_and_view(client, assignment)["order"][0]
    saved = client.post(f"/v1/assignments/{assignment}/followups/{row['student_id']}", json={"action": "not_explained"}, headers=TEACHER)
    assert saved.status_code == 200
    record = client.get(f"/v1/assignments/{assignment}/students/{row['student_id']}/record", headers=TEACHER).json()
    assert record["entries"][0]["action"] == {"action": "not_explained", "reason": ""}
    assert client.post(f"/v1/assignments/{assignment}/followups/{row['student_id']}", json={"action": "guess"}, headers=TEACHER).status_code == 422


def test_student_record_is_only_for_the_owning_teacher(client):
    created, assignment = setup_open(client, numbers=("1",))
    answer_all(client, created, assignment, ("1",), "0")
    row = close_and_view(client, assignment)["order"][0]
    url = f"/v1/assignments/{assignment}/students/{row['student_id']}/record"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-Dev-Teacher": "teacher-b"}).status_code == 404
    assert client.get(f"/v1/assignments/{assignment}/students/{'0' * 16}/record", headers=TEACHER).status_code == 404
    assert client.get(f"/v1/assignments/{assignment}/students/nobody/record", headers=TEACHER).status_code == 422  # IDの形が違う


def test_students_explain_missed_lines_in_their_own_words(client):
    created, assignment = setup_open(client, numbers=("1",))
    headers, _ = login(client, created)
    url = f"/v1/assignments/{assignment}/attempt:explain"
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    assert client.post(url, json={"line": 5, "text": "合計に足す"}, headers=headers).status_code == 409
    result = client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers).json()
    missed = sorted({item["line"] for item in result["results"] if not item["correct"] and item["line"]})
    assert missed
    assert client.post(url, json={"line": missed[0], "text": "  n が 2 より大きいときだけ足す  "}, headers=headers).status_code == 200
    assert client.post(url, json={"line": 6, "text": "表示する"}, headers=headers).status_code == 400  # 誤答した問いが指していない行
    assert client.post(url, json={"line": missed[0], "text": "あ" * 301}, headers=headers).status_code == 422
    assert client.post(url, json={"line": missed[0], "text": "x"}).status_code == 401
    row = close_and_view(client, assignment)["order"][0]
    assert row["explanations"] == {str(missed[0]): "n が 2 より大きいときだけ足す"}


def explain_missed_line(client, created, assignment) -> tuple[dict, str, int]:
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    result = client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers).json()
    line = min(item["line"] for item in result["results"] if not item["correct"] and item["line"])
    return headers, f"/v1/assignments/{assignment}/attempt:explain", line


def test_explanation_sentences_are_checked_by_running_the_students_code(client):
    """説明の文を本人のコードで動かして確かめ、教員の画面に添える。説明どおりかは実行の結果で決める。"""
    created, assignment = setup_open(client, numbers=("1",))
    headers, url, line = explain_missed_line(client, created, assignment)
    # CODE は 16 だけを表示する。何を試すかは、Gemini を使わない既定の規則（PatternProbePlanner）が決める
    text = "大きい数だけ足している。16も表示される。3も表示される"
    assert client.post(url, json={"line": line, "text": text}, headers=headers).status_code == 200
    row = close_and_view(client, assignment)["order"][0]
    assert row["explanations"] == {str(line): text}
    checks = row["explanation_checks"][str(line)]
    assert [(c["sentence"], c["verdict"]) for c in checks] == [("16も表示される。", "holds"), ("3も表示される", "fails")]
    assert checks[1]["runs"] == [
        {"tried": "実行", "expected": "「3」の行が表示される", "actual": "「3」の行は表示されなかった", "verdict": "fails"}
    ]


def test_rewritten_explanation_drops_the_old_checks(client):
    created, assignment = setup_open(client, numbers=("1",))
    headers, url, line = explain_missed_line(client, created, assignment)
    client.post(url, json={"line": line, "text": "3も表示される"}, headers=headers)
    client.post(url, json={"line": line, "text": "合計を出している"}, headers=headers)  # 確かめられる文がない
    row = close_and_view(client, assignment)["order"][0]
    assert row["explanations"] == {str(line): "合計を出している"} and row["explanation_checks"] == {}


def test_sending_the_same_explanation_again_does_not_plan_again(monkeypatch, store):
    """同じ文をもう一度送っても、Gemini（ここでは数える偽物）と隔離環境を使い直さない。"""
    from qgen.probes import PatternProbePlanner

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    asked = []

    class Counting(PatternProbePlanner):
        def plan(self, claim, code):
            asked.append(claim)
            return super().plan(claim, code)

    app_client = TestClient(create_app(store, LocalDevSandbox, TemplateAI, Counting))
    created, assignment = setup_open(app_client, numbers=("1",))
    headers, url, line = explain_missed_line(app_client, created, assignment)
    for _ in range(2):
        assert app_client.post(url, json={"line": line, "text": "16も表示される"}, headers=headers).status_code == 200
    assert asked == ["16も表示される"]


def test_demo_seed_brings_past_records(client, monkeypatch):
    monkeypatch.setenv("ALLOW_DEMO_SEED", "1")
    created = client.post("/v1/dev/seed", headers=TEACHER).json()
    store = client.app.state.store
    classroom = store.get_class(created["class_id"])
    by_number = {number: student_id for student_id, number in classroom.student_numbers.items()}
    record = client.get(f"/v1/assignments/{created['assignment_id']}/students/{by_number['2']}/record", headers=TEACHER).json()
    assert [entry["title"] for entry in record["entries"]] == ["最大値を探す（第2回）", "合計を求める（第1回）"]
    assert store.get_student_record(created["class_id"], by_number["6"]) is None


def test_ai_client_is_built_once_and_reused(monkeypatch, store):
    """Gemini と Model Armor のクライアントは作るたびに準備がかかるので、要求ごとに作り直さない。"""
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    built = []

    def factory():
        built.append(1)
        return TemplateAI()

    app_client = TestClient(create_app(store, LocalDevSandbox, factory))
    created, assignment = setup_open(app_client, numbers=("1",))
    headers, _ = login(app_client, created)
    app_client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    app_client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": {}}, headers=headers)
    for _ in range(3):
        assert app_client.post(f"/v1/assignments/{assignment}/attempt:chat", json={"message": "ヒント"}, headers=headers).status_code == 200
    app_client.post(f"/v1/assignments/{assignment}:close", headers=TEACHER)
    assert len(built) == 1
