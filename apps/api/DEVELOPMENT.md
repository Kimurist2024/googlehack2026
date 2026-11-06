# 開発・運用の手順（apps/api）

## 手元で動かす

```sh
cd apps/api
uv venv --python 3.12 .venv
uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest
sh scripts/dev.sh
```

ブラウザで http://localhost:8000 を開き、「デモクラスを作る」から試せます。画面は `apps/web` のファイルをそのまま配ります（`SERVE_WEB=1` のときだけ）。

> [!WARNING]
> `scripts/dev.sh` は生徒のコードを隔離せずに手元で動かします。合成データ専用で、実在の提出物には絶対に使わないでください。

`scripts/dev.sh` は `apps/api/.venv` がなければ、リポジトリ直下の `.venv` を使います。

## テスト

```sh
cd apps/api
.venv/bin/python -m pytest                    # すべて
.venv/bin/python -m pytest tests/unit         # 単体テストだけ
.venv/bin/python -m pytest tests/integration  # 結合テストだけ
```

| 場所 | 試すもの | 新しいテストを置く基準 |
|---|---|---|
| `tests/unit/` | 関数やクラス1つ | コードを実行せず、APIも通さない。外部とのやりとりは偽物に置き換える |
| `tests/integration/` | 部品をつないだ動き | APIを通す、または合成コードを実際に実行する |

- どちらも本物の Code Execution と Gemini は呼びません。手元の実行環境（`LocalDevSandbox`）とテンプレート（`TemplateAI`）を使います。
- 結合テスト専用の準備は `tests/integration/conftest.py` に置きます。単体テストからは使えません。
- pytest の設定は `pyproject.toml` にあります。

Firestore 版も試すときは、公式エミュレータの中で結合テストを動かします。Java 21 以上と Node.js が必要です。`demo-` で始まるプロジェクトはクラウドに接続しません。エミュレータの設定はリポジトリ直下の `firebase.json` にあるので、直下から実行します。

```sh
npx firebase-tools@15.35.0 emulators:exec --only firestore --project demo-mushitori "cd apps/api && .venv/bin/python -m pytest tests/integration"
```

## 環境変数

[`.env.example`](./.env.example) を参照してください。指定がないときは本番用の設定（Firestore、Code Execution）で動き、`SESSION_SECRET` がなければ起動後の処理を拒否します。

`SESSION_SECRET` からは用途ごとの鍵（トークンの署名、授業コードと個人コードのハッシュ、接続元のハッシュ）を導出します。変えると保存済みのコードで入室できなくなるので、本番では固定した値を Secret Manager に置きます。

| 変数 | 内容 |
|---|---|
| `MODEL_ARMOR_TEMPLATE` | Gemini に渡す文と返答を検査する Model Armor のテンプレート。本番で `AI_BACKEND=gemini` なら必須で、ないときは Gemini を使わずテンプレートで動く |
| `RETENTION_DAYS` | 生徒のデータを残す日数（1〜365、既定30）。課題を作った時点から数える |
| `PACKAGE_SIGNING_KMS_KEY` | 授業パッケージに署名する Cloud KMS の鍵。ないと授業パッケージを作れない（503）。授業そのものには影響しない |
| `TRUSTED_PROXY_HOPS` | `X-Forwarded-For` の右から何個を信用するか。Cloud Run の上では指定しなくても1 |
| `FIREBASE_CHECK_REVOKED` | 1 にすると、失効した教員のトークンも断る。サービスアカウントに `roles/firebaseauth.viewer` が要る |

設定の手順は [`SECURITY.md` の「デプロイのときに行う設定」](../../SECURITY.md#デプロイのときに行う設定) にあります。ネットが落ちたときの校内LAN版は [`docs/offline.md`](../../docs/offline.md) を参照してください。

## 本番の構成

公開URLは https://mushitori-hackathon.web.app です。画面は Firebase Hosting から配信し、Cloud Run のURLには画面を置いていません。

| 部品 | 設定 |
|---|---|
| Firebase Hosting | `apps/web` を配信し、`/v1/**` を Cloud Run の `mushitori`（`asia-northeast1`）へ転送する（直下の `firebase.json`）。画面の HTML・JS・CSS は `Cache-Control: no-cache` で配り、デプロイした直後から新しい画面が出るようにする |
| Firebase Auth | Google ログイン。教員は `TEACHER_EMAILS` のアカウントだけを通す |
| Cloud Run | 誰でも呼べる設定。サービスアカウント `mushitori-run` には Firestore と Agent Platform の利用権限だけを付ける |
| Secret Manager | `mushitori-session-secret` を `SESSION_SECRET` として渡す |
| Code Execution | 実行環境を1つ作り、`SANDBOX_RUNTIME_NAME` で渡す。指定しないと問いを作るたびに新しく作られる |

Cloud Run の環境変数は `APP_ENV=production`、`STORE_BACKEND=firestore`、`AI_BACKEND=gemini`、`SANDBOX_BACKEND=code_execution`、`TEACHER_EMAILS`、`ALLOW_DEMO_SEED=1`、`SERVE_WEB=0` などです。

## デプロイ

> [!IMPORTANT]
> `security/Taiga` のセキュリティ対策を取り込んだ版を初めてデプロイすると、次のことが起きます。
> - 授業コードと個人コードのハッシュの作り方が変わるので、今あるクラスのコードでは入れなくなります。デモクラスは作り直してください。
> - `MODEL_ARMOR_TEMPLATE` がないと、Gemini を使わずテンプレートで動きます。先に Model Armor のテンプレートを作り、Cloud Run のサービスアカウントに `roles/modelarmor.user` を付けて、環境変数を設定します。
> - 授業パッケージは `PACKAGE_SIGNING_KMS_KEY` がないと作れません（503）。授業そのものには影響しません。
> - Firestore の TTL（`students` を含む）を有効にするまでは、期限後のデータは API から見えなくなるだけで、DB には残ります。
> - クラスを作るときに照合値（scrypt）を計算するので、生徒1人あたり数十ミリ秒かかります。

リポジトリを置いた Cloud Shell で、リポジトリ直下から実行します。API を先に、画面をあとに出します（画面が新しい API を使うことがあるため）。`gcloud run deploy` は、指定しない設定（環境変数、サービスアカウント、公開範囲）をそのまま引き継ぎます。

```sh
gcloud run deploy mushitori --source apps/api --region asia-northeast1 --project mushitori-hackathon --quiet
firebase deploy --only hosting,firestore:rules --project mushitori-hackathon
```

教員を増やすときは、`TEACHER_EMAILS` をカンマ区切りで書き換えます。値にカンマを含むので、区切り文字を `^:^` で変えます。

```sh
gcloud run services update mushitori --region asia-northeast1 --project mushitori-hackathon --update-env-vars '^:^TEACHER_EMAILS=a@example.com,b@example.com'
```

## まだできていないこと

- **Cloud Storage：** 仕様では提出コードと実行の記録を Storage に置きますが、今は Firestore の文書に入れています。1文書の上限を超えそうな提出は「出力が多すぎる」として対象外にします。
- **入室の試行回数の制限：** 失敗した入室だけを、接続元ごとに毎分30回まで Firestore で数えます（インスタンスをまたいで効きます）。Cloud Run では `X-Forwarded-For` の右端を接続元とします。Firebase Hosting を通したときの段数（`TRUSTED_PROXY_HOPS`）は、デプロイ後に監査ログで確かめます。
- **Model Armor、Cloud KMS、TTL：** 検査と署名のコードと試験はありますが、テンプレート、鍵、TTL の設定はまだ作っていません（[`SECURITY.md`](../../SECURITY.md#デプロイのときに行う設定)）。
- **画面の CSP：** 本番の画面ではまだ Report-Only です。違反がないことを確かめてから強制にします。
- **Cloud Run Jobs：** 問いの生成と締切のあとの処理は、APIの中のバックグラウンド処理です。本番ではジョブに分けます。
- **Cloud Shell へのコードの持ち込み：** GitHub との連携を設定していないので、今は手作業で送っています。
- **Classroom 連携、`.ipynb` 対応：** 未着手です。

## データの扱い

- 実在の生徒の提出物は使いません。デモは `app/demo.py` の合成データです。
- 評価用データの候補 [ai-cet/paper-neurips23-gaied](https://github.com/ai-cet/paper-neurips23-gaied) は CC BY-NC-SA 4.0 です。公開の提出用リポジトリには含めず、`data/` に置きます（Git の管理外）。
- APIキーや鍵はコミットしません。提出用リポジトリは公開されるので、履歴ごと持ち込まないでください。
