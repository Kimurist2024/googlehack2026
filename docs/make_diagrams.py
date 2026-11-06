"""セキュリティの図（SVG）を作る。文言や配置を変えたら、もう一度実行する。

    .venv/bin/python docs/make_diagrams.py

README と SECURITY.md が docs/*.svg を表示する。スライドには、ブラウザで開いて書き出した PNG を使う。

アイコンは、どれにも当てはまる簡単な絵（ブラウザ、サーバー、データベースなど）を自前で描いている。
公式のアイコンを使いたいときは、提供元の利用条件に沿って入手したファイルを docs/icons/ に
OFFICIAL_ICONS の名前（例：cloud-run.svg）で置いて実行し直すと、その絵の代わりに埋め込む。
"""
import base64
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
W, H = 1600, 900
FONT = "'Noto Sans JP','Noto Sans CJK JP','Hiragino Sans','Yu Gothic UI','Meiryo',sans-serif"
INK, MUTED, LINE, BG, CARD = "#1f2a30", "#55626a", "#44545c", "#efefef", "#ffffff"
GROUPS = {
    "blue": ("#4a86e8", "#1fae8f", "#ffffff"),
    "teal": ("#6fe0cf", "#6fe0cf", INK),
    "pink": ("#f2a7a7", "#f6c9c9", INK),
    "amber": ("#f0b44c", "#f7d48f", INK),
    "violet": ("#9b8cf2", "#cfc6fb", INK),
    "slate": ("#8a9aa3", "#d3dadd", INK),
    "red": ("#d9534f", "#f3c2c0", INK),
}


# 自前の絵（24px 四方を中心 0,0 で描く）。"C" は線の色に置き換える
PICTOGRAMS = {
    "browser": '<rect x="-15" y="-12" width="30" height="24" rx="4"/><path d="M-15,-5 H15"/>'
    '<circle cx="-10" cy="-8.5" r="1.4" fill="C"/><circle cx="-6" cy="-8.5" r="1.4" fill="C"/><circle cx="-2" cy="-8.5" r="1.4" fill="C"/>',
    "server": '<rect x="-14" y="-13" width="28" height="11" rx="2.5"/><rect x="-14" y="2" width="28" height="11" rx="2.5"/>'
    '<circle cx="9" cy="-7.5" r="1.6" fill="C"/><circle cx="9" cy="7.5" r="1.6" fill="C"/><path d="M-9,-7.5 H2 M-9,7.5 H2"/>',
    "database": '<ellipse cx="0" cy="-9" rx="12" ry="4.5"/><path d="M-12,-9 V9 A12,4.5 0 0 0 12,9 V-9 M-12,0 A12,4.5 0 0 0 12,0"/>',
    "ai": '<rect x="-14" y="-12" width="28" height="19" rx="6"/><path d="M-6,7 L-10,13 L1,7"/>'
    '<circle cx="-6" cy="-2.5" r="1.6" fill="C"/><circle cx="0" cy="-2.5" r="1.6" fill="C"/><circle cx="6" cy="-2.5" r="1.6" fill="C"/>',
    "shield": '<path d="M0,-14 L12,-9 V0 C12,8 6,12 0,15 C-6,12 -12,8 -12,0 V-9 Z"/><path d="M-6,0 L-1.5,5 L7,-4"/>',
    "sandbox": '<path d="M0,-14 L13,-7 V7 L0,14 L-13,7 V-7 Z M-13,-7 L0,0 L13,-7 M0,0 V14"/>',
    "key": '<circle cx="-6" cy="-6" r="6.5"/><path d="M-1.5,-1.5 L13,13 M7,7 L10.5,3.5 M10,10 L13.5,6.5"/>',
    "lock": '<rect x="-11" y="-3" width="22" height="16" rx="3"/><path d="M-6.5,-3 V-8 A6.5,6.5 0 0 1 6.5,-8 V-3"/><circle cx="0" cy="5" r="2" fill="C"/>',
    "laptop": '<rect x="-12" y="-11" width="24" height="16" rx="2"/><path d="M-16,9 H16"/>',
    "phone": '<rect x="-8" y="-14" width="16" height="28" rx="3.5"/><path d="M-3,9 H3"/>',
    "log": '<path d="M-10,-14 H5 L10,-9 V14 H-10 Z"/><path d="M-6,-5 H6 M-6,1 H6 M-6,7 H2"/>',
    "check": '<rect x="-11" y="-11" width="22" height="25" rx="3"/><path d="M-5,-11 V-14 H5 V-11"/><path d="M-5,2 L-1,6 L6,-2"/>',
    "cloud": '<path d="M-10,9 H10 A6.5,6.5 0 0 0 9,-4 A9,9 0 0 0 -8,-5 A7,7 0 0 0 -10,9 Z"/>',
    "network": '<circle cx="0" cy="-10" r="4"/><circle cx="-11" cy="9" r="4"/><circle cx="11" cy="9" r="4"/>'
    '<path d="M-2,-6.5 L-9,5.5 M2,-6.5 L9,5.5 M-7,9 H7"/>',
    "package": '<rect x="-13" y="-9" width="26" height="21" rx="2"/><path d="M-13,-3 H13 M-4,-9 V-3 M4,-9 V-3"/>',
}
# docs/icons/ に置くと自前の絵の代わりに使うファイル名
OFFICIAL_ICONS = {
    "server": "cloud-run",
    "database": "firestore",
    "ai": "gemini",
    "shield": "model-armor",
    "sandbox": "code-execution",
    "key": "cloud-kms",
    "lock": "secret-manager",
    "log": "cloud-logging",
    "browser": "firebase-hosting",
}


def official_icon(kind: str) -> str | None:
    name = OFFICIAL_ICONS.get(kind)
    for suffix, mime in ((".svg", "image/svg+xml"), (".png", "image/png")):
        path = HERE / "icons" / f"{name}{suffix}"
        if name and path.exists():
            # README では SVG が画像として表示され、外部のファイルを読めないので、中に埋め込む
            return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return None


def text_width(text: str, size: float) -> float:
    return sum(size * (0.6 if ord(char) < 0x2E80 else 1.0) for char in text)


def wrap(text: str, size: float, width: float) -> list[str]:
    lines, current = [], ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        if text_width(current + char, size) > width and current:
            lines.append(current)
            current = char
        else:
            current += char
    return lines + ([current] if current else [])


ADDED, PLANNED = "#c0392b", "#b7791f"
# 行頭が "+ " なら「セキュリティで追加」、"~ " なら「統合時に対応」として色を変える
MARKS = {"+ ": ("＋", ADDED), "~ ": ("◇", PLANNED)}


class Svg:
    def __init__(self, title: str, subtitle: str, height: int = H) -> None:
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" font-family="{FONT}">',
            "<defs>"
            f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker>'
            '<marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c9302c"/></marker>'
            "</defs>",
            f'<rect width="{W}" height="{height}" fill="{BG}"/>',
            f'<text x="40" y="78" font-size="46" font-weight="700" fill="{INK}">{escape(title)}</text>',
            f'<text x="{48 + text_width(title, 46)}" y="76" font-size="20" fill="{MUTED}">{escape(subtitle)}</text>',
            f'<rect x="0" y="100" width="{W}" height="4" fill="#d4d4d4"/>',
        ]

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def icon(self, kind, cx, cy, color, r=28):
        """白い丸の中にアイコンを置く。docs/icons/ に公式のアイコンがあればそれを使う。"""
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#ffffff" stroke="{color}" stroke-width="3"/>')
        official = official_icon(kind)
        if official:
            size = r * 1.3
            self.add(f'<image href="{official}" x="{cx - size / 2}" y="{cy - size / 2}" width="{size}" height="{size}"/>')
            return
        scale = r / 26
        shape = PICTOGRAMS[kind].replace('"C"', f'"{color}"')
        self.add(
            f'<g transform="translate({cx},{cy}) scale({scale})" fill="none" stroke="{color}" stroke-width="2.4" '
            f'stroke-linecap="round" stroke-linejoin="round">{shape}</g>'
        )

    def group(self, x, y, w, h, label, color, dashed=False, icon=None):
        border, tab, tab_ink = GROUPS[color]
        dash = ' stroke-dasharray="10 7"' if dashed else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{border}" stroke-width="4"{dash}/>')
        tab_w = text_width(label, 22) + 32
        self.add(f'<rect x="{x + 22}" y="{y - 22}" width="{tab_w}" height="42" fill="{tab}"/>')
        self.add(f'<text x="{x + 38}" y="{y + 7}" font-size="22" font-weight="700" fill="{tab_ink}">{escape(label)}</text>')
        if icon:
            # 見出しに重ならない位置に置く
            cx = max(x + w - 46, x + 22 + tab_w + 28 + 10)
            self.icon(icon, cx, y, border if color != "teal" else "#1fae8f")

    def card(self, x, y, w, h, title, lines=(), accent="#1fae8f", size=15, title_size=17, fill=CARD, icon=None):
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="#cfd6d9"/>')
        self.add(f'<rect x="{x}" y="{y + 10}" width="5" height="{h - 20}" rx="2" fill="{accent}"/>')
        if icon:
            self.icon(icon, x + w - 24, y + 26, accent, r=17)
        cursor = y + 12 + title_size
        for line in wrap(title, title_size, w - 32 - (40 if icon else 0)):
            self.add(f'<text x="{x + 18}" y="{cursor}" font-size="{title_size}" font-weight="700" fill="{INK}">{escape(line)}</text>')
            cursor += title_size * 1.35
        cursor += 2
        for item in lines:
            mark, color = "・", MUTED
            if item[:2] in MARKS:
                (mark, color), item = MARKS[item[:2]], item[2:]
            for index, line in enumerate(wrap(item, size, w - 46 - (34 if icon else 0))):
                bullet = mark if index == 0 else "　"
                self.add(f'<text x="{x + 18}" y="{cursor}" font-size="{size}" fill="{color}">{bullet}{escape(line)}</text>')
                cursor += size * 1.45
        return cursor

    def pill(self, x, y, text, fill="#ffffff", ink=INK, size=15, stroke="#cfd6d9", bold=False):
        w = text_width(text, size) + 26
        weight = ' font-weight="700"' if bold else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{size + 16}" rx="{(size + 16) / 2}" fill="{fill}" stroke="{stroke}"/>')
        self.add(f'<text x="{x + 13}" y="{y + size + 4}" font-size="{size}" fill="{ink}"{weight}>{escape(text)}</text>')
        return w

    def arrow(self, points, label=None, label_at=None, red=False, dashed=False, both=False, size=16):
        color, marker = ("#c9302c", "arrow-red") if red else (LINE, "arrow")
        path = " ".join(f"{'M' if i == 0 else 'L'}{px},{py}" for i, (px, py) in enumerate(points))
        dash = ' stroke-dasharray="9 7"' if dashed else ""
        start = f' marker-start="url(#{marker})"' if both else ""
        self.add(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3.5"{dash} marker-end="url(#{marker})"{start}/>')
        if label:
            lx, ly = label_at
            for index, line in enumerate(label.split("\n")):
                self.add(
                    f'<text x="{lx}" y="{ly + index * size * 1.3}" font-size="{size}" fill="{color if red else INK}" '
                    f'text-anchor="middle" paint-order="stroke" stroke="{BG}" stroke-width="6">{escape(line)}</text>'
                )

    def legend(self, x, y, items):
        """右上の凡例。items は（記号, 色, 説明）の並び。"""
        for mark, color, label in items:
            self.note(x, y, f"{mark} {label}", size=17, color=color, bold=True)
            x += text_width(f"{mark} {label}", 17) + 28

    def note(self, x, y, text, size=17, color=INK, anchor="start", bold=False):
        weight = ' font-weight="700"' if bold else ""
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}"{weight}>{escape(text)}</text>')

    def flow(self, x, y, labels, fills, size=13):
        """横に並んだ丸い札と矢印（順に通る処理）。"""
        for index, (label, fill) in enumerate(zip(labels, fills, strict=True)):
            stroke = ADDED if fill == "added" else "#cfd6d9"
            w = self.pill(x, y, label, fill="#fde8e8" if fill == "added" else "#ffffff", size=size, bold=True, stroke=stroke)
            if index < len(labels) - 1:
                self.arrow([(x + w + 3, y + size / 2 + 8), (x + w + 19, y + size / 2 + 8)])
            x += w + 22

    def tags(self, x, y, labels, width, size=14):
        """矢印のない札を幅に合わせて折り返して並べる（別々の機能）。最後の行の下端を返す。"""
        left = x
        for label in labels:
            w = text_width(label, size) + 26
            if x + w > left + width:
                x, y = left, y + size + 26
            self.pill(x, y, label, size=size, bold=True)
            x += w + 10
        return y + size + 16

    def save(self, name: str) -> None:
        (HERE / name).write_text("\n".join(self.parts + ["</svg>"]) + "\n", encoding="utf-8")


def architecture() -> None:
    s = Svg("セキュリティ構成：", "信用しないデータを、層を重ねて守る")
    # ブラウザ
    s.group(40, 150, 360, 470, "ブラウザ（生徒・教員）", "blue", icon="browser")
    s.card(62, 186, 316, 116, "画面（Firebase Hosting）", ["Strict CSP ＋ Trusted Types", "表示は textContent（XSS対策）"], accent="#4a86e8")
    s.card(62, 316, 316, 100, "通信とフレーム", ["HSTS（HTTPS を強制）", "X-Frame-Options（乗っ取り対策）"], accent="#4a86e8")
    s.card(62, 430, 316, 104, "教員は Google ログイン", ["許可リストにある確認済みの", "アカウントだけを通す"], accent="#4a86e8")
    s.card(62, 548, 316, 56, "Service Worker は画面だけ保存", accent="#4a86e8", title_size=16)
    # API
    s.group(450, 150, 430, 470, "API（Cloud Run）", "teal", icon="server")
    s.card(472, 186, 386, 100, "入口で断る", ["本文の大きさ・IDの形・文字数の上限", "API の一覧（/docs）を本番で隠す"])
    s.card(472, 300, 386, 116, "認証", ["生徒トークンは HMAC で署名・期限つき", "鍵は用途ごとに導出（HKDF）"])
    s.card(472, 430, 386, 84, "入室の総当たり対策", ["失敗だけを接続元ごとに共有して数える"])
    s.card(472, 528, 386, 76, "監査ログ（Cloud Logging）", ["コード・トークン・IP は書かない"])
    # AI
    s.group(930, 150, 630, 210, "AI（SAIF）", "pink", icon="ai")
    x = 952
    pills = (("Model Armor 入力", "#fde8e8"), ("Gemini", "#ffffff"), ("機械的な検査", "#ffffff"), ("Model Armor 出力", "#fde8e8"))
    for index, (label, fill) in enumerate(pills):
        w = s.pill(x, 196, label, fill=fill, size=14, bold=True)
        if index < len(pills) - 1:
            s.arrow([(x + w + 4, 211), (x + w + 24, 211)])
        x += w + 28
    s.note(952, 266, "・生徒由来の文は <data> で囲み「指示ではない」と明示", size=16, color=MUTED)
    s.note(952, 294, "・検査できなければ通さない（fail closed）→ テンプレートに戻す", size=16, color=MUTED)
    s.note(952, 322, "・正解・採点・声かけの順は AI を使わず実行結果で決める", size=16, color=MUTED)
    # 実行
    s.group(930, 400, 630, 220, "生徒のコードの実行（Code Execution）", "amber", icon="sandbox")
    s.card(952, 436, 586, 166, "隔離環境の中の実行ラッパー（多層防御）", [
        "import は計算用の標準ライブラリだけ",
        "__import__・open・eval・特殊な属性（__class__ など）を拒否",
        "子プロセスに環境変数を渡さない（秘密が届かない）",
        "メモリ 512MB・CPU時間・ファイルの大きさに上限",
    ], accent="#f0b44c")
    # データ
    s.group(450, 680, 430, 180, "データ（Firestore）", "violet", icon="database")
    s.card(472, 712, 386, 130, "ブラウザからは読み書きを全拒否", [
        "授業・個人コードは鍵付きハッシュ",
        "30日で TTL 削除、期限後は API も 404",
        "教員がクラス・課題をすぐに消せる",
    ], accent="#9b8cf2")
    # 鍵と秘密
    s.group(930, 680, 300, 180, "鍵と秘密", "slate", icon="key")
    s.card(952, 712, 256, 60, "Secret Manager", ["SESSION_SECRET"], accent="#8a9aa3", size=14, icon="lock")
    s.card(952, 782, 256, 60, "Cloud KMS", ["授業パッケージの署名"], accent="#8a9aa3", size=14, icon="key")
    # 教員PC
    s.group(1270, 680, 290, 180, "教員PC（LAN版）", "red", dashed=True)
    s.card(1292, 712, 246, 130, "障害時に引き継ぐ", ["署名を確かめて取り込む", "外へは一度も接続しない", "教員の操作は教員PCだけ"], accent="#d9534f", size=14, icon="laptop")
    # 監査・凡例
    s.group(40, 680, 360, 180, "記録と見張り", "slate", icon="log")
    s.card(62, 712, 316, 130, "Cloud Logging", ["誰が・いつ・何をしたか", "CSV の持ち出しとパッケージの発行", "入室の失敗と上限超え"], accent="#8a9aa3")
    # 矢印
    s.arrow([(402, 380), (448, 380)], "HTTPS", (425, 366), size=14)
    s.arrow([(882, 255), (928, 255)])
    s.arrow([(882, 520), (928, 520)], "コード", (905, 506), size=14)
    s.arrow([(760, 622), (760, 652)])
    s.note(772, 646, "読み書き", size=15)
    s.arrow([(880, 600), (1150, 654)])
    s.note(1162, 648, "署名を依頼", size=15)
    s.arrow([(1232, 812), (1268, 812)], dashed=True)
    s.arrow([(450, 590), (300, 652)])
    s.note(200, 640, "監査ログ", size=15)
    s.save("security-architecture.svg")


def resilience() -> None:
    s = Svg("ネットが落ちても授業を止めない：", "準備はクラウド、授業はどこでも")
    # 授業前
    s.group(40, 150, 1520, 250, "授業前：準備はクラウド（AI と隔離実行はここだけ）", "teal", icon="cloud")
    steps = [
        ("提出コード", ["教員がまとめて登録"]),
        ("隔離して実行", ["Code Execution", "実行結果から正解を作る"]),
        ("問いを選ぶ・説明", ["Gemini ＋ Model Armor"]),
        ("授業パッケージ", ["名簿・問い・正解だけ"]),
    ]
    x = 62
    for index, (title, lines) in enumerate(steps):
        s.card(x, 192, 250, 96, title, lines)
        if index < len(steps) - 1:
            s.arrow([(x + 252, 240), (x + 286, 240)])
        x += 290
    s.card(1222, 186, 316, 196, "パッケージの守り", icon="lock", lines=[
        "Cloud KMS で署名（ECDSA P-256）",
        "AES-256-GCM で暗号化",
        "解除コードは画面に1回だけ",
        "コードは scrypt の照合値だけ",
        "発行から7日で失効",
    ], accent="#1fae8f", size=15)
    s.arrow([(1182, 240), (1220, 240)])
    s.note(62, 330, "授業中に要るのは「配り済みの問い・正解・採点の計算」だけ。AI もコードの実行もいらない。", size=19, bold=True)
    s.note(62, 362, "だから授業はネットがなくても回る。", size=19, color=MUTED)
    # 授業中
    cols = [
        (40, "① ふだん", "teal", "Cloud Run ＋ Firestore", ["生徒は自分の端末から入室・解答", "教員は授業前にパッケージを保存", "結果と記録はクラウドが正", "LAN の結果はクラウドの正解で採点し直す（教員PCの採点は使わない）"]),
        (560, "② ネット障害（LANは動く）", "red", "教員PCで引き継ぐ", ["署名を確かめてから取り込む", "生徒は同じコードで教員PCへ", "外へは一度も接続しない（試験で保証）", "教員の操作は教員PCからだけ", "保存は暗号化したファイル"]),
        (1080, "③ LANも障害", "amber", "生徒の端末にためる", ["画面は Service Worker で開ける", "解答は端末に保存、つながったら送る", "送り直しは何度でも同じ結果（冪等）", "持ち時間超過は「オフライン提出」と表示"]),
    ]
    icons = {"teal": "server", "red": "laptop", "amber": "phone"}
    for x0, label, color, title, lines in cols:
        s.group(x0, 470, 480, 290, label, color, dashed=color != "teal", icon=icons[color])
        s.card(x0 + 22, 508, 436, 232, title, lines, accent=GROUPS[color][0], size=16, title_size=19)
    s.arrow([(940, 290), (940, 466)], dashed=True)
    s.note(952, 432, "教員PCに保存", size=16)
    s.arrow([(560, 640), (522, 640)], dashed=True)
    s.note(541, 622, "結果", size=15, anchor="middle")
    s.arrow([(1080, 700), (1042, 700)], dashed=True)
    s.arrow([(1300, 762), (1300, 822), (300, 822), (300, 764)], dashed=True)
    s.note(800, 856, "つながったら送る（端末の時計は信用せず、受け付けはサーバーの時刻）", size=17, anchor="middle")
    s.save("resilience-flow.svg")


def ai_guard() -> None:
    s = Svg("AI の入出力の検査：", "SAIF に沿い、検査できなければ通さない")
    s.group(40, 150, 1520, 470, "生徒由来の文が画面に出るまで", "pink", icon="shield")
    steps = [
        ("生徒の入力", ["コードと答え", "信用しないデータとして扱う"], "#8a9aa3"),
        ("減らして囲む", ["コメントを消す", "答えは先頭200字", "<data> で囲む"], "#8a9aa3"),
        ("Model Armor 入力", ["プロンプト注入", "ジェイルブレイク", "有害・悪意URL・機密"], "#d9534f"),
        ("Gemini", ["問いの選定", "つまずきの説明"], "#4a86e8"),
        ("機械的な検査", ["JSONの形・長さ", "評価語・URL", "記録にない数値"], "#d9534f"),
        ("Model Armor 出力", ["有害な表現", "悪意のあるURL"], "#d9534f"),
    ]
    x, width, gap = 62, 194, 34
    step_icons = {"生徒の入力": "log", "Model Armor 入力": "shield", "Gemini": "ai", "機械的な検査": "check", "Model Armor 出力": "shield"}
    for title, lines, accent in steps:
        s.card(x, 196, width, 200, title, lines, accent=accent, size=15, title_size=16, icon=step_icons.get(title))
        s.arrow([(x + width + 4, 296), (x + width + gap - 4, 296)])
        if accent == "#d9534f":
            s.arrow([(x + width / 2, 398), (x + width / 2, 498)], red=True, dashed=True)
        x += width + gap
    s.add(f'<rect x="{x}" y="256" width="{1538 - x}" height="80" rx="12" fill="#e2f1ea" stroke="#1fae8f" stroke-width="2"/>')
    s.note((x + 1538) / 2, 304, "画面へ", size=20, anchor="middle", bold=True)
    s.add('<rect x="62" y="500" width="1476" height="96" rx="12" fill="#fde8e8" stroke="#d9534f" stroke-width="2"/>')
    s.note(800, 540, "検出した・検査に失敗した・API が落ちた → Gemini を使わず、テンプレートの文に戻す（fail closed）", size=20, anchor="middle", bold=True)
    s.note(800, 574, "授業は止まらない。どのフィルタが反応したかは監査ログに残す", size=17, anchor="middle", color=MUTED)
    s.group(40, 680, 1520, 180, "AI に任せないこと", "slate", icon="check")
    s.card(62, 716, 720, 124, "正解・採点・声をかける順", ["コードを実際に動かした結果と計算だけで決まる", "Gemini の返答は問いの選定と文面だけに使う"], accent="#8a9aa3", size=16, title_size=18)
    s.card(806, 716, 732, 124, "本番で Model Armor の設定がないとき", ["Gemini を使わず、最初からテンプレートで動く", "検査なしで Gemini を呼ぶのは手元の開発だけ"], accent="#8a9aa3", size=16, title_size=18)
    s.save("ai-guard-flow.svg")


SYSTEM_H = 960


def system_kimura() -> None:
    """木村さんのブランチ（feature/kimura）の構成。セキュリティの変更を入れる前。"""
    s = Svg("木村さんの実装：", "feature/kimura（0a28f28 時点）の全体構成", SYSTEM_H)
    s.group(40, 150, 380, 440, "画面（Firebase Hosting）", "blue", icon="browser")
    s.card(62, 186, 336, 130, "教員の画面", ["Google ログイン", "課題の準備・受付・締切", "声をかける順・声かけメモ"], accent="#4a86e8")
    s.card(62, 330, 336, 130, "生徒の画面", ["授業コード＋個人コードで入室", "解答するとその場で採点", "振り返りの対話（10回まで）"], accent="#4a86e8")
    s.card(62, 474, 336, 96, "web/（HTML・CSS・JS）", ["外部のライブラリなし"], accent="#4a86e8")
    s.group(470, 150, 440, 440, "API（Cloud Run・FastAPI）", "teal", icon="server")
    s.card(492, 186, 396, 112, "問いを作る（授業前）", ["提出（zip）を読み、隔離して実行", "実行結果から問いと正解を作る"])
    s.card(492, 312, 396, 140, "授業と締切", ["入室・解答・採点（AI を使わない）", "締切で声かけメモとクラスのまとめ", "振り返りの対話（答えは言わない）"])
    s.card(492, 466, 396, 104, "声をかける順", ["誤答と持ち時間から計算（AI を使わない）", "CSV の書き出し"])
    s.group(960, 150, 600, 230, "AI（Gemini 3.5 Flash-Lite）", "pink", icon="ai")
    s.tags(982, 192, ["問いの選定", "つまずきの説明", "声かけメモ", "クラスのまとめ", "振り返りの対話"], 556)
    s.note(982, 300, "・出力は checked_text で検査し、通らなければ既定の文に戻す", size=16, color=MUTED)
    s.note(982, 330, "・生徒の対話はデータとして区切って渡す", size=16, color=MUTED)
    s.note(982, 360, "・正解・採点・声をかける順には使わない", size=16, color=MUTED)
    s.group(960, 420, 600, 170, "生徒のコードの実行（Code Execution）", "amber", icon="sandbox")
    s.card(982, 456, 556, 114, "隔離環境で実行（asia-northeast1）", ["import は計算用の標準ライブラリだけ", "実行の記録・出力・変えたときの結果を返す"], accent="#f0b44c")
    s.group(40, 650, 380, 280, "授業の流れ", "slate", icon="check")
    s.card(62, 686, 336, 224, "教員と生徒の5分", [
        "① 提出をまとめて登録", "② 問いを作る（実行＋Gemini）", "③ 受付を始める", "④ 生徒が解答・その場で採点",
        "⑤ 締切 → メモとまとめ", "⑥ 声をかける順に話しかける",
    ], accent="#8a9aa3", size=15)
    s.group(470, 650, 440, 280, "データ（Firestore）", "violet", icon="database")
    s.card(492, 686, 396, 224, "asia-northeast1・ネイティブモード", [
        "クラスと名簿（出席番号だけ、氏名なし）", "提出・問い・正解・解答", "声かけメモ・クラスのまとめ・対話の回数",
        "授業コード・個人コードはハッシュ", "ブラウザからは読み書きを全拒否",
    ], accent="#9b8cf2", size=15)
    s.group(960, 650, 600, 280, "認証と秘密", "slate", icon="key")
    s.card(982, 686, 268, 120, "Firebase Auth", ["Google ログイン", "許可した教員だけ"], accent="#8a9aa3", size=15, icon="lock")
    s.card(1270, 686, 268, 120, "Secret Manager", ["SESSION_SECRET", "トークンとハッシュの鍵"], accent="#8a9aa3", size=15, icon="key")
    s.card(982, 820, 556, 90, "公開", ["mushitori-hackathon.web.app（/v1/** は Cloud Run へ）"], accent="#8a9aa3", size=15)
    s.arrow([(422, 380), (468, 380)], "HTTPS", (445, 366), size=14)
    s.arrow([(912, 265), (958, 265)])
    s.arrow([(912, 505), (958, 505)], "コード", (935, 491), size=14)
    s.arrow([(820, 592), (820, 626)])
    s.note(832, 618, "読み書き", size=15)
    s.arrow([(912, 580), (1260, 628)])
    s.note(1272, 622, "トークンの検証", size=15)
    s.save("system-kimura.svg")


def system_integrated() -> None:
    """木村さんの実装にセキュリティ（security/Taiga）を合わせた全体構成。"""
    s = Svg("統合後の全体構成：", "木村さんの実装 ＋ セキュリティ", SYSTEM_H)
    s.legend(1010, 76, [("・", MUTED, "木村さんの実装"), ("＋", ADDED, "セキュリティで追加"), ("◇", PLANNED, "統合時に対応")])
    s.group(40, 150, 380, 440, "画面（Firebase Hosting）", "blue", icon="browser")
    s.card(62, 186, 336, 130, "教員の画面", ["Google ログイン", "準備・受付・締切・声をかける順", "+ 授業パッケージの保存・取り込み"], accent="#4a86e8")
    s.card(62, 330, 336, 104, "生徒の画面", ["入室・解答・採点・振り返り", "+ 回線が切れたら解答を端末にためる"], accent="#4a86e8")
    s.card(62, 448, 336, 122, "画面の守り", ["+ Strict CSP・Trusted Types", "+ HSTS・クリックジャッキング対策", "+ Service Worker は画面だけ保存"], accent=ADDED)
    s.group(470, 150, 440, 440, "API（Cloud Run・FastAPI）", "teal", icon="server")
    s.card(492, 186, 396, 112, "問いを作る（授業前）", ["提出を隔離して実行し、問いと正解", "+ 危ない書き方は実行せず先生に表示"])
    s.card(492, 312, 396, 122, "授業と締切", ["入室・解答・採点（AI を使わない）", "声かけメモ・まとめ・振り返りの対話", "+ 30日で自動削除・教員がすぐ消せる"])
    s.card(492, 448, 396, 122, "API の守り", ["+ 本文・ID・文字数の上限", "+ 用途別の鍵・入室制限を全体で共有", "+ 監査ログ（コード・IP は残さない）"], accent=ADDED)
    s.group(960, 150, 600, 230, "AI（Gemini ＋ Model Armor）", "pink", icon="ai")
    s.flow(982, 196, ["Model Armor 入力", "Gemini", "checked_text", "Model Armor 出力"], ["added", "", "", "added"])
    s.note(982, 270, "＋ 生徒由来の文は <data> で囲み、検査できなければ通さない", size=16, color=ADDED)
    s.note(982, 300, "＋ 本番で Model Armor の設定がなければ Gemini を使わない", size=16, color=ADDED)
    s.note(982, 330, "◇ 声かけメモ・まとめ・振り返りの対話にも Model Armor", size=16, color=PLANNED)
    s.note(982, 360, "・正解・採点・声をかける順には使わない", size=16, color=MUTED)
    s.group(960, 420, 600, 170, "生徒のコードの実行（Code Execution）", "amber", icon="sandbox")
    s.card(982, 456, 556, 114, "隔離環境の中の実行ラッパー", [
        "import は計算用の標準ライブラリだけ", "+ __import__・open・eval・特殊な属性を拒否", "+ 環境変数を渡さない・メモリと CPU 時間に上限",
    ], accent="#f0b44c", size=15)
    s.group(40, 650, 380, 280, "ネット障害のとき", "red", dashed=True)
    s.card(62, 686, 336, 130, "教員PC（校内LAN版）", ["+ 署名を確かめて取り込む", "+ 外へは一度も接続しない"], accent=ADDED, size=15, icon="laptop")
    s.card(62, 830, 336, 80, "生徒の端末", ["+ 解答をためて、つながったら送る"], accent=ADDED, size=15, icon="phone")
    s.group(470, 650, 440, 280, "データ（Firestore）", "violet", icon="database")
    s.card(492, 686, 396, 224, "asia-northeast1・ネイティブモード", [
        "クラスと名簿（出席番号だけ）", "提出・問い・正解・解答・メモ", "ブラウザからは読み書きを全拒否",
        "+ 用途別の鍵でコードをハッシュ", "+ 期限の印（TTL）と入室の失敗の記録",
    ], accent="#9b8cf2", size=15)
    s.group(960, 650, 600, 280, "認証・鍵・記録", "slate", icon="key")
    s.card(982, 686, 268, 104, "Firebase Auth", ["Google ログイン", "許可した教員だけ"], accent="#8a9aa3", size=15, icon="lock")
    s.card(1270, 686, 268, 104, "Secret Manager", ["SESSION_SECRET"], accent="#8a9aa3", size=15, icon="key")
    s.card(982, 806, 268, 104, "Cloud KMS", ["+ 授業パッケージに署名", "+ 秘密鍵は外に出ない"], accent=ADDED, size=15, icon="key")
    s.card(1270, 806, 268, 104, "Cloud Logging", ["+ 監査ログ", "+ 持ち出しと削除の記録"], accent=ADDED, size=15, icon="log")
    s.arrow([(422, 380), (468, 380)], "HTTPS", (445, 366), size=14)
    s.arrow([(912, 265), (958, 265)])
    s.arrow([(912, 505), (958, 505)], "コード", (935, 491), size=14)
    s.arrow([(820, 592), (820, 626)])
    s.note(832, 618, "読み書き", size=15)
    s.arrow([(912, 580), (1260, 628)])
    s.note(1272, 622, "検証・署名・記録", size=15)
    s.arrow([(480, 592), (395, 640)], dashed=True)
    s.note(260, 626, "授業パッケージ", size=15, color=ADDED)
    s.save("system-integrated.svg")


if __name__ == "__main__":
    architecture()
    resilience()
    ai_guard()
    system_kimura()
    system_integrated()
    print("docs/*.svg を作りました")
