"""模擬提出物と正解の読み込み。

1件ごとにフォルダを分け、program.py（コード）、explanation.txt（生徒の説明）、gold.json（正解）を置く。
すべて自作の合成データで、実在の生徒の提出物は入れない。

生徒役の水準（student）：
- standard：教科書どおりの言葉で、1文に1つの主張を書く生徒
- weak：説明が苦手な生徒。くだけた言い方、あいまいな言葉、「たぶん」「〜はず」のような書き方をする。
  weak/ に explanation.txt と gold.json（主張の文だけを差しかえたもの）を置く。コード・ラベル・根拠は standard と同じ
"""
import json
from dataclasses import dataclass
from pathlib import Path

from .pipeline import CaseInput

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "evals" / "cases"
SPLITS = ("dev", "heldout")
# gap: コードと食い違う（理解不足）、clumsy: 説明は拙いが正しい、alternative: 別解、correct: 正しい
LABELS = ("gap", "clumsy", "alternative", "correct")
KINDS = ("structure", "behavior")
STUDENTS = ("standard", "weak")


@dataclass(frozen=True)
class GoldClaim:
    id: str
    text: str
    label: str
    kind: str
    evidence: tuple[tuple[int, int], ...]  # 根拠の行の範囲。gap は空

    @property
    def is_gap(self) -> bool:
        return self.label == "gap"


@dataclass(frozen=True)
class Case:
    id: str
    split: str
    input: CaseInput
    claims: tuple[GoldClaim, ...]


def _claim(raw: dict, case_id: str) -> GoldClaim:
    label, kind = raw["label"], raw.get("kind", "structure")
    if label not in LABELS or kind not in KINDS:
        raise ValueError(f"{case_id}/{raw.get('id')}: label か kind が不正です")
    evidence = tuple((int(a), int(b)) for a, b in raw.get("evidence", []))
    if (label == "gap") != (not evidence):
        raise ValueError(f"{case_id}/{raw['id']}: gap だけが根拠なしになります")
    return GoldClaim(raw["id"], raw["text"], label, kind, evidence)


def load_case(folder: Path, student: str = "standard") -> Case:
    if student not in STUDENTS:
        raise ValueError(f"student は {STUDENTS} のどれかです")
    gold = json.loads((folder / "gold.json").read_text(encoding="utf-8"))
    if gold["split"] not in SPLITS:
        raise ValueError(f"{folder.name}: split が不正です")
    voice = folder if student == "standard" else folder / student
    raw_claims = json.loads((voice / "gold.json").read_text(encoding="utf-8"))["claims"] if voice != folder else gold["claims"]
    explanation = (voice / "explanation.txt").read_text(encoding="utf-8").strip()
    if voice != folder and [(c["id"], c["label"], c["evidence"]) for c in raw_claims] != [(c["id"], c["label"], c["evidence"]) for c in gold["claims"]]:
        raise ValueError(f"{folder.name}/{student}: 主張のラベルと根拠は standard と同じにしてください")
    missing = [c["id"] for c in raw_claims if c["text"] not in explanation]
    if missing:
        raise ValueError(f"{folder.name}/{student}: 説明にない主張があります {missing}")
    case_input = CaseInput(case_id=folder.name, code=(folder / "program.py").read_text(encoding="utf-8"), explanation=explanation, goal=gold.get("goal", ""))
    claims = tuple(_claim(raw, folder.name) for raw in raw_claims)
    return Case(folder.name, gold["split"], case_input, claims)


def load_cases(folder: Path = DEFAULT_DIR, split: str | None = "dev", student: str = "standard") -> list[Case]:
    """split を指定すると、その分だけを返す。heldout は自動改善に見せない確認用。"""
    if split is not None and split not in SPLITS:
        raise ValueError(f"split は {SPLITS} のどれかです")
    cases = [load_case(path, student) for path in sorted(Path(folder).iterdir()) if (path / "gold.json").exists()]
    return [case for case in cases if split is None or case.split == split]
