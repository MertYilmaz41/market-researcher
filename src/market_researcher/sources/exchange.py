"""Currency exchange rates for the regional prices: open.er-api.com (free, no key, daily rates).
Its terms ask apps to credit it; the game panel links it under the price table."""

from .. import config
from ..http import HttpClient

API = "https://open.er-api.com/v6/latest/USD"


def parse_rates(data: dict) -> tuple[dict[str, float], str]:
    """Units of each currency per US dollar, and the date they were updated ("Fri, 20 Nov 2026 ...")."""
    if data.get("result") != "success":
        raise RuntimeError(f"open.er-api.com did not return JSON rates: {data.get('error-type', data.get('result'))}")
    return {k: float(v) for k, v in (data.get("rates") or {}).items()}, data.get("time_last_update_utc", "")


def usd_rates(http: HttpClient) -> tuple[dict[str, float], str]:
    return parse_rates(http.get_json(API, ttl=config.TTL_EXCHANGE_RATES) or {})
