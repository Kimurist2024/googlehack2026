"""保存先の試験。メモリ版と Firestore 版が同じ動きをすることを確かめる。"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.store import AssignmentRecord, ClassRecord

STALE = 100.0


def run_together(count, work):
    barrier = threading.Barrier(count)

    def task(index):
        barrier.wait()
        return work(index)

    with ThreadPoolExecutor(count) as pool:
        return list(pool.map(task, range(count)))


def unique(prefix: str) -> str:
    return f"{prefix}-{os.urandom(8).hex()}"


def make_class(store) -> ClassRecord:
    classroom = ClassRecord(unique("class"), "1-A", "teacher", {"s1": "1", "s2": "2"})
    store.create_class(classroom, unique("code"), {unique("hash"): "s1"})
    return classroom


def make_assignment(store, class_id: str, state: str = "draft") -> str:
    assignment_id = unique("assignment")
    store.create_assignment(AssignmentRecord(assignment_id, class_id, "合計", "", [], 300, 3, {"output": 1.0}))
    if state in ("ready", "open"):
        assert store.begin_generation(assignment_id, 0.0, STALE)
        store.end_generation(assignment_id, "ready")
    if state == "open":
        assert store.open_assignment(assignment_id)
    return assignment_id


def test_class_is_found_only_by_its_codes(store):
    classroom = ClassRecord(unique("class"), "1-A", "teacher", {"s1": "1"})
    class_code, personal_code = unique("code"), unique("hash")
    store.create_class(classroom, class_code, {personal_code: "s1"})
    assert store.get_class(classroom.id) == classroom
    assert store.class_id_for_code(class_code) == classroom.id
    assert store.student_for_credential(classroom.id, personal_code) == "s1"
    assert store.get_class(unique("class")) is None
    assert store.class_id_for_code(unique("code")) is None
    assert store.student_for_credential(classroom.id, class_code) is None


def test_class_keeps_the_roster_order(store):
    classroom = ClassRecord(unique("class"), "1-A", "teacher", {"z": "1", "a": "2", "m": "10", "b": "3"})
    store.create_class(classroom, unique("code"), {})
    assert list(store.get_class(classroom.id).student_numbers.values()) == ["1", "2", "10", "3"]


def test_changing_a_returned_value_does_not_change_the_store(store):
    classroom = make_class(store)
    store.get_class(classroom.id).student_numbers["s9"] = "9"
    assert "s9" not in store.get_class(classroom.id).student_numbers
    assignment_id = make_assignment(store, classroom.id)
    store.add_submissions(assignment_id, {"s1": "print(1)\n"})
    store.submissions(assignment_id)["s1"]["status"] = "ready"
    assert store.submissions(assignment_id)["s1"]["status"] == "queued"


def test_assignment_round_trip_keeps_every_field(store):
    classroom = make_class(store)
    record = AssignmentRecord(unique("assignment"), classroom.id, "合計", "繰り返し", ["1\n"], 120, 2, {"output": 1.0, "trace": 2.0})
    store.create_assignment(record)
    assert store.get_assignment(record.id) == record
    assert store.get_assignment(unique("assignment")) is None


def test_only_one_assignment_is_open_per_class(store):
    classroom = make_class(store)
    first = make_assignment(store, classroom.id, "ready")
    second = make_assignment(store, classroom.id, "ready")
    assert store.open_assignment(first)
    assert not store.open_assignment(second)
    assert store.get_class(classroom.id).open_assignment_id == first
    assert store.close_assignment(first)
    assert store.get_class(classroom.id).open_assignment_id is None
    assert store.open_assignment(second)


def test_open_and_close_require_the_right_state(store):
    classroom = make_class(store)
    draft = make_assignment(store, classroom.id)
    assert not store.open_assignment(draft)
    assert not store.close_assignment(draft)
    assert store.get_assignment(draft).state == "draft"


def test_opening_at_the_same_time_lets_one_win(store):
    classroom = make_class(store)
    assignments = [make_assignment(store, classroom.id, "ready") for _ in range(2)]
    results = run_together(2, lambda index: store.open_assignment(assignments[index]))
    assert sorted(results) == [False, True]
    winner = assignments[results.index(True)]
    assert store.get_class(classroom.id).open_assignment_id == winner
    assert [store.get_assignment(a).state for a in assignments].count("open") == 1


def test_generation_starts_once_and_restarts_when_stuck(store):
    assignment_id = make_assignment(store, make_class(store).id)
    assert store.begin_generation(assignment_id, 1000.0, STALE)
    assert store.get_assignment(assignment_id).generating_since == 1000.0
    assert not store.begin_generation(assignment_id, 1000.0 + STALE, STALE)
    assert store.begin_generation(assignment_id, 1001.0 + STALE, STALE)
    store.end_generation(assignment_id, "ready")
    assert store.get_assignment(assignment_id).generating_since is None
    assert store.begin_generation(assignment_id, 2000.0, STALE)


def test_generation_started_at_the_same_time_lets_one_win(store):
    assignment_id = make_assignment(store, make_class(store).id)
    results = run_together(4, lambda _: store.begin_generation(assignment_id, 1000.0, STALE))
    assert results.count(True) == 1


def test_generation_cannot_start_once_open(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    assert not store.begin_generation(assignment_id, 1e12, STALE)


def test_submissions_are_refused_once_open(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    assert not store.add_submissions(assignment_id, {"s1": "print(1)\n"})
    assert store.submissions(assignment_id) == {}
    assert store.get_assignment(assignment_id).state == "open"


def test_submissions_return_to_draft_and_replace_the_old_code(store):
    assignment_id = make_assignment(store, make_class(store).id, "ready")
    assert store.add_submissions(assignment_id, {"s1": "print(1)\n", "s2": "print(2)\n"})
    assert store.get_assignment(assignment_id).state == "draft"
    assert store.add_submissions(assignment_id, {"s1": "print(3)\n"})
    submissions = store.submissions(assignment_id)
    assert submissions["s1"]["code"] == "print(3)\n" and submissions["s2"]["code"] == "print(2)\n"


def test_status_views_leave_out_the_code_and_empty_counts(store):
    assignment_id = make_assignment(store, make_class(store).id)
    assert store.submission_counts(assignment_id) == {}
    store.add_submissions(assignment_id, {"s1": "print(1)\n", "s2": "print(2)\n"})
    store.save_generation_result(assignment_id, "s2", "excluded", "timeout", None, None)
    assert store.submission_statuses(assignment_id) == {
        "s1": {"status": "queued", "reason": None},
        "s2": {"status": "excluded", "reason": "timeout"},
    }
    assert store.submission_counts(assignment_id) == {"queued": 1, "excluded": 1}


def test_failed_regeneration_leaves_no_old_quiz(store):
    assignment_id = make_assignment(store, make_class(store).id)
    store.add_submissions(assignment_id, {"s1": "print(1)\n"})
    quiz = {"questions": [{"id": "output-1", "options": ["1", "2"]}], "code": "print(1)\n", "stdin": ""}
    key = {"questions": {"output-1": {"answer": "1", "line": None, "trace": []}}, "trace": ["1行目: x = 1"]}
    store.save_generation_result(assignment_id, "s1", "ready", None, quiz, key)
    assert store.get_quiz(assignment_id, "s1") == quiz
    assert store.get_answer_key(assignment_id, "s1") == key
    store.save_generation_result(assignment_id, "s1", "excluded", "timeout", None, None)
    assert store.get_quiz(assignment_id, "s1") is None
    assert store.get_answer_key(assignment_id, "s1") is None


def test_restarting_an_attempt_keeps_the_first_clock(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    assert store.get_attempt(assignment_id, "s1") is None
    assert store.start_attempt(assignment_id, "s1", 100.0)["started_at"] == 100.0
    assert store.start_attempt(assignment_id, "s1", 200.0)["started_at"] == 100.0
    assert store.get_attempt(assignment_id, "s1") == {"started_at": 100.0, "submitted_at": None, "graded": []}


def test_starting_at_the_same_time_keeps_one_clock(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    attempts = run_together(4, lambda index: store.start_attempt(assignment_id, "s1", 100.0 + index))
    assert len({attempt["started_at"] for attempt in attempts}) == 1


def test_attempt_is_finished_only_once(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    graded = [{"id": "output-1", "correct": True, "given": "1", "answer": "1"}]
    assert not store.finish_attempt(assignment_id, "s1", graded, 110.0)
    store.start_attempt(assignment_id, "s1", 100.0)
    assert store.finish_attempt(assignment_id, "s1", graded, 110.0)
    assert not store.finish_attempt(assignment_id, "s1", [], 120.0)
    assert store.attempts(assignment_id) == {"s1": {"started_at": 100.0, "submitted_at": 110.0, "graded": graded}}


def test_finishing_at_the_same_time_lets_one_win(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    store.start_attempt(assignment_id, "s1", 100.0)
    results = run_together(4, lambda index: store.finish_attempt(assignment_id, "s1", [{"index": index}], 110.0 + index))
    assert results.count(True) == 1
    winner = results.index(True)
    assert store.get_attempt(assignment_id, "s1")["graded"] == [{"index": winner}]


def test_followup_question_and_action_are_merged(store):
    assignment_id = make_assignment(store, make_class(store).id)
    review = {"overview": "記録は今回が最初です。", "spots": [{"line": 3, "question": "3行目はどう変わりますか。"}], "by": "template"}
    store.add_followup(assignment_id, "s1", "3行目はどう変わりますか。", 3, review)
    store.record_action(assignment_id, "s1", {"action": "ask_in_class", "reason": "", "duration_ms": 1000, "by": "teacher"})
    store.record_action(assignment_id, "s2", {"action": "no_problem", "reason": "説明できた", "duration_ms": 0, "by": "teacher"})
    followups = store.followups(assignment_id)
    assert followups["s1"]["question"] == "3行目はどう変わりますか。" and followups["s1"]["line"] == 3
    assert followups["s1"]["review"] == review and followups["s1"]["action"] == "ask_in_class"
    assert followups["s2"]["reason"] == "説明できた" and "question" not in followups["s2"]


def entry(assignment_id: str, closed_at: float, **extra) -> dict:
    return {"assignment_id": assignment_id, "title": assignment_id, "closed_at": closed_at, "score": 1, "total": 3, "spots": [], **extra}


def test_student_record_keeps_one_entry_per_assignment_in_closing_order(store):
    class_id = make_class(store).id
    assert store.get_student_record(class_id, "s1") is None
    store.save_student_entry(class_id, "s1", entry("a2", 200.0))
    store.save_student_entry(class_id, "s1", entry("a1", 100.0))
    store.save_student_entry(class_id, "s1", entry("a2", 200.0, score=3))
    entries = store.get_student_record(class_id, "s1")["entries"]
    assert [item["assignment_id"] for item in entries] == ["a1", "a2"] and entries[1]["score"] == 3
    assert store.get_student_record(class_id, "s2") is None


def test_student_record_drops_the_oldest_entries(store, monkeypatch):
    monkeypatch.setattr("app.store.MAX_ENTRIES", 2)
    class_id = make_class(store).id
    for index in range(3):
        store.save_student_entry(class_id, "s1", entry(f"a{index}", float(index)))
    assert [item["assignment_id"] for item in store.get_student_record(class_id, "s1")["entries"]] == ["a1", "a2"]


def test_teacher_action_is_written_into_the_matching_entry(store):
    class_id = make_class(store).id
    store.set_entry_action(class_id, "s1", "a1", {"action": "explained", "reason": ""})  # 記録がなくても失敗しない
    store.save_student_entry(class_id, "s1", entry("a1", 100.0, action=None))
    store.save_student_entry(class_id, "s1", entry("a2", 200.0, action=None))
    store.set_entry_action(class_id, "s1", "a1", {"action": "explained", "reason": ""})
    entries = store.get_student_record(class_id, "s1")["entries"]
    assert entries[0]["action"] == {"action": "explained", "reason": ""} and entries[1]["action"] is None


def test_explanations_are_kept_only_after_submitting(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    assert store.save_explanation(assignment_id, "s1", 3, "合計に足す") is False
    store.start_attempt(assignment_id, "s1", 100.0)
    assert store.save_explanation(assignment_id, "s1", 3, "合計に足す") is False
    store.finish_attempt(assignment_id, "s1", [], 110.0)
    assert store.save_explanation(assignment_id, "s1", 3, "合計に足す") is True
    assert store.save_explanation(assignment_id, "s1", 5, "条件を確かめる") is True
    assert store.save_explanation(assignment_id, "s1", 3, "60点以上だけ合計に足す") is True
    assert store.get_attempt(assignment_id, "s1")["explanations"] == {"3": "60点以上だけ合計に足す", "5": "条件を確かめる"}


def test_class_summary_is_saved_on_the_assignment(store):
    assignment_id = make_assignment(store, make_class(store).id)
    assert store.get_assignment(assignment_id).class_summary is None
    summary = {"points": ["a", "b"], "by": "template", "stats": [{"type": "trace", "answered": 3, "wrong": 1}], "students": 3}
    store.set_class_summary(assignment_id, summary)
    assert store.get_assignment(assignment_id).class_summary == summary


def test_chat_turns_are_limited_per_attempt(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    assert store.use_chat_turn(assignment_id, "s1", 2) is None
    store.start_attempt(assignment_id, "s1", 100.0)
    assert [store.use_chat_turn(assignment_id, "s1", 2) for _ in range(3)] == [1, 0, None]


def test_explanation_checks_are_limited_per_attempt(store):
    """説明を確かめる回数は、振り返りの質問とは別に数える。"""
    assignment_id = make_assignment(store, make_class(store).id, "open")
    assert store.use_explanation_check(assignment_id, "s1", 2) is None
    store.start_attempt(assignment_id, "s1", 100.0)
    assert store.use_chat_turn(assignment_id, "s1", 2) == 1
    assert [store.use_explanation_check(assignment_id, "s1", 2) for _ in range(3)] == [1, 0, None]
    assert store.use_chat_turn(assignment_id, "s1", 2) == 0


def test_explanation_checks_used_at_the_same_time_do_not_exceed_the_limit(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    store.start_attempt(assignment_id, "s1", 100.0)
    results = run_together(4, lambda _: store.use_explanation_check(assignment_id, "s1", 2))
    assert sorted(r for r in results if r is not None) == [0, 1] and results.count(None) == 2


def test_chat_turns_used_at_the_same_time_do_not_exceed_the_limit(store):
    assignment_id = make_assignment(store, make_class(store).id, "open")
    store.start_attempt(assignment_id, "s1", 100.0)
    results = run_together(4, lambda _: store.use_chat_turn(assignment_id, "s1", 2))
    assert sorted(r for r in results if r is not None) == [0, 1] and results.count(None) == 2


@pytest.mark.skipif(not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="エミュレータが必要")
def test_rules_refuse_browser_access():
    # 認証なしの REST はブラウザと同じ扱いで、firestore.rules が適用される
    base = f"http://{os.environ['FIRESTORE_EMULATOR_HOST']}/v1/projects/demo-mushitori/databases/(default)/documents"
    assert httpx.get(f"{base}/classes/x").status_code == 403
    assert httpx.get(f"{base}/assignments/x/answerKeys/y").status_code == 403
    assert httpx.patch(f"{base}/classes/x", json={"fields": {}}).status_code == 403


def test_guest_usage_is_counted_per_key_and_together(store):
    key, other = unique("generate-1"), unique("generate-1")
    assert store.usage_count(key) == 0
    run_together(4, lambda _: store.add_usage(key, expire_at=10_000_000_000))
    store.add_usage(other, expire_at=10_000_000_000)
    assert store.usage_count(key) == 4
    assert store.usage_count(other) == 1
