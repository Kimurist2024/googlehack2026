"""クラウド版と校内LAN版で共通の入力の型と上限。"""
from typing import Annotated, Literal, get_args

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

# 教員が声かけのあとに記録する処置。クラウドでも校内LANでも、結果の取り込みでも同じものを使う。
# explained と not_explained は、質問案で聞いた結果。生徒の記録に残り、次の課題の材料になる
Action = Literal["explained", "not_explained", "ask_in_class", "no_problem", "question_bad"]
ACTIONS = set(get_args(Action))

ResourceId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
AssignmentId = Annotated[str, PathParam(pattern=ID_PATTERN)]
ClassId = Annotated[str, PathParam(pattern=ID_PATTERN)]
StudentId = Annotated[str, PathParam(pattern=ID_PATTERN)]
AnswerKey = Annotated[str, StringConstraints(max_length=64)]
AnswerText = Annotated[str, StringConstraints(max_length=MAX_ANSWER_CHARS)]
