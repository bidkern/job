import time

from app.services.query_cache import TTLQueryCache


def test_query_cache_round_trip_returns_copy():
    cache = TTLQueryCache(ttl_seconds=60, max_entries=2)
    payload = [{"id": 1, "title": "Analyst"}]

    cache.set("recommendations", {"limit": 25}, payload)
    cached = cache.get("recommendations", {"limit": 25})

    assert cached == payload
    cached[0]["title"] = "Changed"
    fresh = cache.get("recommendations", {"limit": 25})
    assert fresh[0]["title"] == "Analyst"


def test_query_cache_expires_entries():
    cache = TTLQueryCache(ttl_seconds=0.01, max_entries=2)
    cache.set("recommendations", {"limit": 25}, [{"id": 1}])

    time.sleep(0.03)

    assert cache.get("recommendations", {"limit": 25}) is None


def test_query_cache_evicts_oldest_entry():
    cache = TTLQueryCache(ttl_seconds=60, max_entries=2)
    cache.set("one", {"a": 1}, [{"id": 1}])
    cache.set("two", {"a": 2}, [{"id": 2}])
    cache.set("three", {"a": 3}, [{"id": 3}])

    assert cache.get("one", {"a": 1}) is None
    assert cache.get("two", {"a": 2}) == [{"id": 2}]
    assert cache.get("three", {"a": 3}) == [{"id": 3}]
