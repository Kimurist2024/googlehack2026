# ムシトリ（仮称）

自分の書いたコードを本人が分かっているかを、授業の5分で確かめるツールです。

提出コードを隔離環境で実行して問いと正解を作り、生徒が授業中に解きます。教員は誤答をもとに、持ち時間の中で声をかける順を決めます。正解と採点はコードの実行結果で決まり、AIは使いません。Geminiは問いの選定と、つまずきの説明を担当します。

このリポジトリは開発用です。審査は提出用リポジトリ（`Devfest-Hackathon-2026/df-2026-t032`）の内容で行われるので、最終版は提出期限までにそちらへ移します。

## 手元で動かす

```sh
uv venv --python 3.12 .venv
uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest
sh scripts/dev.sh
```

ブラウザで http://localhost:8000 を開き、「デモクラスを作る」から試せます。

> `scripts/dev.sh` は生徒のコードを隔離せずに手元で動かします。合成データ専用で、実在の提出物には絶対に使わないでください。

## 構成

| 場所 | 役割 |
| --- | --- |
| `qgen/harness.py` | 隔離環境の中で動く実行ラッパー。標準ライブラリのみ |
| `qgen/sandbox.py` | 実行環境の切り替え（本番は Code Execution） |
| `qgen/questions.py` | 実行結果から問いと正解を作る |
| `qgen/ai.py` | Gemini の呼び出しと出力の検査。失敗時はテンプレートに戻す |
| `app/main.py` | FastAPI の API |
| `app/ordering.py` | 声をかける順の計算 |
| `app/service.py` | 提出の読み込み、採点、処理の流れ |
| `app/store.py` | 保存先の共通の操作と、手元用のメモリ版 |
| `app/firestore_store.py` | 本番用の Firestore 版 |
| `firestore.rules` | ブラウザからの読み書きをすべて拒否するルール |
| `web/` | 教員と生徒の画面（デモ） |
| `tests/unit/` | 単体テスト |
| `tests/integration/` | 結合テスト |

## テスト

```sh
.venv/bin/python -m pytest                    # すべて
.venv/bin/python -m pytest tests/unit         # 単体テストだけ
.venv/bin/python -m pytest tests/integration  # 結合テストだけ
```

| 場所 | 試すもの | 新しいテストを置く基準 |
| --- | --- | --- |
| `tests/unit/` | 関数やクラス1つ | コードを実行せず、APIも通さない。外部とのやりとりは偽物に置き換える |
| `tests/integration/` | 部品をつないだ動き | APIを通す、または合成コードを実際に実行する |

- どちらも本物の Code Execution と Gemini は呼びません。手元の実行環境（`LocalDevSandbox`）とテンプレート（`TemplateAI`）を使います。
- 結合テスト専用の準備は `tests/integration/conftest.py` に置きます。単体テストからは使えません。
- pytest の設定は `pyproject.toml` にあります。

Firestore 版も試すときは、公式エミュレータの中で結合テストを動かします。Java 21 以上と Node.js が必要です。`demo-` で始まるプロジェクトはクラウドに接続しません。

```sh
npx firebase-tools@15.35.0 emulators:exec --only firestore --project demo-mushitori ".venv/bin/python -m pytest tests/integration"
```

エミュレータがあると、保存先を使う試験はメモリ版と Firestore 版の両方で動きます。

## 環境変数

`.env.example` を参照してください。指定がないときは本番用の設定（Firestore、Code Execution）で動き、`SESSION_SECRET` がなければ起動後の処理を拒否します。

`SESSION_SECRET` は授業コードと個人コードのハッシュにも使います。変えると保存済みのコードで入室できなくなるので、本番では固定した値を Secret Manager に置きます。

## まだできていないこと

- **Firestore のデータベース：** コードはエミュレータで確認済みですが、本物のデータベースはまだ作っていません。場所を後から変えられないので、`asia-northeast1` で作ります。
- **Cloud Storage：** 仕様では提出コードと実行の記録を Storage に置きますが、今は Firestore の文書に入れています。1文書の上限を超えそうな提出は「出力が多すぎる」として対象外にします。
- **ログインの試行回数の制限：** インスタンスごとに数えているので、複数インスタンスでは正確に効きません。
- **Cloud Run Jobs：** 問いの生成はAPIの中のバックグラウンド処理です。本番ではジョブに分けます。
- **教員のログイン：** Firebase の検証コードはありますが、画面はローカル用の仮の認証のままです。
- **デプロイ：** Dockerfile はありますが、まだビルドしていません。
- **Classroom 連携、`.ipynb` 対応：** 未着手です。

## データの扱い

- 実在の生徒の提出物は使いません。デモは `app/demo.py` の合成データです。
- 評価用データの候補 [ai-cet/paper-neurips23-gaied](https://github.com/ai-cet/paper-neurips23-gaied) は CC BY-NC-SA 4.0 です。公開の提出用リポジトリには含めず、`data/` に置きます（Git の管理外）。
- APIキーや鍵はコミットしません。提出用リポジトリは公開されるので、履歴ごと持ち込まないでください。
