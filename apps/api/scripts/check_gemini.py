"""Vertex AI（Agent Platform）経由で Gemini を1回だけ呼んで、つながるかを確かめる。

    GOOGLE_CLOUD_PROJECT=<プロジェクトID> .venv/bin/python scripts/check_gemini.py [モデル名 ...]

生徒のデータは送らない。決まった短い文だけを送る。API キーは使わず、
gcloud auth application-default login で作った認証情報を使う。
"""
import os
import sys

DEFAULT_MODELS = [os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"), os.environ.get("RSI_PROPOSER_MODEL", "gemini-3.1-pro-preview")]


def main(argv: list[str]) -> int:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("GOOGLE_CLOUD_PROJECT を指定してください", file=sys.stderr)
        return 2
    try:
        import google.auth
        from google import genai
    except ImportError:
        print("requirements-gcp.txt を入れてください: .venv/bin/pip install -r requirements-gcp.txt", file=sys.stderr)
        return 2
    try:
        _, detected = google.auth.default()
    except Exception as error:
        print(f"認証情報がありません。gcloud auth application-default login を実行してください（{type(error).__name__}）", file=sys.stderr)
        return 2
    print(f"プロジェクト: {project}（認証情報の既定のプロジェクト: {detected or 'なし'}）")

    client = genai.Client(enterprise=True, project=project, location=os.environ.get("GEMINI_LOCATION", "global"))
    failed = 0
    for model in argv or DEFAULT_MODELS:
        try:
            response = client.models.generate_content(model=model, contents="「OK」とだけ答えてください。")
            print(f"✓ {model}: {response.text.strip()[:40]}")
        except Exception as error:
            failed += 1
            print(f"✗ {model}: {type(error).__name__}: {str(error)[:300]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
