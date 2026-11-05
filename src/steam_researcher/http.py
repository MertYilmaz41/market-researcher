"""HTTP client: polite per-host rate limiting, retries, and caching."""

import json
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, wait_exponential

from . import config
from .cache import Cache

# Minimum seconds between requests to the same host
HOST_INTERVAL = {"steamspy.com": 1.0, "store.steampowered.com": 1.5, "api.steampowered.com": 1.5}
# Slower pace for URL prefixes with a stricter limit. Steam's store search answered HTTP 429 after
# ~30 pages at 1.5 s each (Nov 2026).
URL_INTERVAL = {"https://store.steampowered.com/search/": 3.0}
# Read timeout per host (seconds). The review API is sometimes very slow (20-90+ s for one page,
# measured Nov 2026); give up sooner than the default and retry, since a retry is often fast.
HOST_TIMEOUT = {"api.steampowered.com": 20.0}
DEFAULT_TIMEOUT = 30.0
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryableStatus(Exception):
    """Transient HTTP status (429/5xx) worth retrying."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _rate_limited(state) -> bool:
    exc = state.outcome.exception() if state.outcome else None
    return isinstance(exc, RetryableStatus) and exc.status == 429


def _wait(state) -> float:
    """A 429 lockout lasts tens of seconds: wait 10, 20, 30... s. Everything else backs off briefly."""
    if _rate_limited(state):
        return min(60.0, 10.0 * state.attempt_number)
    return wait_exponential(multiplier=2, max=30)(state)


def _stop(state) -> bool:
    return state.attempt_number >= (6 if _rate_limited(state) else 4)


class HttpClient:
    """Safe to share between threads: requests to different hosts run in parallel, while each host
    gets one request at a time, at most one per HOST_INTERVAL."""

    def __init__(
        self,
        cache: Cache | None = None,
        use_cache: bool = True,
        transport: httpx.BaseTransport | None = None,
    ):
        self.cache = cache or Cache()
        self.use_cache = use_cache
        self.client = httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        )
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}

    def _throttle(self, host: str, url: str) -> None:
        # Reserve the next free slot for this host (or stricter URL prefix) under the lock, then
        # sleep outside it, so threads waiting for one host never block requests to another.
        key = next((prefix for prefix in URL_INTERVAL if url.startswith(prefix)), host)
        interval = URL_INTERVAL.get(key) or HOST_INTERVAL.get(host, 1.0)
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._last.get(key, float("-inf")) + interval)
            self._last[key] = slot
        if slot > now:
            time.sleep(slot - now)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, RetryableStatus)),
        wait=_wait,
        stop=_stop,
        reraise=True,
    )
    def _fetch(self, url: str, params: dict[str, Any]) -> Any:
        host = urlparse(url).hostname or ""
        with self._lock:
            host_lock = self._host_locks.setdefault(host, threading.Lock())
        with host_lock:  # one request in flight per host; retries back off outside the lock
            self._throttle(host, url)
            resp = self.client.get(url, params=params, timeout=HOST_TIMEOUT.get(host, DEFAULT_TIMEOUT))
        if resp.status_code in RETRYABLE_STATUS:
            raise RetryableStatus(f"{url} returned HTTP {resp.status_code}", resp.status_code)
        if resp.is_redirect:
            raise RuntimeError(
                f"{url} redirected to {resp.headers.get('location')!r}; endpoint unavailable"
            )
        resp.raise_for_status()
        try:
            return resp.json()
        except json.JSONDecodeError:
            raise RuntimeError(f"{url} did not return JSON: {resp.text[:120]!r}") from None

    def get_json(self, url: str, params: dict[str, Any] | None = None, ttl: float = 3600) -> Any:
        params = params or {}
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if self.use_cache and (hit := self.cache.get(key)) is not None:
            return hit
        data = self._fetch(url, params)
        if data:  # don't pin a transient empty response for the whole TTL
            self.cache.set(key, data, ttl)
        return data
