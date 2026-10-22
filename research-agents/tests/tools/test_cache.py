"""Tests for the SQLite cache."""

from __future__ import annotations

from pathlib import Path

from src.cache import SQLiteCache


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_cache_hit_and_miss(tmp_path: Path) -> None:
    cache = SQLiteCache(tmp_path / "cache.db", default_ttl_s=60, clock=FakeClock(1000.0))
    key = cache.make_key("search", {"q": "hello"})
    assert cache.get_json(key) is None
    cache.set_json(key, {"value": 1})
    assert cache.get_json(key) == {"value": 1}


def test_cache_expires_entries(tmp_path: Path) -> None:
    clock = FakeClock(1000.0)
    cache = SQLiteCache(tmp_path / "cache.db", default_ttl_s=10, clock=clock)
    key = cache.make_key("page", {"url": "https://example.com"})
    cache.set_json(key, "value")
    clock.now = 1005.0
    assert cache.get_json(key) == "value"
    clock.now = 1011.0
    assert cache.get_json(key) is None


def test_clear_expired_returns_count(tmp_path: Path) -> None:
    clock = FakeClock(1000.0)
    cache = SQLiteCache(tmp_path / "cache.db", default_ttl_s=10, clock=clock)
    cache.set_json("a", 1)
    cache.set_json("b", 2)
    clock.now = 1020.0
    assert cache.clear_expired() == 2


def test_make_key_is_order_independent(tmp_path: Path) -> None:
    first = SQLiteCache.make_key("ns", {"a": 1, "b": 2})
    second = SQLiteCache.make_key("ns", {"b": 2, "a": 1})
    assert first == second
