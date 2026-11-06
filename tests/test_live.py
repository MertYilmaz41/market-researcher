"""Live checks of every outside endpoint the app reads: do they still answer, in the shape we parse?

    SR_LIVE=1 uv run pytest tests/test_live.py -v

Skipped unless SR_LIVE=1, so the normal test run never touches the network. CI runs them weekly
(.github/workflows/live.yml), so a Steam or SteamSpy change shows up as a failed run (and an email)
before users see empty or wrong results. Each test checks one endpoint, so a failure names it.
Uses a throwaway cache: nothing comes from, or goes into, the user's cache.
"""

import os
import time

import pytest

from steam_researcher.cache import Cache
from steam_researcher.http import HttpClient
from steam_researcher.models import Game
from steam_researcher.sources import steam_search, steam_store, steamspy

pytestmark = pytest.mark.skipif(os.environ.get("SR_LIVE") != "1", reason="live network checks: set SR_LIVE=1")

STARDEW = 413150  # big, priced, steadily reviewed: its numbers barely move
DAY = 24 * 3600


@pytest.fixture(scope="module")
def http(tmp_path_factory):
    return HttpClient(cache=Cache(tmp_path_factory.mktemp("live") / "cache.sqlite"), use_cache=False)


def test_steamspy_tag_list(http):
    games = steamspy.games_by_tag(http, "Colony Sim")
    assert len(games) >= 100
    assert sum(g.positive + g.negative >= 1000 for g in games) >= 20
    assert any(g.initial_price_cents > 0 for g in games)


def test_steamspy_unknown_tag_is_detected(http):
    assert steamspy.games_by_tag(http, "Surely Not A Real Tag 7") == []


def test_steamspy_game_details(http):
    game = steamspy.game_details(http, STARDEW)
    assert game is not None and game.positive > 100_000
    assert len(game.tags) >= 10


def test_steam_appdetails(http):
    details = steam_store.app_details(http, STARDEW)
    assert details is not None and details.type == "game"
    assert details.price_initial_cents > 0 and details.release_date


def test_review_histogram(http):
    hist = steam_store.review_histogram(http, STARDEW)
    assert len(hist) >= 100  # monthly since 2016
    assert time.time() - hist[-1].date < 62 * DAY  # reaches the current month
    assert sum(p.total for p in hist) > 100_000


def test_review_texts_negative_and_newest(http):
    negative = steam_store.reviews(http, STARDEW, "negative", limit=5)
    assert len(negative) == 5 and not any(r.voted_up for r in negative)
    assert all(r.text and r.timestamp and r.recommendation_id for r in negative)
    newest = steam_store.reviews(http, STARDEW, "all", limit=5, order="recent")
    assert time.time() - newest[0].timestamp < 30 * DAY  # numeric filter=1 still means newest first


def test_review_summary(http):
    summary = steam_store.review_summary(http, STARDEW)
    assert summary is not None
    positive, total, with_offtopic = summary
    assert total > 100_000 and 0.9 < positive / total <= 1 and with_offtopic >= total


def test_tag_catalog(http):
    names = steam_store.tag_names(http)
    assert len(names) >= 400 and "Colony Sim" in names
    assert steam_store.tag_ids(http)["Incremental"] > 0


def test_store_search_page(http):
    tag_id = steam_store.tag_ids(http)["Incremental"]  # a tag SteamSpy can't search
    params = {"query": "", "start": 0, "count": steam_search.PAGE_SIZE, "tags": tag_id, "category1": 998,
              "infinite": 1, "cc": "us", "l": "english"}
    games, total = steam_search.parse_search_page(http.get_json(steam_search.SEARCH_URL, params))
    assert total > 1000
    assert len(games) >= 50  # most rows parse: the markup still matches
    assert sum(g.positive + g.negative > 0 for g in games) >= 25
    assert any(g.price_cents > 0 for g in games)
    assert all(isinstance(g, Game) and g.name for g in games)
