"""APIの通し試験。実行環境は手元の合成コードだけを動かす。"""
import io
import zipfile
from unittest.mock import Mock

import pytest

from fastapi.testclient import TestClient

from app import service
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
    assert view["order"][0]["question"]
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
