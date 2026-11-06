# API（apps/api）

提出コードから問いと正解を作り、採点し、声をかける順と、本人の説明を聞きたい行・質問案を教員に返す API です。FastAPI で書き、本番は Cloud Run で動かします。

開発・試験・デプロイの手順は [`DEVELOPMENT.md`](./DEVELOPMENT.md) を参照してください。

## 役割

| 段階 | すること | AI |
|---|---|---|
| 提出を受け取る | `出席番号.py` をまとめた zip を展開せずに読み、名簿と対応づける | 使わない |
| 問いと正解を作る | Code Execution で実行し、出力の予測・変数の追跡・変更の影響の問いを作る | 問いの選定と解説だけ Gemini |
| 授業で解く | 持ち時間をサーバーの時刻で判定し、実行結果と照合して採点する | 使わない |
| 締切のあと | 生徒ごとの記録に結果を足し、説明を聞きたい行を選ぶ | 質問案とまとめだけ Gemini |
| 声をかける | 持ち時間の中で声をかける順を出し、教員の記録を残す | 使わない |
| 振り返り | 生徒が行の説明を送る。答えを言わない対話でヒントを返す | 対話の返答だけ Gemini |

Gemini の出力は、文字数、評価の言葉、存在しない行番号、入力にない数値、URL、AIの使用に触れた文を機械的に検査し、通らなければ既定の文に戻します。Gemini に渡す生徒由来の文と返答は、Model Armor でも検査します。セキュリティの全体は [`SECURITY.md`](../../SECURITY.md) を参照してください。

## 構成

| 場所 | 役割 |
|---|---|
| [`app/main.py`](./app/main.py) | API の入口。認証、入力の検査、各段階の呼び出し |
| [`app/service.py`](./app/service.py) | 提出の読み込み、採点、締切のあとの処理の流れ |
| [`app/insight.py`](./app/insight.py) | 生徒ごとの記録から、本人の説明を聞きたい行を選ぶ（AIなし） |
| [`app/ordering.py`](./app/ordering.py) | 声をかける順の計算（AIなし） |
| [`app/auth.py`](./app/auth.py) | 教員の Google ログインの検証、生徒の署名付きトークン、用途ごとの鍵 |
| [`app/security.py`](./app/security.py) | セキュリティヘッダー、本文の大きさの上限、接続元の判定 |
| [`app/audit.py`](./app/audit.py) | 監査ログ（Cloud Logging の形式）。コード、トークン、生のIPアドレスは残さない |
| [`app/offline_api.py`](./app/offline_api.py) | 授業パッケージ、校内LAN版、端末にためた解答の受け付け |
| [`app/classpack.py`](./app/classpack.py) | 授業パッケージの署名（Cloud KMS）、暗号化、コードの照合値 |
| [`app/lan_store.py`](./app/lan_store.py) | 校内LAN版の保存先（暗号化したファイル） |
| [`app/store.py`](./app/store.py) | 保存先の共通の操作と、手元用のメモリ版 |
| [`app/firestore_store.py`](./app/firestore_store.py) | 本番用の Firestore 版 |
| [`app/demo.py`](./app/demo.py) | デモの合成データ（提出6人分と、過去2回分の記録） |
| [`qgen/harness.py`](./qgen/harness.py) | 隔離環境の中で動く実行ラッパー。標準ライブラリのみ |
| [`qgen/sandbox.py`](./qgen/sandbox.py) | 実行環境の切り替え（本番は Code Execution） |
| [`qgen/questions.py`](./qgen/questions.py) | 実行結果から問いと正解を作る |
| [`qgen/ai.py`](./qgen/ai.py) | Gemini の呼び出しと出力の検査。失敗時はテンプレートに戻す |
| [`qgen/guard.py`](./qgen/guard.py) | Gemini に渡す文と返答を Model Armor で検査する。検査できなければ通さない |
| [`tests/unit/`](./tests/unit/) | 単体テスト（135件） |
| [`tests/integration/`](./tests/integration/) | 結合テスト（147件。攻撃の入力、保存期間、校内LAN版を含む） |
| [`scripts/dev.sh`](./scripts/dev.sh) | 手元の開発サーバー（合成データ専用） |
| [`scripts/record_demo.py`](./scripts/record_demo.py) | デモ動画の自動収録 |
| [`scripts/lan.py`](./scripts/lan.py) | 校内LAN版を教員PCで起動する（[`docs/offline.md`](../../docs/offline.md)） |

## 主な API

| メソッドとパス | 使う人 | 内容 |
|---|---|---|
| `POST /v1/classes` | 教員 | クラスと名簿を作り、授業コードと個人コードを返す（平文で返すのはこの1回だけ） |
| `POST /v1/assignments/{id}/submissions` | 教員 | 提出の zip を受け取る |
| `POST /v1/assignments/{id}:generate` | 教員 | 問いの生成を裏の処理で始める |
| `POST /v1/assignments/{id}:open`・`:close` | 教員 | 受付の開始と締切。締切で記録と質問案を作る |
| `GET /v1/assignments/{id}/followups` | 教員 | 声をかける順、説明を聞きたい行と質問案、クラスのまとめ |
| `GET /v1/assignments/{id}/students/{sid}/record` | 教員 | 生徒ごとのこれまでの記録 |
| `POST /v1/sessions` | 生徒 | 授業コードと個人コードで入室する |
| `POST /v1/assignments/{id}/attempt:start`・`:submit` | 生徒 | 解答の開始と提出 |
| `POST /v1/assignments/{id}/attempt:explain` | 生徒 | まちがえた問いが指す行を、自分の言葉で説明して送る |
| `POST /v1/assignments/{id}/attempt:chat` | 生徒 | 答えを言わない振り返りの対話（1課題10回まで） |
| `DELETE /v1/assignments/{id}`・`DELETE /v1/classes/{id}` | 教員 | 課題、またはクラスとそのすべてのデータを、期限を待たずに消す |
| `POST /v1/assignments/{id}/package` | 教員 | 授業パッケージ（署名・暗号化）を作る。解除コードは1回だけ返す |
| `POST /v1/assignments/{id}/attempt:submit-offline` | 生徒 | 通信が切れている間に端末にためた解答を送る |
| `POST /v1/assignments/{id}/edge-results` | 教員 | 校内LAN版の結果を取り込み、クラウドの正解で採点し直す |
