# 著作物利用シートの下書き（使った素材・ライブラリ・データの出典とライセンス）

提出物の「著作物利用シート」に写すための一覧です。リポジトリの中身から機械的に拾ったので、提出前に各自が担当した部分（画像の生成に使ったツール、動画の素材）を確かめて埋めてください。**空欄（「要記入」）が残ったまま提出しないこと。**

## 1. ライブラリ（API：`apps/api/requirements*.txt`）

| 名前 | 版 | ライセンス | 出典 | 用途 |
| --- | --- | --- | --- | --- |
| fastapi | 0.136.1 | MIT | https://github.com/fastapi/fastapi | API |
| uvicorn | 0.46.0 | BSD-3-Clause | https://github.com/encode/uvicorn | サーバー |
| python-multipart | 0.0.26 | Apache-2.0 | https://github.com/Kludex/python-multipart | 提出 zip の受け取り |
| cryptography | 46.0.3 | Apache-2.0 または BSD-3-Clause | https://github.com/pyca/cryptography | 授業パッケージの署名・暗号化 |
| google-genai | 2.34.0 | Apache-2.0 | https://github.com/googleapis/python-genai | Gemini の呼び出し |
| google-cloud-agentplatform | 2.7.0 | Apache-2.0 | https://github.com/googleapis/google-cloud-python | Code Execution（生徒のコードの実行） |
| google-cloud-modelarmor | 0.7.5 | Apache-2.0 | https://github.com/googleapis/google-cloud-python | AI の入出力の検査 |
| google-cloud-kms | 3.18.0 | Apache-2.0 | https://github.com/googleapis/google-cloud-python | 授業パッケージの署名 |
| google-crc32c | 1.9.0 | Apache-2.0 | https://github.com/googleapis/python-crc32c | KMS とのやりとりの整合性 |
| firebase-admin | 7.7.0 | Apache-2.0 | https://github.com/firebase/firebase-admin-python | 教員の ID トークンの検証 |
| google-cloud-firestore | 2.34.1 | Apache-2.0 | https://github.com/googleapis/google-cloud-python | データの保存 |

開発・試験・収録にだけ使うもの（プロダクトには入らない）:

| 名前 | ライセンス | 用途 |
| --- | --- | --- |
| pytest | MIT | 試験 |
| httpx | BSD-3-Clause | 試験（API の呼び出し） |
| ruff | MIT | 静的検査 |
| playwright | Apache-2.0 | デモ動画の収録、画面の試験 |
| imageio-ffmpeg | BSD-2-Clause（同梱の ffmpeg は LGPL/GPL） | デモ動画の書き出し |

## 2. ブラウザで読み込むもの（`apps/web/`）

| 名前 | 版 | ライセンス | 出典 | 用途 |
| --- | --- | --- | --- | --- |
| Firebase JS SDK（app, auth） | 10.14.1 | Apache-2.0 | https://www.gstatic.com/firebasejs/10.14.1 | 教員の Google ログイン |

画面の HTML・CSS・JavaScript は自作。Web フォントは使わず、端末のフォントで表示する。

## 3. 画像・図・アイコン

| もの | 作り方 | ライセンス・出典 |
| --- | --- | --- |
| `assets/mushitori_hero.png`、`assets/flow.png`、`assets/diagram.png` | 生成AIで作成（プロンプトはチーム）。実在の人物・学校とは無関係 | **要記入**：使ったツールの名前と、そのツールの利用規約での出力の扱い |
| `docs/*.svg`（セキュリティ、RSI、構成の図） | `docs/make_diagrams.py`、`docs/make_rsi_diagrams.py` で自作。ピクトグラムも自作 | チーム |
| README のバッジ | shields.io、skillicons.dev のサービスを URL で参照（画像ファイルは持たない） | 各サービスの利用規約。製品ロゴはそれぞれの商標 |
| Google Cloud の公式アイコン | 使う場合は `docs/icons/` に置く（現在は未使用） | https://cloud.google.com/icons の利用条件に従う |

## 4. データ

| もの | 中身 | 出典・ライセンス |
| --- | --- | --- |
| `apps/api/app/demo.py` のデモクラス | 合成データ（架空の生徒6人分のコードと過去2回分の記録） | チームが作成 |
| `apps/api/evals/cases/` | 評価用の合成データ（コード、主張、正解ラベル） | チームが作成 |
| `apps/api/evals/cases_lowq2/` | 質の低い提出を模した合成データ。コードの元は公開モデル HuggingFaceTB/SmolLM2-1.7B-Instruct の出力（Apache-2.0）にチームが手を入れたもの。説明文はチームが型から作成 | モデル: Apache-2.0。生成はローカル/Colab で行い、**プロダクトからは呼ばない**（評価用データのみ） |
| 実在の生徒の提出物 | 使っていない | — |

## 5. フォント・音声・動画素材

| もの | 出典 |
| --- | --- |
| デモ動画の字幕フォント | 収録した PC の 'Hiragino Sans'（OS 同梱） |
| BGM・効果音 | **要記入**（使った場合のみ。使っていなければ「なし」） |

## 6. 開発に使った AI ツール（採点外項目「AIをどの場面でどう使ったか」に書く内容）

プロダクトの中で使う AI は Gemini（Google）だけ。開発の補助として AI コーディング支援ツールを使った（設計の相談、コードとテストの下書き、文書の下書き）。どの場面でどう使い、どう確かめたかは提出ドキュメントの該当欄に書く。デモ・ピッチ・README では他社の AI 製品名を前面に出さない。
