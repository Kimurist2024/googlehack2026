#!/usr/bin/env bash
# 提出用リポジトリ（Devfest-Hackathon-2026/df-2026-t032）に、開発リポジトリの今の内容を
# 「履歴なしの1コミット」として置く。運営の README のとおり、開発の履歴ごとは push しない
# （過去のコミットに紛れた秘密情報や、開発の都合のメッセージを公開リポジトリに持ち込まないため）。
#
# 使い方:
#   git clone https://github.com/Devfest-Hackathon-2026/df-2026-t032 ../df-2026-t032
#   scripts/export_submission.sh ../df-2026-t032
#   （内容を確かめてから） git -C ../df-2026-t032 push origin main
#
# この script は push しない。コミットの作者は実行した人の git 設定、ほかのメンバーは
# 開発リポジトリの履歴から Co-authored-by として付ける（GitHub で全員が貢献者に出る）。
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
DEST=${1:?使い方: scripts/export_submission.sh <提出用リポジトリの clone 先>}
DEST=$(cd "$DEST" && pwd)

[ -d "$DEST/.git" ] || { echo "clone 先に .git がありません: $DEST" >&2; exit 1; }
git -C "$DEST" remote get-url origin | grep -qi 'Devfest-Hackathon-2026/df-2026-t032' \
  || { echo "origin が提出用リポジトリ（Devfest-Hackathon-2026/df-2026-t032）ではありません" >&2; exit 1; }
[ -z "$(git -C "$SRC" status --porcelain)" ] || { echo "開発リポジトリに未コミットの変更があります。先にコミットするか戻してください" >&2; exit 1; }

echo "== 秘密らしき文字列がないか（追跡しているファイル）"
if git -C "$SRC" grep -nIE 'AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|"private_key"|ya29\.[0-9A-Za-z_-]{20,}' -- . ':(exclude)scripts/export_submission.sh' ':(exclude)docs/submission-checklist.md'; then
  echo "上の行を確かめてください。止めます" >&2; exit 1
fi
echo "   なし"

echo "== 提出用リポジトリの中身を入れ替える"
ORIGINAL_IGNORE=$(mktemp); ORIGINAL_LICENSE=$(mktemp)
[ -f "$DEST/.gitignore" ] && cp "$DEST/.gitignore" "$ORIGINAL_IGNORE"
[ -f "$DEST/LICENSE" ] && cp "$DEST/LICENSE" "$ORIGINAL_LICENSE"
git -C "$DEST" rm -rq --ignore-unmatch . >/dev/null
git -C "$SRC" archive --format=tar HEAD | tar -x -C "$DEST"

# 提出に要らないもの（開発の進め方の記録）は置かない。README の「このリポジトリは開発用です」の注意書きも外す
rm -f "$DEST/docs/submission-checklist.md"
sed -i '/^> \[!NOTE\]$/{N;/開発用です/d}' "$DEST/README.md"
sed -i '/submission-checklist\.md/d' "$DEST/docs/README.md"

# 運営の .gitignore（秘密情報の形式）はこちらの .gitignore に足す。運営の LICENSE（MIT）は、こちらに無ければ残す
if [ -s "$ORIGINAL_IGNORE" ]; then
  { echo; echo "# 提出用リポジトリの既定（運営の .gitignore）"; grep -vxFf "$DEST/.gitignore" "$ORIGINAL_IGNORE" || true; } >> "$DEST/.gitignore"
fi
[ -f "$DEST/LICENSE" ] || { [ -s "$ORIGINAL_LICENSE" ] && cp "$ORIGINAL_LICENSE" "$DEST/LICENSE"; }
rm -f "$ORIGINAL_IGNORE" "$ORIGINAL_LICENSE"

echo "== コミットする（履歴は持ち込まない）"
ME=$(git -C "$DEST" config user.email || true)
COAUTHORS=$(git -C "$SRC" shortlog -sne HEAD | sed -E 's/^ *[0-9]+\t//' | grep -v -F "${ME:-@@none@@}" | sed 's/^/Co-authored-by: /' || true)
SHA=$(git -C "$SRC" rev-parse --short HEAD)
git -C "$DEST" add -A
git -C "$DEST" commit -q -F - <<EOF
ムシトリ 最終提出（$(date +%Y-%m-%d)）

開発リポジトリ https://github.com/Kimurist2024/googlehack2026 の $SHA の内容。
${COAUTHORS}
EOF

echo
git -C "$DEST" log -1 --stat | head -20
echo
echo "確かめてから push してください:  git -C $DEST push origin $(git -C "$DEST" branch --show-current)"
