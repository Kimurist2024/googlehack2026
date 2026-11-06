# ムシトリ

![Website](https://img.shields.io/website?url=https%3A%2F%2Fmushitori-hackathon.web.app&label=demo)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-141%20passed-17694A)

[![自分のコードを、自分の言葉で。](./assets/mushitori_hero.png)](https://mushitori-hackathon.web.app)

<div align="center">

  ## DevFest GDGoC Japan Hackathon 2026
  [![教育部門](https://img.shields.io/badge/DevFest%20Hackathon%202026-%E6%95%99%E8%82%B2%E9%83%A8%E9%96%80-17694A?style=for-the-badge&logo=google&logoColor=white)](https://mushitori-hackathon.web.app)

  <br/>

  [![Used Skills](https://skillicons.dev/icons?i=python,fastapi,js,html,css,gcp,firebase,docker)](https://skillicons.dev)

</div>

## 目次

- [リポジトリ構成](#リポジトリ構成)
- [Live Demo](#live-demo)
- [製品概要](#製品概要)
  - [特長](#特長)
  - [解決出来ること](#解決出来ること)
  - [今後の展望](#今後の展望)
  - [注力したこと](#注力したこと)
- [開発技術](#開発技術)
  - [活用した技術](#活用した技術)
  - [独自技術](#独自技術)
- [データの扱い](#データの扱い)

## リポジトリ構成

各コンポーネントの役割は、それぞれのREADMEを参照してください。開発・運用の手順は [`apps/api/DEVELOPMENT.md`](./apps/api/DEVELOPMENT.md) にまとめています。

| ディレクトリ | 内容 |
|---|---|
| [`apps/api/`](./apps/api/README.md) | 問いの生成、採点、声をかける順、生徒ごとの記録と質問案を扱うAPI（FastAPI、Cloud Run） |
| [`apps/web/`](./apps/web/README.md) | 教員と生徒の画面。ビルド不要のHTML・CSS・JavaScriptで、Firebase Hosting から配信 |
| [`docs/`](./docs/README.md) | 設計の考え方（問いの作り方、声をかける順、説明を聞きたい行の選び方）と、本番での確認記録 |
| [`assets/`](./assets/) | READMEの画像 |
| `firebase.json`・`firestore.rules` | Firebase Hosting の配信設定と、ブラウザからの読み書きをすべて拒否する Firestore のルール |

> [!NOTE]
> このリポジトリは開発用です。審査は提出用リポジトリ（`Devfest-Hackathon-2026/df-2026-t032`）の内容で行われるので、最終版は提出期限までにそちらへ移します。

## Live Demo

**教員と生徒の画面**: https://mushitori-hackathon.web.app

+ 教員の画面は、許可した Google アカウントでログインしたときだけ使えます。「デモクラスを作る」で、合成データのクラス（過去2回分の記録つき）ができます。
+ 生徒の画面は、教員の画面に出る授業コードと個人コードで入室します。ログインは要りません。

## 製品概要

### 背景（製品開発のきっかけ、課題等）

生成AIを使えば、動くコードはすぐに提出できます。一方で、提出したコードを本人が説明できるかどうかは、提出物を見ても分かりません。教員が40人分のコードを1行ずつ読み、本人に確かめて回る時間は授業の中にありません。

AtCoder のような自動採点は、コードが正しく動くかを判定します。私たちが確かめたいのは、そのコードを書いた本人が、自分のコードの動きを説明できるかどうかです。

### 製品説明（具体的な製品の説明）

ムシトリは、生徒が提出したコードそのものから短い問いを作り、授業の5分で本人に答えてもらうツールです。

提出コードを隔離環境（Code Execution）で実行し、最後に表示される内容、変数の値の移り変わり、1か所を変えたときの結果を記録します。その記録から問いと正解を作るので、正解も採点もAIには頼りません。

締切のたびに、生徒ごとの記録に結果を積み上げます。誤答した問いが指す行、本人がこれまで使っていなかった書き方、クラスでほとんど使われていない書き方を手がかりに、本人の説明を聞きたい行を選びます。Gemini は、その行で教員がたずねる質問案と、これまでの様子のまとめを書きます。

![授業の流れ](./assets/flow.png)

![構成](./assets/diagram.png)

### 特長

#### 1. 本人のコードから問いを作る！

> [!IMPORTANT]
> 生徒一人ひとりの提出コードを実行し、その結果から問いと正解を作ります。AIは正解と採点に関わりません。

同じ課題でも、生徒ごとにコードは違います。ムシトリは、出力の予測、変数の追跡、変更の影響の3種類の問いを、本人のコードから作ります。誰かの答えを写しても、自分のコードの問いには答えられません。

#### 2. 説明を聞きたい行が分かる！

> [!IMPORTANT]
> 生徒ごとの記録とクラスの提出を比べて、本人の説明を聞きたい行を選び、その場でたずねる質問案を出します。

教員はコードをゼロから読み直さずに、「6行目の `.append()` は何をしていますか。なぜこの書き方にしましたか」のような質問から始められます。根拠はどれも機械的に確かめられる事実で、AIを使ったかどうかは判定しません。

#### 3. 生徒が自分の言葉で振り返る！

> [!IMPORTANT]
> 解答のあと、まちがえた問いが指す行を、生徒が自分の言葉で説明して先生に送れます。

AI任せになっていたところを、生徒が自分で言葉にします。答えを教えずにヒントを返す振り返りの対話もあり、送った説明は教員の画面のその行の下に並びます。

### 解決出来ること

教員は、40人分のコードを読み込まなくても、限られた授業時間の中で、誰の、どの行から話を聞けばよいかが分かります。浮いた時間を、テスト作りや個別の指導に回せます。

生徒は、動くコードを提出して終わりにせず、自分のコードを説明できるかを確かめる機会を毎回の授業で持てます。

### 今後の展望

- 教員が記録した「説明できた」「説明が難しかった」を積み上げ、質問案の選び方を改善します。
- Google Classroom から提出を受け取れるようにし、`.ipynb` にも対応します。
- 問いの生成を Cloud Run Jobs に分け、40人分を並列で作れるようにします。

### 注力したこと

- **AIに任せる範囲を絞ること**

  正解、採点、声をかける順、説明を聞きたい行の選び方は、実行結果と記録から機械的に決めます。Gemini には、問いの選定、解説、質問の言い回し、まとめだけを任せ、その出力は文字数、評価の言葉、存在しない行番号、入力にない数値を機械的に検査します。通らなければ既定の文に戻すので、Gemini が止まっても授業は止まりません。

- **生徒を疑う道具にしないこと**

  説明を聞きたい行は「AIを使った証拠」ではありません。画面にもそう示し、AIの使用に触れた文は Gemini の出力から取り除きます。

## 開発技術

### 活用した技術

**技術構成: Code Execution で本人のコードを実行し、Gemini が質問案を書き、Firebase と Cloud Run で授業に届ける**

| 技術 | ムシトリでの役割 |
|---|---|
| ![Code Execution](https://img.shields.io/badge/Agent%20Platform-Code%20Execution-4285F4?style=flat&logo=googlecloud&logoColor=white) | 生徒の提出コードを外部通信のない隔離環境で実行し、出力と変数の移り変わりを記録する。 |
| ![Gemini](https://img.shields.io/badge/Gemini-3.5%20Flash--Lite-8E75B2?style=flat&logo=googlegemini&logoColor=white) | 問いの選定、解説、行ごとの質問案、これまでの様子のまとめ、振り返りの対話。正解と採点には使わない。 |
| ![Cloud Run](https://img.shields.io/badge/Cloud%20Run-4285F4?style=flat&logo=googlecloud&logoColor=white) | API と裏の処理（問いの生成、締切のあとの記録と質問案）を動かす。 |
| ![Firestore](https://img.shields.io/badge/Firestore-FFCA28?style=flat&logo=firebase&logoColor=black) | クラス、提出、問い、解答、生徒ごとの記録を保存する。ブラウザからは読み書きさせない。 |
| ![Firebase Hosting](https://img.shields.io/badge/Firebase-Hosting-FFCA28?style=flat&logo=firebase&logoColor=black)・![Firebase Auth](https://img.shields.io/badge/Firebase-Auth-FFCA28?style=flat&logo=firebase&logoColor=black) | 画面の配信と Cloud Run への転送。教員の Google ログイン。 |

#### フレームワーク・ライブラリ

**API: 提出の読み込み、問いの生成、採点、声をかける順**

* ![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white) / [![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) / [![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)：API と入力の検査（[`apps/api/`](./apps/api/)）。
* [![Google Gen AI SDK](https://img.shields.io/badge/google--genai-8E75B2?style=flat&logo=googlegemini&logoColor=white)](https://github.com/googleapis/python-genai)：Agent Platform 経由で Gemini を呼ぶ。応答は JSON スキーマで受け取る。
* [![firebase-admin](https://img.shields.io/badge/firebase--admin-FFCA28?style=flat&logo=firebase&logoColor=black)](https://firebase.google.com/docs/admin/setup) / [![google-cloud-firestore](https://img.shields.io/badge/google--cloud--firestore-FFCA28?style=flat&logo=firebase&logoColor=black)](https://cloud.google.com/python/docs/reference/firestore/latest)：教員の ID トークンの検証と、トランザクションでの保存。
* [![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=flat&logo=pytest&logoColor=white)](https://docs.pytest.org/)：単体59件、結合82件の試験。

**画面: 教員と生徒の画面**

* ![HTML](https://img.shields.io/badge/HTML-E34F26?style=flat&logo=html5&logoColor=white) / ![CSS](https://img.shields.io/badge/CSS-1572B6?style=flat&logo=css&logoColor=white) / ![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat&logo=javascript&logoColor=black)：ビルド不要の画面（[`apps/web/`](./apps/web/)）。生徒のコードはすべて文字として表示し、HTMLとしては解釈させない。

**運用: Cloud Run、Secret Manager、Firebase**

* [![Cloud Run](https://img.shields.io/badge/Cloud%20Run-4285F4?style=flat&logo=googlecloud&logoColor=white)](https://cloud.google.com/run) / [![Secret Manager](https://img.shields.io/badge/Secret%20Manager-4285F4?style=flat&logo=googlecloud&logoColor=white)](https://cloud.google.com/secret-manager) / ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)：API のコンテナと、セッションの秘密鍵の受け渡し。

### 独自技術

#### 本人のコードの実行記録から問いを作る

提出コードを実行するときに、変数への代入を1つずつ記録し、数値や比較演算子を1か所ずつ変えた版も実行します。そこから「最後に表示される内容」「変数 `total` の3番目の値」「4行目の `>` を `>=` に変えたときの結果」のような問いと正解を作ります。誤答の選択肢も、同じ実行記録の値から選びます（[`apps/api/qgen/`](./apps/api/qgen/)）。

#### 生徒ごとの記録から、説明を聞きたい行を選ぶ

締切のたびに、課題ごとの正答数、使った書き方、説明を聞いた行、教員の記録を、生徒ごとの記録に足します。書き方は構文木から行ごとに取り出し、これまでの提出とクラスの提出と比べて、説明を聞きたい行を最大3行選びます（[`apps/api/app/insight.py`](./apps/api/app/insight.py)、詳しくは [`docs/design.md`](./docs/design.md)）。

#### 声をかける順を、持ち時間から決める

誤答の数と問いの種類の重みから、1人あたりの時間に対する見込みを出し、持ち時間の中で上から順に声をかけます。全問正解の生徒も0にはせず、順番の最後に残します（[`apps/api/app/ordering.py`](./apps/api/app/ordering.py)）。

## データの扱い

- 実在の生徒の提出物は使いません。デモとテストはすべて合成データです（[`apps/api/app/demo.py`](./apps/api/app/demo.py)）。
- 結果は声をかける順と振り返りにだけ使い、成績には使いません。
- 氏名は持たず、出席番号と個人コードのハッシュで扱います。
- READMEの画像は生成AI（GPT）で作ったイラストで、実在の人物や学校とは関係ありません。
