"""接続元の判定と CSV の無害化の単体テスト。"""
import pytest
from starlette.requests import Request

from app import security
from app.main import csv_cell


def request_from(peer: str, forwarded: list[str] | None = None) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded or []]
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)


def test_without_a_proxy_the_peer_is_used_and_the_header_ignored():
    assert security.client_address(request_from("203.0.113.5", ["198.51.100.1"])) == "203.0.113.5"


def test_on_cloud_run_the_rightmost_entry_is_used(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "mushitori")
    # 左側は送り手が自由に書けるので、偽の値を入れても右端（Cloud Run が足した値）が使われる
    request = request_from("169.254.1.1", ["1.1.1.1, 203.0.113.5"])
    assert security.client_address(request) == "203.0.113.5"


def test_several_forwarded_headers_are_read_in_order(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert security.client_address(request_from("10.0.0.1", ["1.1.1.1", "203.0.113.5"])) == "203.0.113.5"


def test_ipv6_is_grouped_by_64(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    first = security.client_address(request_from("10.0.0.1", ["2001:db8:1:2::1"]))
    second = security.client_address(request_from("10.0.0.1", ["2001:db8:1:2:ffff::9"]))
    assert first == second == "2001:db8:1:2::/64"


def test_ipv4_mapped_ipv6_counts_as_ipv4():
    assert security.client_address(request_from("::ffff:203.0.113.5")) == "203.0.113.5"


def test_garbage_address_becomes_unknown(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert security.client_address(request_from("10.0.0.1", ["<script>"])) == "unknown"


def test_client_key_hides_the_address():
    key = security.client_key(request_from("203.0.113.5"))
    assert "203" not in key and len(key) == 32


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_csv_formula_cells_are_neutralized(value):
    assert csv_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["12", "ready", 3, ""])
def test_ordinary_csv_cells_are_kept(value):
    assert csv_cell(value) == value
