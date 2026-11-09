"""Regenerate the SVG figures embedded in RSI.md (standard library only)."""
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
FONT = 'Hiragino Sans, Noto Sans JP, Yu Gothic, sans-serif'


def figure(name, title, subtitle, rows, footer):
    height = 150 + len(rows) * 145 + 80
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle + "。" + "。".join("：".join(row) for row in rows))}</desc>',
             f'<rect width="1000" height="{height}" fill="#f4f7f5"/>',
             f'<g font-family="{FONT}" fill="#20352c">',
             f'<text x="50" y="55" font-size="30" font-weight="700">{escape(title)}</text>',
             f'<text x="50" y="92" font-size="19">{escape(subtitle)}</text>']
    for i, (heading, line1, line2) in enumerate(rows):
        y = 125 + i * 145
        parts += [f'<rect x="50" y="{y}" width="900" height="112" rx="14" fill="#ffffff" stroke="#b9cec2"/>',
                  f'<circle cx="88" cy="{y+34}" r="20" fill="#216b50"/>',
                  f'<text x="88" y="{y+41}" font-size="20" text-anchor="middle" fill="#ffffff">{i+1}</text>',
                  f'<text x="125" y="{y+40}" font-size="23" font-weight="700">{escape(heading)}</text>',
                  f'<text x="125" y="{y+71}" font-size="19">{escape(line1)}</text>',
                  f'<text x="125" y="{y+97}" font-size="18" fill="#4d6357">{escape(line2)}</text>']
        if i < len(rows)-1:
            parts += [f'<path d="M500 {y+117} v18 m-7 -7 7 7 7 -7" fill="none" stroke="#216b50" stroke-width="3"/>']
    parts += [f'<text x="50" y="{height-30}" font-size="19">{escape(footer)}</text>', '</g></svg>']
    (HERE / name).write_text('\n'.join(parts) + '\n', encoding='utf-8')


figure('rsi-target.svg', 'RSIが改善する場所', '対象：説明を確かめる実行テストを考える probe_planner の指示文', [
    ('生徒の説明とコード', '例：「入力が空でもエラーにならない」', '評価では正解つきの合成提出物を使用'),
    ('Geminiが実行テストを設計', '空の入力で動かし、「エラーなし」を期待結果にする', 'RSIは、この設計を頼む指示文を書き直す'),
    ('隔離環境でコードを実行', '実際にエラーが起きるかを記録する', '期待結果をコードの挙動に合わせて書き換えない'),
    ('実行結果と説明を機械的に比較', '説明と食い違えば、確認が必要な主張として扱う', '失敗したテスト設計と結果が、次の改善の材料になる'),
], '改善するのは指示文。モデルの重みや生徒のコードは更新しない。')
figure('rsi-loop.svg', '測る → 振り返る → 書き直す → 確かめる', '候補生成から推薦までを自動化し、採用は人が判断する', [
    ('開始時の指示文を測定', '改善用データで複数回試し、平均点と点数の幅を記録', '点数＝提出物ごとの「正しく扱えた主張の割合」の平均'),
    ('親を選び、Geminiが書き直す', '提出物ごとの最高点の回数に応じて、親候補を抽選', 'その段階で直せる失敗例・成功例・実行記録を読む'),
    ('検査して、候補を評価', '差し込み口・長さ・例の丸写しなどを機械的に検査', '親よりぶれを超えて改善し、必須ルールも守れば候補に残す'),
    ('候補を親にして探索を繰り返す', '不採用の理由も含め、全候補と親子関係を保存', '終了後、残った候補から最良のものを選ぶ'),
    ('別データで最終確認', '開始時より点数が下がらず、必須ルールも守れば推薦', '最終確認の失敗例は書き直し役に渡さない'),
    ('人が差分を読み、採用する', 'promote で新しい指示文の版を作り、ACTIVEを切り替える', '推薦だけでは本番の指示文は変わらない'),
], 'UIのRSIテストは、この過程の実測記録を再生するモード。')
