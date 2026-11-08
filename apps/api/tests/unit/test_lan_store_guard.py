"""校内LAN版の保存先（LanStore）が、書き換えをすべてファイルに残すことの試験。

LanStore は MemoryStore の書き換える操作を、名前の一覧（lan_store.MUTATING）で包んで保存する。
MemoryStore に書き換える操作を足して一覧に入れ忘れると、教員PCを再起動したときにその分が消えるので、ここで見つける。
"""
import copy
import inspect
import os

from app import lan_store
from app.lan_store import LanStore
from app.store import AssignmentRecord, ClassRecord, MemoryStore

# 書き換える操作を1回ずつ、意味の通る順に呼ぶ。MUTATING の名前がすべて1回ずつ出てくる
STEPS = [
    ("create_class", (ClassRecord("c1", "1-A", "teacher", {"s1": "1", "s2": "2"}), "class-hash", {"personal-hash": "s1"})),
    ("save_offline_verifiers", ("c1", {"class": "verifier"})),
    ("create_assignment", (AssignmentRecord("a1", "c1", "合計", "", [], 300, 3, {"output": 1.0}),)),
    ("add_submissions", ("a1", {"s1": "print(1)\n", "s2": "print(2)\n"})),
    ("begin_generation", ("a1", 0.0, 100.0)),
    ("save_generation_result", ("a1", "s1", "ready", None, {"questions": [{"id": "q1"}]}, {"q1": "1", "trace": []})),
    ("end_generation", ("a1", "ready")),
    ("open_assignment", ("a1",)),
    ("start_attempt", ("a1", "s1", 1.0)),
    ("finish_attempt", ("a1", "s1", [{"id": "q1", "given": "1", "correct": True}], 2.0)),
    ("use_chat_turn", ("a1", "s1", 3)),
    ("save_explanation", ("a1", "s1", 1, "1を表示する")),
    ("close_assignment", ("a1",)),
    ("add_followup", ("a1", "s1", "1行目は何をしていますか", 1, None)),
    ("record_action", ("a1", "s1", {"action": "explained", "reason": "", "duration_ms": 10})),
    ("set_class_summary", ("a1", {"by": "template", "stats": []})),
    ("save_student_entry", ("c1", "s1", {"assignment_id": "a1", "closed_at": 3.0, "score": 1, "total": 1})),
    ("set_entry_action", ("c1", "s1", "a1", {"action": "explained"})),
    ("add_login_failure", ("client", 1, 180.0)),
    ("add_usage", ("generate-1", 172800.0)),
    ("remove_entries", ("c1", "a1")),
    ("delete_assignment", ("a1",)),
    ("delete_class", ("c1",)),
]

# 読むだけの操作と、それを呼ぶときの引数。ここにも MUTATING にもない操作を MemoryStore に足すと、下の試験が落ちる
READS = {
    "get_class": ("c1",),
    "class_id_for_code": ("class-hash",),
    "student_for_credential": ("c1", "personal-hash"),
    "get_assignment": ("a1",),
    "submissions": ("a1",),
    "submission_statuses": ("a1",),
    "submission_counts": ("a1",),
    "get_quiz": ("a1", "s1"),
    "get_answer_key": ("a1", "s1"),
    "get_attempt": ("a1", "s1"),
    "attempts": ("a1",),
    "followups": ("a1",),
    "get_student_record": ("c1", "s1"),
    "login_failures": ("client", 1),
    "usage_count": ("generate-1",),
    "offline_verifiers": ("c1",),
}
REMOVING = ("remove_entries", "delete_assignment", "delete_class")


def store_operations() -> set[str]:
    """MemoryStore の公開メソッドの名前をすべて集める。"""
    return {name for name, _ in inspect.getmembers(MemoryStore, inspect.isfunction) if not name.startswith("_")}


def state(store: MemoryStore) -> dict:
    """ロック以外の中身をすべて写す。"""
    return {name: copy.deepcopy(value) for name, value in vars(store).items() if name != "_lock"}


def test_every_store_operation_is_listed_as_mutating_or_read_only():
    assert len(set(lan_store.MUTATING)) == len(lan_store.MUTATING)
    assert set(lan_store.MUTATING).isdisjoint(READS)
    assert store_operations() == set(lan_store.MUTATING) | set(READS)
    assert sorted(name for name, _ in STEPS) == sorted(lan_store.MUTATING)


def test_read_only_operations_change_nothing():
    store = MemoryStore()
    for name, args in STEPS:
        if name not in REMOVING:
            getattr(store, name)(*args)
    before = state(store)
    for name, args in READS.items():
        getattr(store, name)(*args)
        assert state(store) == before, name


def test_lan_store_writes_each_mutating_operation_to_the_file(tmp_path):
    key = os.urandom(32)
    store = LanStore(tmp_path / "store.bin", key)
    for name, args in STEPS:
        getattr(store, name)(*args)
        reopened = LanStore(tmp_path / "store.bin", key)
        assert reopened._snapshot() == store._snapshot(), name
