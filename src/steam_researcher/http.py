"""HTTP client: polite per-host rate limiting, retries, and caching."""

import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from . import config
from .cache import Cache

# Minimum seconds between requests to the same host
HOST_INTERVAL = {"steamspy.com": 1.0, "store.steampowered.com": 1.5, "api.steampowered.com": 1.5}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryableStatus(Exception):
    """Transient HTTP status (429/5xx) worth retrying."""


class HttpClient:
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
            timeout=30.0,
            follow_redirects=False,
            transport=transport,
        )
        self._last: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        wait = HOST_INTERVAL.get(host, 1.0) - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, RetryableStatus)),
        wait=wait_exponential(multiplier=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _fetch(self, url: str, params: dict[str, Any]) -> Any:
        self._throttle(urlparse(url).hostname or "")
        resp = self.client.get(url, params=params)
        if resp.status_code in RETRYABLE_STATUS:
            raise RetryableStatus(f"{url} returned HTTP {resp.status_code}")
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
