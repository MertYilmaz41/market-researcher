"""SteamSpy API: per-game details with tags. (Its tag lists missed most games: docs/measurements.md.)"""

from .. import config
from ..http import HttpClient
from ..models import Game

API = "https://steamspy.com/api.php"


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def parse_game(row: dict) -> Game:
    tags = row.get("tags")
    return Game(
        appid=_int(row.get("appid")),
        name=row.get("name") or "?",
        developer=row.get("developer") or "",
        publisher=row.get("publisher") or "",
        positive=_int(row.get("positive")),
        negative=_int(row.get("negative")),
        price_cents=_int(row.get("price")),
        initial_price_cents=_int(row.get("initialprice")),
        discount=_int(row.get("discount")),
        owners=row.get("owners") or "",
        ccu=_int(row.get("ccu")),
        tags=tags if isinstance(tags, dict) else {},  # SteamSpy sends [] when there are none
    )


def game_details(http: HttpClient, appid: int) -> Game | None:
    data = http.get_json(API, {"request": "appdetails", "appid": appid}, ttl=config.TTL_APPDETAILS)
    if not data or not data.get("name"):
        return None
    return parse_game(data)
