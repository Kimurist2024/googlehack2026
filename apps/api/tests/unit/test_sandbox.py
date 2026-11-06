"""実行環境の切り替えと結果の読み取りの試験。コードは実行しない。"""
import pytest

from qgen.sandbox import LocalDevSandbox, SandboxError, parse_result


def test_local_sandbox_refuses_outside_local(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_SANDBOX", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SandboxError):
        LocalDevSandbox()


@pytest.mark.parametrize("stdout", ["", "no result", "HARNESS_RESULT:not json", "HARNESS_RESULT:[1]", 'HARNESS_RESULT:{"a":1}'])
def test_parse_result_rejects_malformed_output(stdout):
    with pytest.raises(SandboxError):
        parse_result(stdout)
