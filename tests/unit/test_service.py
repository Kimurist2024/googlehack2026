"""問いの生成と提出の読み込みの試験。実行環境は偽物に置き換える。"""
import io
import struct
import zipfile

import pytest

from app.service import MAX_FILE_BYTES, generate_one, read_submissions
from app.store import AssignmentRecord
from qgen.ai import TemplateAI


class FixedSandbox:
    def __init__(self, result):
        self.result = result

    def analyze(self, code, stdin):
        return self.result


ASSIGNMENT = AssignmentRecord("a", "c", "合計", "", [], 300, 3, {"output": 1.0})


def result_with_values(size: int) -> dict:
    history = [{"scope": "", "name": "x", "value": repr("a" * size + str(i)), "line": 1} for i in range(3)]
    return {"status": "ok", "stdout": "1\n", "history": history, "mutants": []}


def test_ordinary_result_is_ready():
    outcome = generate_one(ASSIGNMENT, "s1", "x = 1\n", FixedSandbox(result_with_values(10)), TemplateAI())
    assert outcome["status"] == "ready"
    assert "answer" not in outcome["quiz"]["questions"][0]
    assert outcome["answer_key"]["questions"]


def test_result_too_large_for_one_document_is_excluded():
    outcome = generate_one(ASSIGNMENT, "s1", "x = 1\n", FixedSandbox(result_with_values(400_000)), TemplateAI())
    assert outcome == {"status": "excluded", "reason": "too_much_output"}


def zip_of(entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def lie_about_size(data: bytes, real: int, claimed: int) -> bytes:
    """ヘッダーの「展開後の大きさ」を小さく偽った zip にする（zip 爆弾の手口）。"""
    old, new = struct.pack("<I", real), struct.pack("<I", claimed)
    return data.replace(old, new)


def test_sandbox_status_is_not_trusted_as_a_reason():
    outcome = generate_one(ASSIGNMENT, "s1", "x = 1\n", FixedSandbox({"status": "=HYPERLINK(\"http://evil\")"}), TemplateAI())
    assert outcome == {"status": "excluded", "reason": "error"}


def test_zip_bomb_with_a_lying_header_is_not_loaded():
    big = b"#" * (MAX_FILE_BYTES * 20)
    data = lie_about_size(zip_of([("1.py", big)]), len(big), 10)
    found, problems = read_submissions(data, {"1"})
    assert found == {} and problems


def mark_encrypted(data: bytes, name: str) -> bytes:
    """ローカルヘッダーと中央ディレクトリの両方で、そのファイルに「暗号化」の印を付ける。"""
    out = bytearray(data)
    for signature, flag_at, name_length_at, name_at in ((b"PK\x03\x04", 6, 26, 30), (b"PK\x01\x02", 8, 28, 46)):
        start = 0
        while (index := out.find(signature, start)) != -1:
            length = struct.unpack_from("<H", out, index + name_length_at)[0]
            if bytes(out[index + name_at : index + name_at + length]) == name.encode():
                out[index + flag_at] |= 0x01
            start = index + 4
    return bytes(out)


def test_encrypted_duplicate_and_corrupted_entries_are_reported():
    data = zip_of([("1.py", b"print(1)\n"), ("dir/1.py", b"print(2)\n"), ("2.py", b"print(3)\n"), ("3.py", b"print(4)\n" * 50)])
    data = mark_encrypted(data, "2.py")
    # 3.py の圧縮データだけを壊す
    start = data.index(b"3.py") + len("3.py")
    corrupted = data[:start] + bytes(b ^ 0xFF for b in data[start : start + 2]) + data[start + 2 :]
    found, problems = read_submissions(corrupted, {"1", "2", "3"})
    assert found == {"1": "print(1)\n"}
    assert len(problems) == 3


def test_not_a_zip_is_a_value_error():
    with pytest.raises(ValueError):
        read_submissions(b"PK\x03\x04garbage", {"1"})
