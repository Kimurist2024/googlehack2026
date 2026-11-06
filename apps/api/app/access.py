"""生徒の入室情報と課題の対応を確かめる。"""
from fastapi import HTTPException

from . import service
from .store import AssignmentRecord, Store, is_expired


def student_assignment(store: Store, assignment_id: str, claims: dict) -> AssignmentRecord:
    """入室したクラスの、期限内の課題だけを返す。"""
    assignment = store.get_assignment(assignment_id)
    if assignment is None or assignment.class_id != claims["class"] or is_expired(assignment, service.now()):
        raise HTTPException(status_code=404, detail="課題が見つかりません")
    return assignment
