"""結合テスト専用の準備。合成コードを手元で実際に動かすので、単体テストからは使えない場所に置く。

FIRESTORE_EMULATOR_HOST があれば、保存先を使う試験をメモリとエミュレータの両方で動かす。
本物の Firestore には接続しない。
"""
import os
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import MemoryStore
from qgen.ai import TemplateAI
from qgen.sandbox import LocalDevSandbox

BACKENDS = ["memory", "firestore"] if os.environ.get("FIRESTORE_EMULATOR_HOST") else ["memory"]
EMULATOR_PROJECT = "demo-mushitori"  # demo- で始まるプロジェクトはクラウドに接続しない


def clear_emulator() -> None:
    """エミュレータの中身を消す。入室の失敗の回数のように、試験をまたいで残ると結果が変わるものがある。"""
    host = os.environ["FIRESTORE_EMULATOR_HOST"]
    url = f"http://{host}/emulator/v1/projects/{EMULATOR_PROJECT}/databases/(default)/documents"
    urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=10).close()


@pytest.fixture(params=BACKENDS)
def store(request):
    if request.param == "memory":
        return MemoryStore()
    from app.firestore_store import FirestoreStore

    clear_emulator()
    return FirestoreStore(project=EMULATOR_PROJECT)


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
    return LocalDevSandbox()


@pytest.fixture
def client(monkeypatch, store):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    return TestClient(create_app(store, LocalDevSandbox, TemplateAI))
