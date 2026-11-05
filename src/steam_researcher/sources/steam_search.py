"""Steam store search: games by tag, for the tags SteamSpy can't search (config.STEAMSPY_UNSEARCHABLE_TAGS).

The endpoint returns JSON with the result rows as HTML. Each row has the appid, title, review summary
("78% of the 3,325 user reviews") and price in cents, which is all steps 1-3 need. It can't sort by
review count, so a tag is read page by page. Review counts can be slightly language-filtered;
analyze_game loads the full numbers from SteamSpy later.
"""

import html
import re
from collections.abc import Callable

from .. import config
from ..http import HttpClient
from ..models import Game

SEARCH_URL = "https://store.steampowered.com/search/results/"
PAGE_SIZE = 100

_ROW = re.compile(r'<a href="https://store\.steampowered\.com/(?:app|sub|bundle)/')
_APPID = re.compile(r'data-ds-appid="(\d+)"')  # bundles/packages have none or "1,2,3": skipped
_TITLE = re.compile(r'<span class="title">(.*?)</span>', re.S)
_REVIEWS = re.compile(r"(\d+)% of the ([\d,]+) user reviews")
_FINAL = re.compile(r'data-price-final="(\d+)"')
_ORIGINAL = re.compile(r'class="discount_original_price">[^\d<]*([\d,]+)\.(\d\d)')


def parse_search_page(data: dict) -> tuple[list[Game], int]:
    """(games on this page, total results for the query). Pure, for tests."""
    data = data or {}
    games = []
    for row in _ROW.split(data.get("results_html") or "")[1:]:
        appid, title = _APPID.search(row), _TITLE.search(row)
        if not appid or not title:
            continue
        reviews = _REVIEWS.search(html.unescape(row))
        pct, n = (int(reviews[1]), int(reviews[2].replace(",", ""))) if reviews else (0, 0)
        positive = round(pct * n / 100)
        final, original = _FINAL.search(row), _ORIGINAL.search(row)
        price = int(final[1]) if final else 0
        games.append(Game(
            appid=int(appid[1]),
            name=html.unescape(title[1]).strip(),
            positive=positive,
            negative=n - positive,
            price_cents=price,
            initial_price_cents=int(original[1].replace(",", "") + original[2]) if original else price,
        ))
    return games, int(data.get("total_count") or 0)


def games_by_tag(http: HttpClient, tag_id: int, on_page: Callable[[int, int], None] | None = None) -> list[Game]:
    """Every game with this Steam tag id. on_page(pages done, total pages) reports progress."""
    games, start, total = [], 0, None
    while total is None or start < total:
        params = {"query": "", "start": start, "count": PAGE_SIZE, "tags": tag_id, "category1": 998,
                  "infinite": 1, "cc": "us", "l": "english"}
        page, total = parse_search_page(http.get_json(SEARCH_URL, params, ttl=config.TTL_TAG_LIST))
        if not page:  # past the end, or the markup changed
            break
        games.extend(page)
        start += PAGE_SIZE
        if on_page:
            on_page(start // PAGE_SIZE, -(-total // PAGE_SIZE))
    seen = set()  # a game can move between pages while we read them
    return [g for g in games if not (g.appid in seen or seen.add(g.appid))]
