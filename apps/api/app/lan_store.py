"""校内LAN版の保存先。教員PCのファイルに、暗号化して置く。

中身はメモリ版と同じで、書き換えるたびに全体を AES-256-GCM で暗号化して書き直す（1クラスの授業分なので小さい）。
鍵は別のファイルに置き、どちらも教員のアカウントだけが読める権限にする。
書き込みは一時ファイルに書いてから置き換えるので、途中で電源が落ちても前の状態が残る。
"""
import json
import os
import secrets
from dataclasses import asdict
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .store import AssignmentRecord, ClassRecord, MemoryStore

FORMAT = b"MUSHITORI-LAN-1"
MUTATING = (
    "create_class",
    "create_assignment",
    "add_submissions",
    "begin_generation",
    "end_generation",
    "save_generation_result",
    "open_assignment",
    "close_assignment",
    "start_attempt",
    "finish_attempt",
    "use_chat_turn",
    "save_explanation",
    "add_followup",
    "record_action",
    "set_class_summary",
    "save_student_entry",
    "set_entry_action",
    "remove_entries",
    "add_login_failure",
    "save_offline_verifiers",
    "delete_assignment",
    "delete_class",
)


def data_dir() -> Path:
    return Path(os.environ.get("LAN_DATA_DIR") or Path.home() / ".mushitori")


def _private_file(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_or_create_key(path: Path) -> bytes:
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise RuntimeError(f"{path} は鍵の形をしていません")
        return key
    key = secrets.token_bytes(32)
    _private_file(path, key)
    return key


class LanStore(MemoryStore):
    def __init__(self, path: Path, key: bytes) -> None:
        super().__init__()
        self._path = path
        self._aead = AESGCM(key)
        self._loading = True
        if path.exists():
            self._restore(self._decrypt(path.read_bytes()))
        self._loading = False

    @classmethod
    def open_default(cls) -> "LanStore":
        folder = data_dir()
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        return cls(folder / "store.bin", load_or_create_key(folder / "store.key"))

    def lan_classes(self) -> list[str]:
        with self._lock:
            return list(self._classes)

    # --- 保存と復元 ---

    def _snapshot(self) -> dict:
        return {
            "classes": {key: asdict(value) for key, value in self._classes.items()},
            "class_codes": self._class_codes,
            "credentials": [[class_id, code_hash, student_id] for (class_id, code_hash), student_id in self._credentials.items()],
            "assignments": {key: asdict(value) for key, value in self._assignments.items()},
            "submissions": self._submissions,
            "quizzes": self._quizzes,
            "answer_keys": self._answer_keys,
            "attempts": self._attempts,
            "followups": self._followups,
            "records": [[class_id, student_id, record] for (class_id, student_id), record in self._records.items()],
            "login_failures": [[client, window, count] for (client, window), count in self._login_failures.items()],
            "offline_verifiers": self._offline_verifiers,
        }

    def _restore(self, state: dict) -> None:
        self._classes = {key: ClassRecord(**value) for key, value in state["classes"].items()}
        self._class_codes = state["class_codes"]
        self._credentials = {(class_id, code_hash): student_id for class_id, code_hash, student_id in state["credentials"]}
        self._assignments = {key: AssignmentRecord(**value) for key, value in state["assignments"].items()}
        for name in ("submissions", "quizzes", "answer_keys", "attempts", "followups", "offline_verifiers"):
            setattr(self, f"_{name}", state[name])
        self._login_failures = {(client, window): count for client, window, count in state["login_failures"]}
        # 生徒ごとの記録を足す前に書いた保存ファイルにも対応する
        self._records = {(class_id, student_id): record for class_id, student_id, record in state.get("records", [])}

    def _decrypt(self, data: bytes) -> dict:
        if not data.startswith(FORMAT):
            raise RuntimeError(f"{self._path} は校内LAN版の保存ファイルではありません")
        body = data[len(FORMAT):]
        return json.loads(self._aead.decrypt(body[:12], body[12:], FORMAT))

    def _save(self) -> None:
        if self._loading:
            return
        nonce = secrets.token_bytes(12)
        plain = json.dumps(self._snapshot(), ensure_ascii=False).encode("utf-8")
        _private_file(self._path, FORMAT + nonce + self._aead.encrypt(nonce, plain, FORMAT))


def _persisting(name: str):
    original = getattr(MemoryStore, name)

    def method(self, *args, **kwargs):
        with self._lock:
            result = original(self, *args, **kwargs)
            self._save()
            return result

    method.__name__ = name
    method.__doc__ = original.__doc__
    return method


for _name in MUTATING:
    setattr(LanStore, _name, _persisting(_name))

