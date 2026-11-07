"""APIを通したセキュリティの試験。攻撃の入力で 500 にならず、決めた応答で断ることを確かめる。"""
import json
import sys

import pytest
from fastapi.testclient import TestClient

from app.main import LOGIN_FAILURES_PER_MIN, MAX_BODY_BYTES, create_app
from qgen.ai import TemplateAI
from qgen.sandbox import LocalDevSandbox

from tests.integration.test_api import TEACHER, login, make_zip, setup_open

WRONG = {"class_code": "AAAAAAAA", "personal_code": "BBBBBBBB"}


def audit_entries(output: str) -> list[dict]:
    entries = []
    for line in output.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and "audit" in entry:
            entries.append(entry)
    return entries


def production_client(monkeypatch, store) -> TestClient:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    return TestClient(create_app(store, LocalDevSandbox, TemplateAI), base_url="https://testserver")


def test_api_responses_carry_security_headers(client):
    response = client.get("/v1/health")
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "require-trusted-types-for 'script'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "server" not in response.headers
    # HSTS は https で配信する本番だけ
    assert "strict-transport-security" not in response.headers


def test_api_responses_are_never_cached(client):
    response = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER)
    assert response.headers["cache-control"] == "no-store"


def test_static_pages_carry_the_same_policy(monkeypatch, store):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SERVE_WEB", "1")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    page = TestClient(create_app(store, LocalDevSandbox, TemplateAI)).get("/")
    assert page.status_code == 200 and "content-security-policy" in page.headers
    # ページにインラインのスクリプトがあると CSP で止まるので、置かない
    assert "<script>" not in page.text and "onclick" not in page.text


RSI_DATA = "/rsi-test-assets/rsi-demo.json"


def local_web(monkeypatch, store, rsi_test: str | None) -> TestClient:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SERVE_WEB", "1")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    if rsi_test is None:
        monkeypatch.delenv("RSI_TEST", raising=False)
    else:
        monkeypatch.setenv("RSI_TEST", rsi_test)
    return TestClient(create_app(store, LocalDevSandbox, TemplateAI))


def test_rsi_test_is_off_unless_started_with_the_option(monkeypatch, store):
    """RSIテストの記録とタブは、起動オプション（RSI_TEST=1）のときだけ。"""
    off = local_web(monkeypatch, store, None)
    assert off.get("/v1/health").json() == {"status": "ok", "rsi_test": False}
    assert off.get(RSI_DATA).status_code == 404
    assert off.get("/app.js").status_code == 200
    on = local_web(monkeypatch, store, "1")
    assert on.get("/v1/health").json()["rsi_test"] is True
    assert on.get(RSI_DATA).json()["synthetic"] is True


def test_rsi_test_never_turns_on_in_production(monkeypatch, store):
    monkeypatch.setenv("RSI_TEST", "1")
    assert production_client(monkeypatch, store).get("/v1/health").json()["rsi_test"] is False


def test_production_hides_api_docs_and_sends_hsts(monkeypatch, store):
    production = production_client(monkeypatch, store)
    assert production.get("/docs").status_code == 404
    assert production.get("/openapi.json").status_code == 404
    assert production.get("/v1/health").headers["strict-transport-security"].startswith("max-age=")


def test_local_keeps_api_docs(client):
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("bad_id", ["x", "../../classes", "0123456789abcdeF", "a" * 17, "a%2Fb%2Fc%2Fd"])
def test_malformed_ids_are_rejected_before_the_store(client, bad_id):
    assert client.get(f"/v1/assignments/{bad_id}", headers=TEACHER).status_code in (404, 422)
    payload = {"class_id": bad_id, "title": "x"}
    assert client.post("/v1/assignments", json=payload, headers=TEACHER).status_code == 422


@pytest.mark.parametrize("token", ["abc", "a.b", "a.b.c", "x" * 5000, "eyJ2IjoxfQ.AAAA"])
def test_malformed_student_tokens_are_401(client, token):
    _, assignment = setup_open(client)
    response = client.post(f"/v1/assignments/{assignment}/attempt:start", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_non_ascii_token_is_401_not_500(client):
    _, assignment = setup_open(client)
    headers = {"Authorization": "Bearer éé.éé".encode("latin-1")}
    assert client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers).status_code == 401


def test_oversized_body_is_rejected_before_parsing(client):
    response = client.post(
        "/v1/sessions", content=b"{}", headers={"content-type": "application/json", "content-length": str(MAX_BODY_BYTES + 1)}
    )
    assert response.status_code == 413
    assert "content-security-policy" in response.headers


def test_answers_with_too_many_keys_are_rejected(client):
    created, assignment = setup_open(client)
    headers, _ = login(client, created)
    client.post(f"/v1/assignments/{assignment}/attempt:start", headers=headers)
    answers = {f"q{i}": "1" for i in range(1000)}
    assert client.post(f"/v1/assignments/{assignment}/attempt:submit", json={"answers": answers}, headers=headers).status_code == 422


def test_huge_stdin_example_is_rejected(client):
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER).json()
    payload = {"class_id": created["class_id"], "title": "x", "stdin_examples": ["1" * 100_000]}
    assert client.post("/v1/assignments", json=payload, headers=TEACHER).status_code == 422


def test_budget_must_be_in_range(client):
    _, assignment = setup_open(client)
    assert client.get(f"/v1/assignments/{assignment}/followups?budget_sec=-1", headers=TEACHER).status_code == 422
    assert client.get(f"/v1/assignments/{assignment}/followups?budget_sec=1e308", headers=TEACHER).status_code == 422


def test_malformed_dev_teacher_header_is_rejected(client):
    assert client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers={"X-Dev-Teacher": "a b\tc"}).status_code == 400


def test_login_limit_is_shared_between_instances(client, store, monkeypatch):
    other = TestClient(create_app(store, LocalDevSandbox, TemplateAI))
    for index in range(LOGIN_FAILURES_PER_MIN):
        assert (client if index % 2 else other).post("/v1/sessions", json=WRONG).status_code == 401
    # 片方のインスタンスで数えた失敗も、もう片方の上限に効く
    blocked = client.post("/v1/sessions", json=WRONG)
    assert blocked.status_code == 429 and 0 < int(blocked.headers["retry-after"]) <= 60


def test_on_cloud_run_one_client_cannot_lock_out_another(client, monkeypatch):
    created, _ = setup_open(client)
    monkeypatch.setenv("K_SERVICE", "mushitori")
    attacker = {"X-Forwarded-For": "203.0.113.66"}
    for _ in range(LOGIN_FAILURES_PER_MIN):
        client.post("/v1/sessions", json=WRONG, headers=attacker)
    assert client.post("/v1/sessions", json=WRONG, headers=attacker).status_code == 429
    # 偽の X-Forwarded-For を左に足しても、右端（Cloud Run が足す値）で数えるので逃げられない
    spoofed = {"X-Forwarded-For": "198.51.100.1, 203.0.113.66"}
    assert client.post("/v1/sessions", json=WRONG, headers=spoofed).status_code == 429
    # 別の教室（別の接続元）の生徒は入れる
    student = {"X-Forwarded-For": "192.0.2.10"}
    payload = {"class_code": created["class_code"], "personal_code": created["personal_codes"]["1"]}
    assert client.post("/v1/sessions", json=payload, headers=student).status_code == 200


def test_audit_log_records_actions_but_never_codes(client, capsys):
    created, assignment = setup_open(client)
    client.post("/v1/sessions", json=WRONG)
    login(client, created)
    client.get(f"/v1/assignments/{assignment}/export", headers=TEACHER)
    output = capsys.readouterr().out
    events = [entry["audit"]["event"] for entry in audit_entries(output)]
    for expected in ("class.created", "submissions.uploaded", "generation.started", "assignment.opened", "login.failed", "login.succeeded", "export.downloaded"):
        assert expected in events
    secrets_in_play = [created["class_code"], *created["personal_codes"].values(), WRONG["class_code"], WRONG["personal_code"]]
    assert not any(secret in output for secret in secrets_in_play)
    assert "testclient" not in output  # 接続元は生の値で残さない


def test_export_is_an_attachment_and_neutralizes_formulas(client):
    created, assignment = setup_open(client, numbers=("-1", "2"))
    response = client.get(f"/v1/assignments/{assignment}/export", headers=TEACHER)
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "'-1," in response.text and "\n-1," not in response.text


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("print(__import__('os').environ)\n", "unsupported_code"),
        ("print(().__class__.__bases__[0].__subclasses__())\n", "unsupported_code"),
        ("print(open('/etc/passwd').read())\n", "unsupported_code"),
        ("x = [0] * (10 ** 9)\nprint(len(x))\n", "error"),
    ],
)
def test_escape_attempts_are_excluded_and_shown_to_the_teacher(client, code, status):
    created = client.post("/v1/classes", json={"name": "1-A", "student_numbers": ["1"]}, headers=TEACHER).json()
    assignment = client.post("/v1/assignments", json={"class_id": created["class_id"], "title": "x"}, headers=TEACHER).json()["assignment_id"]
    client.post(f"/v1/assignments/{assignment}/submissions", files={"file": ("s.zip", make_zip({"1.py": code}), "application/zip")}, headers=TEACHER)
    client.post(f"/v1/assignments/{assignment}:generate", headers=TEACHER)
    view = client.get(f"/v1/assignments/{assignment}/followups", headers=TEACHER).json()
    # macOS はメモリの上限（RLIMIT_AS）を守らないので、メモリを食うコードは時間切れで止まる。本番の Linux では error になる
    allowed = {status, "timeout"} if status == "error" and sys.platform == "darwin" else {status}
    assert len(view["excluded"]) == 1 and view["excluded"][0]["number"] == "1" and view["excluded"][0]["reason"] in allowed
