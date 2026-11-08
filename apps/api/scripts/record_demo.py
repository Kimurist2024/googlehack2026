"""デモ動画を自動で収録する。合成データだけを使い、demo/ に MP4 を書き出す。

使い方: apps/api で ../../.venv/bin/python scripts/record_demo.py
必要なもの: requirements-demo.txt と Google Chrome
字幕は収録時に画面へ重ねるだけで、アプリ本体には含まれない。
"""
import asyncio
import base64
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
os.environ.update(
    APP_ENV="local",
    SERVE_WEB="1",
    SANDBOX_BACKEND="local",
    ALLOW_LOCAL_SANDBOX="1",
    AI_BACKEND="template",
    STORE_BACKEND="memory",
    SESSION_SECRET=secrets.token_hex(32),
)

import imageio_ffmpeg  # noqa: E402
import uvicorn  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

from app.main import create_app  # noqa: E402

PORT = 8010
BASE = f"http://127.0.0.1:{PORT}"
# 動画はリポジトリ直下の demo/ に書き出す（Git では管理しない）
OUTPUT = ROOT.parents[1] / "demo" / "mushitori_demo.mp4"

OVERLAY = """
() => {
  const style = document.createElement('style');
  style.textContent = `
    body { padding-bottom: 150px; scroll-behavior: smooth; }
    #demo-caption { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); width: max-content; max-width: 88%;
      padding: 12px 24px; background: rgba(18,24,20,.93); color: #fff; font: 600 24px/1.5 'Hiragino Sans', sans-serif;
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


class Recorder:
    """CDP の画面配信で JPEG を受け取り、時刻どおりにつないで MP4 にする。"""

    def __init__(self, client, folder: Path) -> None:
        self.client = client
        self.folder = folder
        self.frames: list[tuple[Path, float]] = []
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

    def encode(self, output: Path, tail_sec: float = 1.0) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        listing = self.folder / "frames.txt"
        lines = []
        for index, (path, stamp) in enumerate(self.frames):
            following = self.frames[index + 1][1] if index + 1 < len(self.frames) else stamp + tail_sec
            lines += [f"file '{path}'", f"duration {max(following - stamp, 0.001):.3f}"]
        lines.append(f"file '{self.frames[-1][0]}'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease:in_range=pc:out_range=tv,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white,fps=30",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
            ],
            check=True,
        )


class Demo:
    def __init__(self, page, store) -> None:
        self.page = page
        self.store = store

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

    def answers_for(self, number: str) -> dict[str, str]:
        # 収録はメモリ上の保存先で動かし、作った課題は1つだけなので中を直接見る
        assignment = next(iter(self.store._assignments.values()))
        classroom = self.store.get_class(assignment.class_id)
        student_id = next(sid for sid, value in classroom.student_numbers.items() if value == number)
        return {qid: item["answer"] for qid, item in self.store.get_answer_key(assignment.id, student_id)["questions"].items()}

    async def enter_as(self, number: str) -> None:
        page = self.page
        # 生徒の画面にいるときは、上の帯の右の「教員の画面へ」で教員の画面に戻る
        if await page.locator("#to-teacher").is_visible():
            await page.locator("#to-teacher").click()
        row = page.locator("#codes tr").filter(has=page.get_by_role("cell", name=number, exact=True))
        await self.click(row.get_by_role("button"))
        await self.click(page.get_by_role("button", name="入室", exact=True))
        await self.click(page.locator("#start"), 1.0)

    async def answer(self, question_id: str, value: str, wrong: bool = False) -> None:
        options = self.page.locator(f'input[type=radio][name="{question_id}"]')
        if await options.count():
            values = [await options.nth(i).get_attribute("value") for i in range(await options.count())]
            chosen = next(v for v in values if v != value) if wrong else value
            await self.click(self.page.locator(f'label.option:has(input[name="{question_id}"][value="{chosen}"])'), 0.5)
        else:
            field = self.page.locator(f'input[name="{question_id}"]')
            await self.show(field)
            await field.press_sequentially("0" if wrong else value, delay=80)
            await asyncio.sleep(0.5)

    async def background_attempt(self, class_code: str, personal_code: str, correct: int, number: str) -> None:
        """動画に映らない生徒の解答。順番を見せるために入れる。"""
        request = self.page.request
        session = await (await request.post(f"{BASE}/v1/sessions", data={"class_code": class_code, "personal_code": personal_code})).json()
        headers = {"Authorization": "Bearer " + session["token"]}
        url = f"{BASE}/v1/assignments/{session['assignment_id']}/attempt"
        quiz = await (await request.post(url + ":start", headers=headers)).json()
        key = self.answers_for(number)
        answers = {q["id"]: (key[q["id"]] if index < correct else "") for index, q in enumerate(quiz["questions"])}
        await request.post(url + ":submit", headers=headers, data={"answers": answers})


async def scenario(demo: Demo) -> None:
    page = demo.page
    await demo.card(
        "ムシトリ（仮称）",
        ["自分の書いたコードを本人が分かっているかを、", "授業の5分で確かめる"],
        "デモは合成データです",
        3.5,
    )
    await demo.hide_card()

    await demo.say("教員が、生徒の提出コードを取り込みます（デモは合成データ6人分）", 1.8)
    await demo.click(page.locator("#seed"))
    await demo.say("「問いを作る」を押すと、コードを実行した結果から問いと正解を作ります", 1.6)
    await demo.click(page.locator("#generate"), 0.3)
    await page.wait_for_function("!document.getElementById('open').disabled", timeout=60000)
    await demo.show(page.locator("#status"), 0.3)
    await demo.say("動かないコードは対象外にして、教員に知らせます。正解をAIに作らせません", 3.4)
    await demo.say("受付を始め、生徒に授業コードと個人コードを配ります", 1.4)
    await demo.click(page.locator("#open"))
    class_code = await page.locator("#class-code").inner_text()
    codes = {}
    for row in await page.locator("#codes tr").all():
        cells = row.locator("td")
        codes[await cells.nth(0).inner_text()] = await cells.nth(1).inner_text()
    await demo.show(page.locator("#codes-card"), 1.2)

    await demo.say("生徒は、自分のコードを見ながら短い問いに答えます", 1.0)
    await demo.enter_as("1")
    await demo.say("問いは本人のコードから作られるので、生徒ごとに変わります", 3.2)
    key = demo.answers_for("1")
    question_ids = await page.locator("#questions fieldset").evaluate_all(
        "(sets) => sets.map((s) => s.querySelector('input').name)"
    )
    await demo.say("出力の予測、変数の追跡、コードを変えたときの結果を問います", 0.5)
    for question_id in question_ids:
        await demo.answer(question_id, key[question_id])
    await asyncio.sleep(0.8)
    await demo.say("送信すると、すぐに正誤と解説が返ります。結果は成績には使いません", 0.6)
    await demo.click(page.locator("#quiz button.primary"), 0.8)
    await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    await asyncio.sleep(2.8)

    await demo.say("別の生徒です。同じ 255 を表示するコードでも、問いは本人専用です", 0.8)
    await demo.enter_as("3")
    await demo.show(page.locator("#code"), 2.6)
    key = demo.answers_for("3")
    question_ids = await page.locator("#questions fieldset").evaluate_all(
        "(sets) => sets.map((s) => s.querySelector('input').name)"
    )
    await demo.say("動くコードを提出していても、問いに答えられるとは限りません", 0.5)
    for question_id in question_ids:
        await demo.answer(question_id, key[question_id], wrong=True)
    await demo.click(page.locator("#quiz button.primary"), 0.8)
    await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    await demo.say("間違えても、どこを追えばよいかの解説が出ます", 1.0)
    await demo.show(page.locator("#result-items .card").first, 2.4)

    await demo.background_attempt(class_code, codes["4"], 1, "4")
    await page.locator("#to-teacher").click()
    await demo.say("教員が締め切ると、誤答をもとに声をかける順が出ます", 0.6)
    await demo.click(page.locator("#close"), 0.8)
    await page.wait_for_selector(".person")
    await demo.show(page.locator("#followups-card h2"), 2.8)
    await demo.say("授業で聞く一問も出るので、限られた時間を確認に使えます", 0.6)
    await demo.show(page.locator(".person .ask").first, 2.8)
    await demo.say("持ち時間を60秒にすると、外れた生徒は次の空き時間に回ります", 0.6)
    budget = page.locator("#budget")
    await demo.click(budget, 0.2)
    await budget.fill("60")
    await budget.press("Tab")
    await asyncio.sleep(0.6)
    await demo.show(page.locator(".person").last, 2.8)
    await demo.say("判断するのは教員です。処置と理由を記録します", 0.6)
    await page.evaluate("lastActionAt = Date.now() - 30000")  # 動画では実時間で待たない
    await demo.click(page.locator(".person").first.get_by_role("button", name="授業で聞く"), 1.2)
    await demo.show(page.locator(".person").first, 1.6)
    await demo.say("動かない提出と未解答の生徒は、順番の外に分けて示します", 0.6)
    await demo.show(page.locator("#others"), 3.0)
    await demo.say("", 0.2)
    await demo.card(
        "判断は教員、手間はAI",
        ["正解と採点はコードの実行結果で決まる", "問いの選定と説明を Gemini が担う設計"],
        "合成データによるデモ。文面はテンプレート版で、教育効果は未検証です",
        4.5,
    )


async def main() -> None:
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    folder = Path(tempfile.mkdtemp(prefix="demo-frames-"))
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel="chrome", headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5, locale="ja-JP", color_scheme="light")
            page = await context.new_page()
            await page.goto(BASE)
            await page.evaluate(OVERLAY)
            recorder = Recorder(await context.new_cdp_session(page), folder)
            await recorder.start()
            await scenario(Demo(page, app.state.store))
            await recorder.stop()
            await browser.close()
        recorder.encode(OUTPUT)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        shutil.rmtree(folder, ignore_errors=True)
    print(OUTPUT, f"{OUTPUT.stat().st_size / 1_000_000:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
