"""Steam store search: the games of a search's tags (pipeline.tag_games).

The endpoint returns JSON with the result rows as HTML. Each row has the appid, title, review summary
("78% of the 3,325 user reviews") and price in cents, which is all steps 1-3 need. Several tag ids in one
query return only games with all of them. Sorted by review score, the results leave out games without one
(under 10 reviews), which saves most pages; it can't sort by review count, so they're read page by page.
Review counts are English reviews only (Steam computes the row's score in the visitor's language);
analyze_game loads Steam's all-language numbers later.
SteamSpy's tag lists were far smaller than Steam's (Colony Sim: 34 of 472 games with 100+ reviews, Nov 2026;
docs/measurements.md).
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


def games_by_tags(http: HttpClient, tag_ids: list[int],
                  on_page: Callable[[int, int], None] | None = None) -> list[Game]:
    """Every game with a review score and all of these Steam tag ids. on_page(pages done, total pages)."""
    games, start, total = [], 0, None
    while total is None or start < total:
        params = {"query": "", "start": start, "count": PAGE_SIZE, "tags": ",".join(map(str, tag_ids)),
                  "category1": 998, "sort_by": "Reviews_DESC", "infinite": 1, "cc": "us", "l": "english"}
        page, total = parse_search_page(http.get_json(SEARCH_URL, params, ttl=config.TTL_TAG_SEARCH))
        if not page:  # past the end, or the markup changed
            break
        games.extend(page)
        start += PAGE_SIZE
        if on_page:
            on_page(start // PAGE_SIZE, -(-total // PAGE_SIZE))
    seen = set()  # a game can move between pages while we read them
    return [g for g in games if not (g.appid in seen or seen.add(g.appid))]
