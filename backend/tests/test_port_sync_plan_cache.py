"""Кэш планов согласования (services/port_sync_plan_cache.py): срок жизни, вытеснение, ключ, сброс."""
from __future__ import annotations

import pytest

from app.services.port_sync_plan_cache import CachedPlan, PlanCache, scope_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def plan(*connection_ids: str) -> CachedPlan:
    return CachedPlan(items=tuple({"connection_id": i} for i in connection_ids), summary={"total_items": len(connection_ids)})


def test_hit_returns_the_stored_plan_and_miss_returns_none():
    cache = PlanCache()
    stored = plan("c1", "c2")
    cache.put("scope", "hash", stored)

    assert cache.get("scope", "hash") is stored
    assert cache.get("scope", "other-hash") is None
    assert cache.get("other-scope", "hash") is None


def test_same_hash_in_different_scopes_does_not_mix():
    cache = PlanCache()
    cache.put(scope_key(None, None), "same", plan("all"))
    cache.put(scope_key(["c1"], None), "same", plan("one"))

    assert [i["connection_id"] for i in cache.get(scope_key(None, None), "same").items] == ["all"]
    assert [i["connection_id"] for i in cache.get(scope_key(["c1"], None), "same").items] == ["one"]


def test_scope_key_depends_on_connections_order_and_rule():
    assert scope_key(["a", "b"], None) == scope_key(["a", "b"], None)
    assert scope_key(["a", "b"], None) != scope_key(["b", "a"], None)  # порядок подключений задаёт порядок элементов
    assert scope_key(None, None) != scope_key(None, "rule-1")
    assert scope_key(None, None) != scope_key([], None)


def test_entry_expires_after_ttl_and_is_dropped():
    clock = FakeClock()
    cache = PlanCache(ttl_seconds=60, clock=clock)
    cache.put("s", "h", plan("c1"))

    clock.now += 59
    assert cache.get("s", "h") is not None
    clock.now += 1
    assert cache.get("s", "h") is None
    assert len(cache) == 0


def test_reads_do_not_extend_the_lifetime_of_a_snapshot():
    """Снимок не должен жить дольше TTL от расчёта, сколько бы страниц ни листали, — иначе он устаревал бы бесконечно."""
    clock = FakeClock()
    cache = PlanCache(ttl_seconds=60, clock=clock)
    cache.put("s", "h", plan("c1"))

    for _ in range(5):
        clock.now += 12
        cache.get("s", "h")
    clock.now += 1

    assert cache.get("s", "h") is None


def test_least_recently_used_plan_is_evicted_beyond_max_entries():
    cache = PlanCache(max_entries=2)
    cache.put("s", "a", plan("a"))
    cache.put("s", "b", plan("b"))
    cache.get("s", "a")  # «a» использовался позже «b»
    cache.put("s", "c", plan("c"))

    assert cache.get("s", "b") is None
    assert cache.get("s", "a") is not None and cache.get("s", "c") is not None
    assert len(cache) == 2


def test_clear_drops_everything():
    cache = PlanCache()
    cache.put("s", "a", plan("a"))
    cache.put("s", "b", plan("b"))

    cache.clear()

    assert len(cache) == 0 and cache.get("s", "a") is None


@pytest.mark.parametrize("kwargs", [{"ttl_seconds": 0}, {"ttl_seconds": -1}, {"max_entries": 0}])
def test_invalid_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        PlanCache(**kwargs)
