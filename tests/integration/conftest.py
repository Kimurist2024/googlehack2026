"""結合テスト専用の準備。合成コードを手元で実際に動かすので、単体テストからは使えない場所に置く。"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import Store
from qgen.ai import TemplateAI
from qgen.sandbox import LocalDevSandbox


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
    return LocalDevSandbox()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    return TestClient(create_app(Store(), LocalDevSandbox, TemplateAI))
