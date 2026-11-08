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
# 開発リポジトリの履歴から Co-authored-by として付ける（GitHub で貢献者に出る）。
# 公開リポジトリに個人のメールアドレスを出さないため、Co-authored-by には GitHub の noreply アドレス
# （…@users.noreply.github.com）のメンバーだけを付ける。実行する人の user.email も noreply にしておく。
# macOS（BSD）と Linux（GNU）のどちらの sed でも動くように、sed -i には必ず .bak を付けて後で消す。
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
DEST=${1:?使い方: scripts/export_submission.sh <提出用リポジトリの clone 先>}
DEST=$(cd "$DEST" && pwd)

[ -d "$DEST/.git" ] || { echo "clone 先に .git がありません: $DEST" >&2; exit 1; }
git -C "$DEST" remote get-url origin | grep -qi 'Devfest-Hackathon-2026/df-2026-t032' \
  || { echo "origin が提出用リポジトリ（Devfest-Hackathon-2026/df-2026-t032）ではありません" >&2; exit 1; }
[ -z "$(git -C "$SRC" status --porcelain)" ] || { echo "開発リポジトリに未コミットの変更があります。先にコミットするか戻してください" >&2; exit 1; }
# 提出するのは、いま開いているブランチの HEAD。どのブランチのどのコミットかを先に見せる
echo "== 提出元: $(git -C "$SRC" branch --show-current) $(git -C "$SRC" rev-parse --short HEAD)（$(git -C "$SRC" log -1 --format=%s)）"

echo "== 秘密らしき文字列がないか（追跡しているファイル）"
if git -C "$SRC" grep -nIE 'AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|"private_key"|ya29\.[0-9A-Za-z_-]{20,}' -- . ':(exclude)scripts/export_submission.sh' ':(exclude)docs/submission-checklist.md'; then
  echo "上の行を確かめてください。止めます" >&2; exit 1
fi
echo "   なし"

echo "== 個人情報らしき文字列がないか（個人のメールアドレス、手元の絶対パス）"
if git -C "$SRC" grep -nIE '@gmail\.com|@icloud\.com|@yahoo\.co\.jp|/Users/[A-Za-z]|/home/[a-z]' -- . ':(exclude)scripts/export_submission.sh'; then
  echo "上の行を確かめてください。止めます" >&2; exit 1
fi
echo "   なし"

echo "== README に書き残し（TODO）がないか"
if grep -n 'TODO' "$SRC/README.md"; then
  # 締切前の途中の反映だけは ALLOW_README_TODO=1 で通す。最終の提出では必ず埋める
  if [ "${ALLOW_README_TODO:-}" = 1 ]; then
    echo "注意: README に TODO が残ったまま書き出します（途中の反映）。最終の提出までに埋めてください" >&2
  else
    echo "README の上の行を埋めてから書き出してください（途中の反映なら ALLOW_README_TODO=1）。止めます" >&2; exit 1
  fi
else
  echo "   なし"
fi

echo "== 提出用リポジトリの中身を入れ替える"
ORIGINAL_IGNORE=$(mktemp); ORIGINAL_LICENSE=$(mktemp)
[ -f "$DEST/.gitignore" ] && cp "$DEST/.gitignore" "$ORIGINAL_IGNORE"
[ -f "$DEST/LICENSE" ] && cp "$DEST/LICENSE" "$ORIGINAL_LICENSE"
git -C "$DEST" rm -rq --ignore-unmatch . >/dev/null
git -C "$SRC" archive --format=tar HEAD | tar -x -C "$DEST"

# 提出に要らないもの（開発の進め方の記録、Drive の著作物利用シートへ移す下書き、この script）は置かない。
# CI の設定（.github）も置かない。提出用リポジトリでは GitHub Actions が使えない（運営の README）ので、CI は開発用リポジトリでだけ動かす。
# README の「このリポジトリは開発用です」の注意書きと、置かないファイルへのリンクも外す
rm -f "$DEST/docs/submission-checklist.md" "$DEST/docs/third-party.md" "$DEST/scripts/export_submission.sh"
rm -rf "$DEST/.github"
rmdir "$DEST/scripts" 2>/dev/null || true
sed -i.bak -e '/^> \[!NOTE\]$/{N;/開発用です/d;}' "$DEST/README.md"
sed -i.bak -e '/submission-checklist\.md/d' -e '/third-party\.md/d' "$DEST/docs/README.md"
rm -f "$DEST/README.md.bak" "$DEST/docs/README.md.bak"

# 運営の .gitignore（秘密情報の形式）はこちらの .gitignore に足す。運営の LICENSE（MIT）は、こちらに無ければ残す
if [ -s "$ORIGINAL_IGNORE" ]; then
  { echo; echo "# 提出用リポジトリの既定（運営の .gitignore）"; grep -vxFf "$DEST/.gitignore" "$ORIGINAL_IGNORE" || true; } >> "$DEST/.gitignore"
fi
[ -f "$DEST/LICENSE" ] || { [ -s "$ORIGINAL_LICENSE" ] && cp "$ORIGINAL_LICENSE" "$DEST/LICENSE"; }
rm -f "$ORIGINAL_IGNORE" "$ORIGINAL_LICENSE"

echo "== コミットする（履歴は持ち込まない）"
ME=$(git -C "$DEST" config user.email || true)
case "$ME" in
  *@users.noreply.github.com) ;;
  *) echo "注意: コミットの作者のメールアドレス（$ME）が公開されます。GitHub の noreply アドレスにするなら git -C $DEST config user.email <ID+名前@users.noreply.github.com>" >&2 ;;
esac
# 個人のメールアドレスを公開しないため、noreply アドレスのメンバーだけを付ける
AUTHORS=$(git -C "$SRC" shortlog -sne HEAD | sed -E 's/^ *[0-9]+[[:space:]]+//' | grep -v -F "${ME:-@@none@@}" || true)
COAUTHORS=$(printf '%s\n' "$AUTHORS" | grep -F '@users.noreply.github.com>' | sed 's/^/Co-authored-by: /' || true)
SKIPPED=$(printf '%s\n' "$AUTHORS" | grep -v -F '@users.noreply.github.com>' | sed -E 's/ <.*//' || true)
[ -z "$SKIPPED" ] || echo "注意: noreply でないので Co-authored-by に付けません: $(echo $SKIPPED)" >&2
SHA=$(git -C "$SRC" rev-parse --short HEAD)
git -C "$DEST" add -A
git -C "$DEST" commit -q -F - <<EOF
ムシトリ 最終提出（$(date +%Y-%m-%d)）

開発用リポジトリ（非公開）の $SHA の内容。
${COAUTHORS}
EOF

echo
# head に渡すと、pipefail の下で git が SIGPIPE（終了コード 141）で止まり、書き出せていても失敗になる。要約だけを出す
git -C "$DEST" --no-pager log -1 --shortstat
echo
echo "確かめてから push してください:  git -C $DEST push origin $(git -C "$DEST" branch --show-current)"
