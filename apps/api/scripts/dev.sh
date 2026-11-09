#!/bin/sh
# ローカル開発用の起動。合成データ専用で、生徒のコードを隔離せずに動かす。
# 実在の提出物には絶対に使わない。127.0.0.1 だけで待ち受ける。
set -eu
# --rsi-test を付けると「RSIテスト」のタブ（保存済みの合成データの記録の再生）を出す
for arg in "$@"; do
  case "$arg" in
    --rsi-test) export RSI_TEST=1 ;;
    *) echo "知らないオプションです: $arg（使えるのは --rsi-test）" >&2; exit 2 ;;
  esac
done
cd "$(dirname "$0")/.."
# 仮想環境は apps/api/.venv か、リポジトリ直下の .venv を使う
VENV=.venv
[ -d "$VENV" ] || VENV=../../.venv
export APP_ENV=local
export SERVE_WEB=1
export SANDBOX_BACKEND=local
export ALLOW_LOCAL_SANDBOX=1
export AI_BACKEND=template
export STORE_BACKEND=memory
SESSION_SECRET="${SESSION_SECRET:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
export SESSION_SECRET
exec "$VENV/bin/uvicorn" --factory app.main:create_app --host 127.0.0.1 --port "${PORT:-8000}" --no-server-header
