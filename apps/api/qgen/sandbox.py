"""生徒のコードを動かす実行環境。本番は Code Execution を使う。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

HARNESS_SOURCE = (Path(__file__).parent / "harness.py").read_text(encoding="utf-8")
RESULT_PREFIX = "HARNESS_RESULT:"
HARNESS_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
DEFAULT_REQUEST = {
    "run_timeout_sec": 1,
    "max_events": 200_000,
    "max_mutants": 30,
    "max_output_chars": 20_000,
    "deadline_sec": 45,
    "max_probes": 3,
}


class SandboxError(RuntimeError):
    """実行環境そのものが失敗したときの例外。生徒のコードの失敗とは区別する。"""


class Sandbox(Protocol):
    def analyze(self, student_code: str, stdin: str) -> dict: ...

    def probe(self, student_code: str, probes: list[dict]) -> dict: ...


def probe_request(probes: list[dict]) -> dict:
    """動きの主張を確かめる依頼。中身の形は qgen.probes で検査してから渡す。"""
    return {**DEFAULT_REQUEST, "stdin": "", "mode": "probe", "probes": probes}


def parse_result(stdout: str) -> dict:
    """結果の行だけを読む。隔離環境の出力は信用せず、形も確かめる。"""
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                result = json.loads(line[len(RESULT_PREFIX):])
            except ValueError as error:
                raise SandboxError("結果のJSONを読めません") from error
            if not isinstance(result, dict) or not isinstance(result.get("status"), str):
                raise SandboxError("結果の形が正しくありません")
            return result
    raise SandboxError("結果の行がありません")


class LocalDevSandbox:
    """開発用。自作の合成データだけに使う。隔離はしないので本番では起動させない。"""

    def __init__(self) -> None:
        if os.environ.get("APP_ENV") != "local" or os.environ.get("ALLOW_LOCAL_SANDBOX") != "1":
            raise SandboxError("LocalDevSandbox は APP_ENV=local かつ ALLOW_LOCAL_SANDBOX=1 のときだけ使えます")

    def analyze(self, student_code: str, stdin: str) -> dict:
        return self._execute(student_code, {**DEFAULT_REQUEST, "stdin": stdin})

    def probe(self, student_code: str, probes: list[dict]) -> dict:
        return self._execute(student_code, probe_request(probes))

    def _execute(self, student_code: str, request: dict) -> dict:
        with tempfile.TemporaryDirectory(prefix="sandbox-") as folder:
            Path(folder, "student.py").write_text(student_code, encoding="utf-8")
            Path(folder, "request.json").write_text(json.dumps(request), encoding="utf-8")
            try:
                done = subprocess.run(
                    [sys.executable, "-I", "-c", HARNESS_SOURCE],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=request["deadline_sec"] + 15,
                    cwd=folder,
                    # SESSION_SECRET などの環境変数を、生徒のコードが動く側に渡さない
                    env=HARNESS_ENV,
                )
            except subprocess.TimeoutExpired as error:
                raise SandboxError("実行ラッパーが時間内に終わりませんでした") from error
        if done.returncode != 0:
            raise SandboxError("実行ラッパーが失敗しました: " + done.stderr[-300:])
        return parse_result(done.stdout)


class CodeExecutionSandbox:
    """Gemini Enterprise Agent Platform の Code Execution。提出ごとに sandbox を作って消す。"""

    def __init__(self, project: str, location: str = "asia-northeast1", runtime_name: str | None = None) -> None:
        import agentplatform  # 重い依存なので使うときだけ読み込む

        self._client = agentplatform.Client(project=project, location=location)
        self._runtime_name = runtime_name

    def _runtime(self) -> str:
        if not self._runtime_name:
            self._runtime_name = self._client.runtimes.create().api_resource.name
        return self._runtime_name

    def analyze(self, student_code: str, stdin: str) -> dict:
        return self._execute(student_code, {**DEFAULT_REQUEST, "stdin": stdin})

    def probe(self, student_code: str, probes: list[dict]) -> dict:
        return self._execute(student_code, probe_request(probes))

    def _execute(self, student_code: str, request: dict) -> dict:
        from agentplatform import types

        operation = self._client.sandboxes.create(
            spec={"code_execution_environment": {}},
            name=self._runtime(),
            config=types.CreateRuntimeSandboxConfig(display_name="mushitori-run", ttl="300s"),
        )
        sandbox = operation.response.name
        try:
            response = self._client.sandboxes.execute_code(
                name=sandbox,
                input_data={
                    "code": HARNESS_SOURCE,
                    "files": [
                        {"name": "student.py", "content": student_code.encode("utf-8")},
                        {"name": "request.json", "content": json.dumps(request).encode("utf-8")},
                    ],
                },
            )
        finally:
            self._client.sandboxes.delete(name=sandbox)
        for chunk in response.outputs or []:
            if chunk.mime_type == "application/json":
                payload = json.loads(chunk.data.decode("utf-8"))
                if payload.get("exit_status_int") != 0:
                    raise SandboxError("実行ラッパーが失敗しました: " + str(payload.get("msg_err", ""))[-300:])
                return parse_result(payload.get("msg_out", ""))
        raise SandboxError("Code Execution の応答に結果がありません")


def default_sandbox() -> Sandbox:
    """環境変数から実行環境を選ぶ。指定がなければ隔離された本番用を使う。"""
    if os.environ.get("SANDBOX_BACKEND", "code_execution") == "local":
        return LocalDevSandbox()
    return CodeExecutionSandbox(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("SANDBOX_LOCATION", "asia-northeast1"),
        runtime_name=os.environ.get("SANDBOX_RUNTIME_NAME"),
    )
