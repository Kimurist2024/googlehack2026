"""クラウド版と校内LAN版で共通の入力の型と上限。"""
from typing import Annotated

from fastapi import Path as PathParam
from pydantic import StringConstraints

# サーバーが作るID（secrets.token_hex(8)）の形。これ以外は保存先に問い合わせる前に断る
ID_PATTERN = r"^[0-9a-f]{16}$"
MAX_ANSWERS = 10
MAX_ANSWER_CHARS = 20_000
GENERATION_STALE_SEC = 30 * 60
REASON_CHARS = 400
MAX_DURATION_MS = 3_600_000
CLOCK_SKEW_SEC = 300

ResourceId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
AssignmentId = Annotated[str, PathParam(pattern=ID_PATTERN)]
ClassId = Annotated[str, PathParam(pattern=ID_PATTERN)]
StudentId = Annotated[str, PathParam(pattern=ID_PATTERN)]
AnswerKey = Annotated[str, StringConstraints(max_length=64)]
AnswerText = Annotated[str, StringConstraints(max_length=MAX_ANSWER_CHARS)]
