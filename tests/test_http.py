import httpx
import pytest

from steam_researcher import http as http_mod
from steam_researcher.cache import Cache
from steam_researcher.http import HttpClient

URL = "https://example.test/api"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(HttpClient._fetch.retry, "sleep", lambda s: None)


def make_client(tmp_path, handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    client = HttpClient(cache=Cache(tmp_path / "c.sqlite"), transport=httpx.MockTransport(wrapped))
    return client, calls


def test_cache_ttl(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "c.sqlite")
    cache.set("k", {"a": 1}, ttl=10)
    assert cache.get("k") == {"a": 1}
    monkeypatch.setattr("steam_researcher.cache.time.time", lambda: 10**12)
    assert cache.get("k") is None


def test_404_not_retried(tmp_path):
    client, calls = make_client(tmp_path, lambda r: httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json(URL)
    assert len(calls) == 1


def test_503_retried_then_succeeds(tmp_path):
    responses = iter([httpx.Response(503), httpx.Response(200, json={"ok": 1})])
    client, calls = make_client(tmp_path, lambda r: next(responses))
    assert client.get_json(URL) == {"ok": 1}
    assert len(calls) == 2


def test_empty_result_not_cached(tmp_path):
    client, calls = make_client(tmp_path, lambda r: httpx.Response(200, json={}))
    client.get_json(URL)
    client.get_json(URL)
    assert len(calls) == 2


def test_result_cached(tmp_path):
    client, calls = make_client(tmp_path, lambda r: httpx.Response(200, json={"x": 1}))
    client.get_json(URL)
    assert client.get_json(URL) == {"x": 1}
    assert len(calls) == 1


def test_non_json_raises_clear_error(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(200, text="<html>oops"))
    with pytest.raises(RuntimeError, match="did not return JSON"):
        client.get_json(URL)
