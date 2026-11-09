"""生徒の入室情報と課題の対応を確かめる。"""
from fastapi import HTTPException

from . import auth, service
from .store import AssignmentRecord, ClassRecord, Store, is_expired


def student_session(classroom: ClassRecord, student_id: str) -> dict:
    """入室の応答。クラウド版と校内LAN版で同じ形にする。"""
    return {
        "token": auth.issue_student_token(classroom.id, student_id),
        "assignment_id": classroom.open_assignment_id,
        "number": classroom.student_numbers[student_id],
    }


def student_assignment(store: Store, assignment_id: str, claims: dict) -> AssignmentRecord:
    """入室したクラスの、期限内の課題だけを返す。"""
    assignment = store.get_assignment(assignment_id)
    if assignment is None or assignment.class_id != claims["class"] or is_expired(assignment, service.now()):
        raise HTTPException(status_code=404, detail="課題が見つかりません")
    return assignment
