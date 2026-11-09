"""デモ動画を自動で収録する。合成データだけを使い、MP4 を書き出す（既定は demo/。Git では管理しない）。

使い方: apps/api で ../../.venv/bin/python scripts/record_demo.py
必要なもの: requirements-demo.txt と Google Chrome
字幕は収録時に画面へ重ねるだけで、アプリ本体には含まれない。

提出する動画は、公開URLの本番で収録する。「ログインせずに試す」の体験用の教員で合成データのデモクラスを作るので、
画面に出る問い・解説・質問案は、本番の Code Execution と Gemini が作ったものになる:
  DEMO_URL=https://mushitori-hackathon.web.app ../../.venv/bin/python scripts/record_demo.py
DEMO_URL を付けないと手元にサーバーを立てて収録する（AI は定型文、実行は手元のサンドボックス。動きの確認用）。
問いを作るときと締め切ったときの待ち時間は動画から省き、省いた秒数を字幕に出す。
公開URLで収録したときは、最後に作ったデモクラスを「データを消す」で消す（動画には映らない）。
書き出す先は DEMO_OUTPUT で変えられる。
"""
import asyncio
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 先に環境変数で指定されていればそれを使う。公開URLで収録するときも、生徒の正解を手元で計算するのに手元のサンドボックスを使う
for name, value in {
    "APP_ENV": "local",
    "SERVE_WEB": "1",
    "SANDBOX_BACKEND": "local",
    "ALLOW_LOCAL_SANDBOX": "1",
    "AI_BACKEND": "template",
    "STORE_BACKEND": "memory",
    "SESSION_SECRET": secrets.token_hex(32),
}.items():
    os.environ.setdefault(name, value)
DEMO_URL = os.environ.get("DEMO_URL", "").rstrip("/")
if not DEMO_URL and (os.environ["AI_BACKEND"] != "gemini" or os.environ["SANDBOX_BACKEND"] != "code_execution"):
    print("注意: AI と実行が本物ではない設定で収録します（提出用には DEMO_URL を付けて公開URLで収録する）", file=sys.stderr)

import imageio_ffmpeg  # noqa: E402
import uvicorn  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

from app.main import create_app  # noqa: E402
from qgen.questions import build_candidates  # noqa: E402
from qgen.sandbox import LocalDevSandbox  # noqa: E402

PORT = 8010
BASE = DEMO_URL or f"http://127.0.0.1:{PORT}"
OUTPUT = Path(os.environ.get("DEMO_OUTPUT") or ROOT.parents[1] / "demo" / "mushitori_demo.mp4")
WAIT_LIMIT_MS = 180_000
# 動画の最初と最後のカードに出す、どこで収録したか
WHERE = "公開中の本番（Code Execution と Gemini）で収録" if DEMO_URL else "手元のサーバーで収録（AI は定型文）"
# 締め切ったあと、誤答のある生徒全員の「本人の説明を聞きたい箇所」がそろったか（裏で作るので、最初の読み込みにはないことがある）
REVIEWS_READY = """(() => {
  const people = [...document.querySelectorAll('#order .person')];
  const needed = people.filter((p) => !/（(\\d+)\\/\\1 問正解）/.test(p.querySelector('h3').textContent)).length;
  return people.length > 0 && document.querySelectorAll('#order .person .memo').length >= needed;
})()"""
# 誤答した生徒が、まちがえた行を自分の言葉で説明する文（合成）
OWN_WORDS = "ここで合計に足していると思ったけど、何回足されるのかは分かっていなかった。"

OVERLAY = """
() => {
  const style = document.createElement('style');
  style.textContent = `
    body { padding-bottom: 150px; scroll-behavior: smooth; }
    #demo-caption { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); width: max-content; max-width: 88%;
      padding: 12px 24px; background: rgba(18,24,20,.93); color: #fff; font: 600 26px/1.5 'Hiragino Sans', sans-serif;
      border-radius: 12px; z-index: 9999; text-align: center; opacity: 0; transition: opacity .25s; }
    #demo-cursor { position: fixed; left: -40px; top: -40px; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%;
      background: rgba(31,111,80,.35); border: 2px solid #1f6f50; z-index: 9998; pointer-events: none;
      transition: left .4s ease, top .4s ease, opacity .25s; }
    #demo-card { position: fixed; inset: 0; z-index: 10000; display: flex; flex-direction: column; gap: 18px; align-items: center;
      justify-content: center; background: #16201a; color: #fff; text-align: center; padding: 0 80px;
      font-family: 'Hiragino Sans', sans-serif; transition: opacity .35s; }
    #demo-card h1 { font-size: 58px; margin: 0; font-weight: 700; }
    #demo-card p { font-size: 30px; margin: 0; line-height: 1.5; }
    #demo-card small { font-size: 20px; color: #a9b8ad; }
  `;
  document.head.append(style);
  const caption = document.createElement('div');
  caption.id = 'demo-caption';
  const cursor = document.createElement('div');
  cursor.id = 'demo-cursor';
  document.body.append(caption, cursor);
}
"""


def skipped(seconds: float) -> str:
    """省いた待ち時間を字幕に添える文。手元の収録のように待ちがなければ何も添えない。"""
    return f"（待ち時間の {seconds:.0f} 秒は省いています）" if seconds >= 1 else ""


class Recorder:
    """CDP の画面配信で JPEG を受け取り、時刻どおりにつないで MP4 にする。"""

    def __init__(self, client, folder: Path) -> None:
        self.client = client
        self.folder = folder
        self.frames: list[tuple[Path, float]] = []
        # 動画から省く区間（開始と終了の時刻）
        self.cuts: list[tuple[float, float]] = []
        self._cut_from: float | None = None
        client.on("Page.screencastFrame", self._on_frame)

    def _on_frame(self, event: dict) -> None:
        path = self.folder / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(event["data"]))
        self.frames.append((path, event["metadata"]["timestamp"]))
        asyncio.create_task(self.client.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]}))

    async def start(self) -> None:
        await self.client.send(
            "Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1}
        )

    async def stop(self) -> None:
        await self.client.send("Page.stopScreencast")

    def begin_cut(self) -> None:
        self._cut_from = time.time()

    def end_cut(self) -> float:
        """省く区間を閉じ、その長さ（秒）を返す。"""
        start, self._cut_from = self._cut_from, None
        self.cuts.append((start, time.time()))
        return self.cuts[-1][1] - start

    def timeline(self) -> list[tuple[Path, float]]:
        """省く区間の中のフレームは最後の1枚だけを区間の終わりに置き、その後ろを区間の長さの分だけ前に詰める。"""
        def cut_of(stamp: float):
            return next((cut for cut in self.cuts if cut[0] <= stamp < cut[1]), None)

        kept = []
        for index, (path, stamp) in enumerate(self.frames):
            cut = cut_of(stamp)
            if cut:
                if index + 1 < len(self.frames) and cut_of(self.frames[index + 1][1]) == cut:
                    continue
                stamp = cut[1]
            kept.append((path, stamp - sum(end - start for start, end in self.cuts if end <= stamp)))
        return kept

    def encode(self, output: Path, tail_sec: float = 1.0) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        frames = self.timeline()
        listing = self.folder / "frames.txt"
        lines = []
        for index, (path, stamp) in enumerate(frames):
            following = frames[index + 1][1] if index + 1 < len(frames) else stamp + tail_sec
            lines += [f"file '{path}'", f"duration {max(following - stamp, 0.001):.3f}"]
        lines.append(f"file '{frames[-1][0]}'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease:in_range=pc:out_range=tv,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white,fps=30",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
            ],
            check=True,
        )


def answer_key(session: dict, quiz: dict) -> dict[str, str]:
    """生徒の問いの正解を手元で計算する。正解は API では返らないので、
    サーバーと同じ実行記録と種（課題のIDと生徒のID）から候補を作り、問いのIDで突き合わせる。"""
    body = session["token"].split(".")[0]
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    result = LocalDevSandbox().analyze(quiz["code"], quiz["stdin"])
    candidates = {item.id: item for item in build_candidates(result, quiz["stdin"], f"{session['assignment_id']}:{claims['student']}")}
    key = {}
    for question in quiz["questions"]:
        found = candidates.get(question["id"])
        if found is None:
            raise RuntimeError(f"問い {question['id']} の正解を手元で再現できません")
        key[question["id"]] = found.answer
    return key


class Demo:
    def __init__(self, page, recorder: Recorder) -> None:
        self.page = page
        self.recorder = recorder
        # 出席番号ごとの、問いのIDと正解
        self.keys: dict[str, dict[str, str]] = {}

    async def card(self, title: str, lines: list[str], note: str, hold: float) -> None:
        await self.page.evaluate(
            """([title, lines, note]) => {
              document.getElementById('demo-card')?.remove();
              const card = document.createElement('div');
              card.id = 'demo-card';
              const heading = document.createElement('h1');
              heading.textContent = title;
              card.append(heading);
              for (const line of lines) { const p = document.createElement('p'); p.textContent = line; card.append(p); }
              const small = document.createElement('small');
              small.textContent = note;
              card.append(small);
              document.body.append(card);
            }""",
            [title, lines, note],
        )
        await asyncio.sleep(hold)

    async def hide_card(self) -> None:
        await self.page.evaluate("document.getElementById('demo-card').style.opacity = 0")
        await asyncio.sleep(0.4)
        await self.page.evaluate("document.getElementById('demo-card').remove()")

    async def say(self, text: str, hold: float = 2.8) -> None:
        await self.page.evaluate(
            "(text) => { const c = document.getElementById('demo-caption'); c.textContent = text; c.style.opacity = text ? 1 : 0; }", text
        )
        await asyncio.sleep(hold)

    async def show(self, locator, hold: float = 0.7) -> None:
        await locator.evaluate("(el) => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
        await asyncio.sleep(hold)

    async def click(self, locator, hold: float = 0.7) -> None:
        await self.show(locator, 0.6)
        box = await locator.bounding_box()
        await self.page.evaluate(
            "([x, y]) => { const c = document.getElementById('demo-cursor'); c.style.opacity = 1; c.style.left = x + 'px'; c.style.top = y + 'px'; }",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
        )
        await asyncio.sleep(0.5)
        await locator.click()
        await asyncio.sleep(0.25)
        await self.page.evaluate("document.getElementById('demo-cursor').style.opacity = 0")
        await asyncio.sleep(hold)

    async def skip_wait(self, condition: str, refresh: str | None = None) -> float:
        """condition が真になるまで待ち、その間は動画から省く。省いた秒数を返す。
        refresh を渡すと、裏で作り終わるまでそのボタン（画面の「更新」）を押して読み直す。"""
        self.recorder.begin_cut()
        if refresh is None:
            await self.page.wait_for_function(condition, timeout=WAIT_LIMIT_MS)
        else:
            deadline = time.time() + WAIT_LIMIT_MS / 1000
            while not await self.page.evaluate(condition):
                if time.time() > deadline:
                    raise TimeoutError(f"待ちきれませんでした: {condition}")
                await asyncio.sleep(2)
                await self.page.click(refresh)
        return self.recorder.end_cut()

    async def enter_as(self, number: str) -> None:
        page = self.page
        # 生徒の画面にいるときは、上の帯の右の「教員の画面へ」で教員の画面に戻る
        if await page.locator("#to-teacher").is_visible():
            await page.locator("#to-teacher").click()
        row = page.locator("#codes tr").filter(has=page.get_by_role("cell", name=number, exact=True))
        await self.click(row.get_by_role("button"), 0.3)
        async with page.expect_response(lambda r: r.url.endswith("/v1/sessions") and r.request.method == "POST") as entered:
            await self.click(page.get_by_role("button", name="入室", exact=True), 0.4)
        session = await (await entered.value).json()
        async with page.expect_response(lambda r: r.url.endswith("/attempt:start")) as started:
            await self.click(page.locator("#start"), 0.8)
        self.keys[number] = answer_key(session, await (await started.value).json())

    async def answer(self, question_id: str, value: str, wrong: bool = False, hold: float = 0.5) -> None:
        options = self.page.locator(f'input[type=radio][name="{question_id}"]')
        if await options.count():
            values = [await options.nth(i).get_attribute("value") for i in range(await options.count())]
            chosen = next(v for v in values if v != value) if wrong else value
            await self.click(self.page.locator(f'label.option:has(input[name="{question_id}"][value="{chosen}"])'), hold)
        else:
            field = self.page.locator(f'input[name="{question_id}"]')
            await self.show(field)
            await field.press_sequentially("0" if wrong else value, delay=80)
            await asyncio.sleep(0.5)

    async def answer_all(self, number: str, wrong: bool = False, hold: float = 0.5) -> None:
        question_ids = await self.page.locator("#questions fieldset").evaluate_all(
            "(sets) => sets.map((s) => s.querySelector('input').name)"
        )
        for question_id in question_ids:
            await self.answer(question_id, self.keys[number][question_id], wrong, hold)

    async def background_attempt(self, class_code: str, personal_code: str, correct: int) -> None:
        """動画に映らない生徒の解答。順番を見せるために入れる。"""
        request = self.page.request
        session = await (await request.post(f"{BASE}/v1/sessions", data={"class_code": class_code, "personal_code": personal_code})).json()
        headers = {"Authorization": "Bearer " + session["token"]}
        url = f"{BASE}/v1/assignments/{session['assignment_id']}/attempt"
        quiz = await (await request.post(url + ":start", headers=headers)).json()
        key = answer_key(session, quiz)
        answers = {q["id"]: (key[q["id"]] if index < correct else "") for index, q in enumerate(quiz["questions"])}
        response = await request.post(url + ":submit", headers=headers, data={"answers": answers})
        if not response.ok:
            raise RuntimeError(f"裏の解答を送れませんでした: {response.status}")


async def scenario(demo: Demo) -> None:
    page = demo.page
    await demo.card(
        "ムシトリ（仮称）",
        ["自分の書いたコードを本人が分かっているかを、", "授業の5分で確かめる"],
        f"{WHERE}。データはすべて合成です",
        2.8,
    )
    await demo.hide_card()

    await demo.say("先生の画面です。合成データの提出コード6人分で、デモのクラスを作ります", 1.4)
    await demo.click(page.locator("#seed"), 0.4)
    await page.wait_for_function("!document.getElementById('generate').disabled", timeout=WAIT_LIMIT_MS)
    await demo.say("「問いを作る」で提出コードを隔離した環境で動かし、実行記録から問いと正解を作ります", 1.6)
    await demo.click(page.locator("#generate"), 0.3)
    seconds = await demo.skip_wait("!document.getElementById('open').disabled")
    await demo.show(page.locator("#status"), 0.2)
    await demo.say(f"問いができました{skipped(seconds)}", 2.2)
    await demo.say("動かないコードは対象外にして先生に知らせます。正解をAIには作らせません", 2.8)
    await demo.say("受付を始め、生徒に授業コードと個人コードを配ります", 1.0)
    await demo.click(page.locator("#open"), 0.4)
    class_code = await page.locator("#class-code").inner_text()
    codes = {}
    for row in await page.locator("#codes tr").all():
        cells = row.locator("td")
        codes[await cells.nth(0).inner_text()] = await cells.nth(1).inner_text()
    await demo.show(page.locator("#codes-card"), 0.8)

    await demo.say("生徒の画面です。ログインはなく、配られたコードで入室します", 0.8)
    await demo.enter_as("1")
    await demo.say("問いは本人のコードの実行記録から作るので、生徒ごとに違います", 2.4)
    await demo.say("出力の予測、変数の追跡、コードを変えたときの結果を問います", 0.3)
    await demo.answer_all("1")
    await demo.say("送るとすぐに正誤と解説が出ます。結果は成績には使いません", 0.4)
    await demo.click(page.locator("#quiz button.primary"), 0.6)
    await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    await asyncio.sleep(2.2)

    await demo.say("別の生徒です。同じような処理のコードでも、問いは本人専用です", 0.6)
    await demo.enter_as("3")
    await demo.show(page.locator("#code"), 1.8)
    await demo.say("動くコードを出していても、問いに答えられるとは限りません", 0.3)
    await demo.answer_all("3", wrong=True, hold=0.2)
    await demo.click(page.locator("#quiz button.primary"), 0.6)
    await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    await demo.say("まちがえた問いには解説が出ます。その行を自分の言葉で説明して、先生に送れます", 1.6)
    # 説明の文（合計に足す話）に合うよう、足し算の行の欄を選ぶ。なければ最初の欄
    forms = page.locator("#explain-items form")
    adding = forms.filter(has=page.locator(".spot-where code", has_text="+"))
    form = adding.first if await adding.count() else forms.first
    await demo.click(form.locator("textarea"), 0.2)
    await form.locator("textarea").press_sequentially(OWN_WORDS, delay=40)
    await demo.click(form.get_by_role("button", name="先生に送る"), 1.0)

    await demo.background_attempt(class_code, codes["4"], 1)
    await page.locator("#to-teacher").click()
    await demo.say("先生が締め切ると、誤答と本人の説明をもとに、声をかける順が出ます", 0.6)
    await demo.click(page.locator("#close"), 0.3)
    seconds = await demo.skip_wait(REVIEWS_READY, refresh="#refresh")
    await demo.show(page.locator("#followups-card h2"), 0.4)
    await demo.say(f"声をかける順です{skipped(seconds)}", 2.0)
    first = page.locator("#order .person").first
    await demo.say("説明を聞きたい行はコードが選び、聞き方の文面とまとめを Gemini が書きます", 0.4)
    await demo.show(first.locator(".memo"), 3.2)
    await demo.say("正解と採点、声をかける順も、AIではなくコードで決めます", 2.2)
    own_words = page.locator("#order .own-words").first
    if await own_words.count():
        await demo.say("生徒が送った説明も、その行の下に並びます", 0.4)
        await demo.show(own_words, 2.2)
    await demo.say("判断するのは先生です。聞いた結果を記録し、次の課題に生かします", 0.4)
    await page.evaluate("lastActionAt = Date.now() - 30000")  # 動画では実時間で待たない
    await demo.click(first.get_by_role("button", name="聞いて説明できた"), 1.0)
    await demo.show(first.locator(".done"), 1.4)
    await demo.say("", 0.2)
    await demo.card(
        "判断は先生、手間はAI",
        ["正解と採点はコードの実行結果で決まる", "問いの選び方と文面を Gemini が担う"],
        f"{WHERE}。合成データのデモで、待ち時間は一部省略。教育効果は未検証です",
        4.0,
    )


async def sign_in_as_guest(page) -> None:
    """公開URLでは「ログインせずに試す」で体験用の教員になる（収録の前なので動画には映らない）。"""
    await page.wait_for_function("() => !document.getElementById('guest-signin').disabled", timeout=WAIT_LIMIT_MS)
    await page.click("#guest-signin")
    await page.wait_for_function("() => !document.getElementById('teacher-work').hidden", timeout=WAIT_LIMIT_MS)


async def delete_demo_class(page) -> None:
    """公開URLで作ったデモクラスを、画面の「データを消す」で消す（確認のダイアログは受け入れる）。"""
    page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
    await page.evaluate("document.getElementById('demo-card')?.remove()")
    if await page.locator("#to-teacher").is_visible():
        await page.locator("#to-teacher").click()
    async with page.expect_response(lambda r: "/v1/classes/" in r.url and r.request.method == "DELETE") as deleted:
        await page.click("#delete")
    response = await deleted.value
    print("デモクラスを消しました" if response.ok else f"デモクラスを消せませんでした: {response.status}")


async def record(page, context) -> Recorder:
    await page.goto(BASE)
    if DEMO_URL:
        await sign_in_as_guest(page)
    await page.evaluate(OVERLAY)
    recorder = Recorder(await context.new_cdp_session(page), Path(tempfile.mkdtemp(prefix="demo-frames-")))
    await recorder.start()
    try:
        await scenario(Demo(page, recorder))
    except Exception:
        await page.screenshot(path=str(OUTPUT.with_suffix(".failed.png")), full_page=True)
        raise
    finally:
        await recorder.stop()
        if DEMO_URL:
            try:
                await delete_demo_class(page)
            except Exception as error:  # 片付けに失敗しても動画は書き出す。体験用のデータは1日で消える
                print(f"デモクラスを消せませんでした（1日で自動で消えます）: {type(error).__name__}", file=sys.stderr)
    return recorder


async def main() -> None:
    server = thread = None
    if not DEMO_URL:
        app = create_app()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.05)
    recorder = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel="chrome", headless=True)
            # 字幕を重ねる式と待つ条件の式をページで評価するので、CSP（unsafe-eval を許さない）はこのブラウザでだけ外す
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720}, device_scale_factor=1.5, locale="ja-JP", color_scheme="light", bypass_csp=True
            )
            recorder = await record(await context.new_page(), context)
            await browser.close()
        recorder.encode(OUTPUT)
    finally:
        if server:
            server.should_exit = True
            thread.join(timeout=5)
        if recorder:
            shutil.rmtree(recorder.folder, ignore_errors=True)
    print(OUTPUT, f"{OUTPUT.stat().st_size / 1_000_000:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
