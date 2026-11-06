"""Gemini に渡す指示文の版の管理。

指示文は qgen/prompts/<対象>/vNNN.md に置き、使う版の名前を ACTIVE に書く。
自動改善（rsi）は新しい版の候補を作るだけで、ACTIVE を書き換えるのは人の判断（python -m rsi promote）。
"""
import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
VERSION = re.compile(r"v(\d{3})\.md")


def _folder(target: str, root: Path) -> Path:
    if not re.fullmatch(r"[a-z_]+", target):
        raise ValueError(f"対象の名前が不正です: {target}")
    return root / target


def versions(target: str, root: Path = PROMPTS_DIR) -> list[str]:
    folder = _folder(target, root)
    return sorted(path.name for path in folder.glob("v*.md") if VERSION.fullmatch(path.name)) if folder.exists() else []


def active_version(target: str, root: Path = PROMPTS_DIR) -> str:
    name = (_folder(target, root) / "ACTIVE").read_text(encoding="utf-8").strip()
    if not VERSION.fullmatch(name):
        raise ValueError(f"ACTIVE の版の名前が不正です: {name}")
    return name


def load_active(target: str, root: Path = PROMPTS_DIR) -> str:
    return (_folder(target, root) / active_version(target, root)).read_text(encoding="utf-8")


def add_version(target: str, text: str, root: Path = PROMPTS_DIR) -> str:
    """次の番号で新しい版を書く。ACTIVE は変えない。"""
    existing = versions(target, root)
    number = int(VERSION.fullmatch(existing[-1]).group(1)) + 1 if existing else 1
    name = f"v{number:03d}.md"
    folder = _folder(target, root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return name


def set_active(target: str, name: str, root: Path = PROMPTS_DIR) -> None:
    if name not in versions(target, root):
        raise ValueError(f"{target} に {name} はありません")
    (_folder(target, root) / "ACTIVE").write_text(name + "\n", encoding="utf-8")
