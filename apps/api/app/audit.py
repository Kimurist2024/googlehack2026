"""監査の記録。Cloud Logging が読める JSON を1行ずつ標準出力に書く。

誰が、いつ、何をしたかを残す。コード（授業・個人）、トークン、生徒のコードは決して書かない。
接続元は生のアドレスではなく、鍵付きハッシュで記録する。
"""
import json
import os
import sys
import time

from fastapi import Request

# 記録に入れてよい項目。これ以外の名前を渡すと書く前に落とす（秘密を誤って記録しないため）
ALLOWED_FIELDS = {
    "principal",
    "class_id",
    "assignment_id",
    "student_id",
    "client",
    "reason",
    "count",
    "problems",
    "action",
    "forwarded",
}


def _trace(request: Request | None) -> dict:
    """Cloud Run のリクエストログと同じトレースに結びつける。"""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    header = request.headers.get("x-cloud-trace-context", "") if request is not None else ""
    trace_id = header.split("/", 1)[0]
    if not project or not trace_id.isalnum() or len(trace_id) > 64:
        return {}
    return {"logging.googleapis.com/trace": f"projects/{project}/traces/{trace_id}"}


def event(name: str, request: Request | None = None, severity: str = "NOTICE", **fields) -> None:
    unknown = set(fields) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"監査の記録に使えない項目です: {sorted(unknown)}")
    entry = {
        "severity": severity,
        "message": f"audit {name}",
        "audit": {"event": name, **{key: value for key, value in fields.items() if value is not None}},
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **_trace(request),
    }
    sys.stdout.write(json.dumps(entry, ensure_ascii=False) + "\n")
    sys.stdout.flush()
