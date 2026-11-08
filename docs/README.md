# docs

ムシトリの設計の考え方と、本番での確認記録です。手順は [`apps/api/DEVELOPMENT.md`](../apps/api/DEVELOPMENT.md) を参照してください。

| 文書 | 内容 |
|---|---|
| [`../RSI.md`](../RSI.md) | 失敗例から指示文を改善するRSIの仕組み、GEPAとの関係、実測例とUIテスト |
| [`design.md`](./design.md) | 問いの作り方、声をかける順、本人の説明を聞きたい行の選び方、Gemini の出力の検査 |
| [`verification-2026-11-06.md`](./verification-2026-11-06.md) | 2026年11月6日に公開URLで、本物の Code Execution、Gemini、Firestore を使って確かめたこと |
| [`offline.md`](./offline.md) | ネットが落ちても授業を止めない仕組み（授業パッケージ、校内LAN版、端末にためる解答） |
| [`../SECURITY.md`](../SECURITY.md) | セキュリティの設計と対策、デプロイのときに行う設定 |
| [`submission-checklist.md`](./submission-checklist.md) | Kickoff 資料の提出要件・審査対象外の条件との照合（締切 11/10 19:00、提出用リポジトリへの置き方） |
| [`third-party.md`](./third-party.md) | 著作物利用シートの下書き（ライブラリ・画像・データの出典とライセンス） |

## 図

| 図 | 内容 |
|---|---|
| [`rsi-target.svg`](./rsi-target.svg)・[`rsi-loop.svg`](./rsi-loop.svg) | RSIの改善対象と、候補生成から人による採用まで（`make_rsi_diagrams.py`で再生成） |
| [`architecture-gcp.svg`](./architecture-gcp.svg) | Google Cloud の構成（プロダクト説明ドキュメントのアーキテクチャ図） |
| [`security-easy.svg`](./security-easy.svg) | 何から守っているか（セキュリティに詳しくない人向け） |
| [`security-stack.svg`](./security-stack.svg)・[`security-architecture.svg`](./security-architecture.svg) | セキュリティの技術構成と信頼の境界 |
| [`ai-guard-flow.svg`](./ai-guard-flow.svg) | AI の入出力の検査の流れ |
| [`resilience-flow.svg`](./resilience-flow.svg) | ネットが落ちても授業を止めない3段階 |
| [`system-kimura.svg`](./system-kimura.svg)・[`system-integrated.svg`](./system-integrated.svg) | 2つのブランチを統合する前の比較図（2026年11月6日時点）。今の構成は README の図を参照 |

図は [`make_diagrams.py`](./make_diagrams.py) で作っています。

確認はすべて合成データで行っています。
