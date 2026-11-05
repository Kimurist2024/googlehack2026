"""データの置き場所。今はメモリ上で持ち、Firestore 版は同じ形で差し替える。"""
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClassRecord:
    id: str
    name: str
    teacher: str
    student_numbers: dict[str, str]  # student_id -> 出席番号
    credentials: dict[str, str]  # 個人コードのハッシュ -> student_id


@dataclass
class AssignmentRecord:
    id: str
    class_id: str
    title: str
    learning_goal: str
    stdin_examples: list[str]
    time_limit_sec: int
    question_count: int
    weights: dict[str, float]
    state: str = "draft"  # draft, generating, ready, open, closed
    submissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    quizzes: dict[str, dict[str, Any]] = field(default_factory=dict)
    answer_keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    attempts: dict[str, dict[str, Any]] = field(default_factory=dict)
    followups: dict[str, dict[str, Any]] = field(default_factory=dict)


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.classes: dict[str, ClassRecord] = {}
        self.class_codes: dict[str, str] = {}  # 授業コードのハッシュ -> class_id
        self.assignments: dict[str, AssignmentRecord] = {}

    def open_assignment_for(self, class_id: str) -> str | None:
        with self.lock:
            for assignment in self.assignments.values():
                if assignment.class_id == class_id and assignment.state == "open":
                    return assignment.id
        return None
