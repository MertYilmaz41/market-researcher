import json
from pathlib import Path

import httpx
import pytest

from steam_researcher import risk
from steam_researcher.cache import Cache
from steam_researcher.http import HttpClient
from steam_researcher.models import AppDetails, Game, HistPoint
from steam_researcher.sources import steam_store
from steam_researcher.sources.steamspy import parse_game

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


def game(**kw):
    base = dict(appid=1, name="X", positive=100, negative=100, price_cents=999, initial_price_cents=999)
    return Game(**(base | kw))


def flat_hist(n=12, per=100, up_share=0.5):
    return [HistPoint(date=i * 2_600_000, up=int(per * up_share), down=per - int(per * up_share)) for i in range(n)]


# --- parsers on real responses ---

def test_parse_app_details_real():
    d = steam_store.parse_app_details(2336220, load("appdetails_2336220.json"))
    assert d.type == "game" and d.price_final_cents == 1599
    assert 38 in d.category_ids  # Online Co-op


def test_parse_app_details_unlisted():
    assert steam_store.parse_app_details(5, {"5": {"success": False}}) is None


def test_parse_histogram_real():
    hist = steam_store.parse_histogram(load("histogram_2336220.json"))
    assert len(hist) == 34 and hist[3].down == 5829


def test_steamspy_empty_tags_list():
    assert parse_game({"appid": 1, "name": "A", "tags": []}).tags == {}


# --- spikes ---

def test_feed_the_cups_review_bomb_detected():
    flags = risk.check_spikes(steam_store.parse_histogram(load("histogram_2336220.json")))
    codes = [f.code for f in flags]
    assert "review_bomb" in codes and "2024-05" in flags[0].message
    without = next(f for f in flags if f.code == "rating_without_spikes")
    assert "% positive" in without.message


def test_flat_history_no_spike():
    assert risk.check_spikes(flat_hist()) == []


def test_launch_window_ignored():
    hist = flat_hist()
    hist[0] = HistPoint(date=0, up=5000, down=100)
    assert risk.check_spikes(hist) == []


def test_positive_spike_is_streamer_warning():
    hist = flat_hist()
    hist[6] = HistPoint(date=hist[6].date, up=3000, down=200)
    assert [f.code for f in risk.check_spikes(hist)][0] == "streamer_spike"


# --- discount, complexity, niche, listing ---

def details(**kw):
    base = dict(appid=1, type="game", name="X", price_initial_cents=1999, price_final_cents=1999)
    return AppDetails(**(base | kw))


def test_deep_discount_and_cheap_price():
    flags = risk.check_discount(game(), details(price_final_cents=49, discount_percent=90))
    assert {f.code for f in flags} == {"deep_discount", "cheap_price"}
    assert risk.check_discount(game(), details()) == []


def test_free_game_not_flagged_cheap():
    assert risk.check_discount(game(price_cents=0), details(price_final_cents=0, is_free=True)) == []


def test_netcode_only_for_online_categories():
    assert risk.check_complexity(details(category_ids=[2, 9, 24]), {}) == []  # single-player, local co-op
    assert risk.check_complexity(details(category_ids=[38]), {})[0].code == "netcode"


def test_niche_and_hard_tags():
    assert risk.check_niche({"VR": 100, "Cooking": 90})[0].code == "niche"
    assert risk.check_complexity(None, {"Physics": 5})[0].code == "hard_tech"


def test_listing_checks():
    assert risk.check_listing(None)[0].code == "unlisted"
    assert risk.check_listing(details(type="dlc"))[0].code == "not_game"
    assert risk.check_listing(details()) == []


# --- review paging ---

def test_reviews_paging_stops_at_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("steam_researcher.http.time.sleep", lambda s: None)
    pages = {"*": "c1", "c1": "c2", "c2": "c2"}
    seen = []

    def handler(request):
        q = json.loads(request.url.params["input_json"])
        seen.append(q)
        cur, n = q["cursor"], q["num_per_page"]
        revs = [{"recommendationid": f"{cur}-{i}", "review": "bad", "voted_up": False} for i in range(n)]
        return httpx.Response(200, json={"response": {"cursor": pages[cur], "reviews": revs}})

    http = HttpClient(cache=Cache(tmp_path / "c.sqlite"), transport=httpx.MockTransport(handler))
    got = steam_store.reviews(http, 1, limit=250)
    assert len(got) == 250 and len({r.recommendation_id for r in got}) == 250
    # numeric review_type and all-time range are what the new endpoint needs
    assert all(q["review_type"] == 2 and q["day_range"] == 0 and q["filter"] == 0 for q in seen)
    seen.clear()
    steam_store.reviews(http, 1, limit=10, order="recent")
    assert seen[0]["filter"] == 1  # numeric: the string "recent" is ignored by the API


def test_reviews_redirect_is_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr("steam_researcher.http.time.sleep", lambda s: None)
    handler = lambda r: httpx.Response(302, headers={"location": "https://store.steampowered.com/"})
    http = HttpClient(cache=Cache(tmp_path / "c.sqlite"), transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="redirected"):
        steam_store.reviews(http, 1)


# --- recent demand ---------------------------------------------------------------------------

NOW = 1_800_000_000  # fixed "now" so the 12-month window is deterministic
MONTH = 31 * 24 * 3600  # 12 of these fit in a year, 13 do not


def _months(counts: list[int]) -> list[HistPoint]:
    """One point per month, oldest first, ending this month."""
    n = len(counts)
    return [HistPoint(date=NOW - (n - 1 - i) * MONTH, up=c, down=0) for i, c in enumerate(counts)]


def test_recent_activity_counts_last_12_months():
    hist = _months([100] * 24 + [5] * 12)
    recent, total, age = risk.recent_activity(hist, NOW)
    assert (recent, total) == (60, 2460)
    assert 2.9 < age < 3.0


def test_old_quiet_game_is_fading():
    flags = risk.check_fading(_months([500] * 36 + [1] * 12), NOW)
    assert [f.code for f in flags] == ["fading_demand"]
    assert "0.1%" in flags[0].message  # 12 of 18,012 reviews


def test_young_or_active_game_is_not_fading():
    assert risk.check_fading(_months([500] * 6 + [1] * 12), NOW) == []  # under 2 years old
    assert risk.check_fading(_months([100] * 36 + [50] * 12), NOW) == []  # still busy
    assert risk.check_fading([], NOW) == []


def test_fading_demand_costs_points():
    from steam_researcher import scoring
    g = Game(appid=1, name="x", positive=4000, negative=4000, price_cents=999)
    flag = risk.check_fading(_months([500] * 36 + [1] * 12), NOW)
    assert scoring.score(g, flag, None).penalty == 10


def test_reviews_use_playtime_at_review():
    data = {"reviews": [
        {"recommendationid": "1", "review": "x", "author": {"playtime_forever": 900, "playtime_at_review": 25}},
        {"recommendationid": "2", "review": "y", "author": {"playtime_forever": 900}},
    ]}
    assert [r.playtime_minutes for r in steam_store.parse_reviews(data)] == [25, 900]


def test_review_sample_mixes_helpful_and_newest(monkeypatch):
    from steam_researcher import pipeline
    from steam_researcher.models import Review

    calls = []

    def reviews(http, appid, kind, limit, order="all"):
        calls.append((order, limit))
        ids = ["a", "b", "c"] if order == "all" else ["c", "d"]  # "c" is in both
        return [Review(recommendation_id=i, text=i, voted_up=False) for i in ids][:limit]

    monkeypatch.setattr(steam_store, "reviews", reviews)
    got = pipeline.review_sample(None, 1, "negative", 5)
    assert calls == [("all", 3), ("recent", 2)]
    assert [r.recommendation_id for r in got] == ["a", "b", "c", "d"]


# --- official review numbers -----------------------------------------------------------------

def test_parse_review_summary():
    data = {"response": {"query_summary": {"total_positive": 928, "total_negative": 532, "total_reviews": 1460}}}
    assert steam_store.parse_review_summary(data) == (928, 1460)
    assert steam_store.parse_review_summary({"response": {"query_summary": {"total_reviews": 0}}}) is None
    assert steam_store.parse_review_summary({}) is None


def test_review_summary_asks_for_all_languages(tmp_path, monkeypatch):
    monkeypatch.setattr("steam_researcher.http.time.sleep", lambda s: None)
    seen = []

    def handler(request):
        seen.append(json.loads(request.url.params["input_json"]))
        return httpx.Response(200, json={"response": {"query_summary": {"total_positive": 3, "total_reviews": 4}}})

    http = HttpClient(cache=Cache(tmp_path / "c.sqlite"), transport=httpx.MockTransport(handler))
    assert steam_store.review_summary(http, 7) == (3, 4)
    # without languages=["all"] the summary is English-only
    assert seen[0]["languages"] == ["all"] and seen[0]["num_per_page"] == 0 and seen[0]["day_range"] == 0


def _game(**kw):
    from steam_researcher.models import Game

    return Game(appid=1, name="G", positive=kw.pop("positive", 300), negative=kw.pop("negative", 700), **kw)


def test_official_reviews_replace_steamspy(monkeypatch):
    from steam_researcher import pipeline

    monkeypatch.setattr(steam_store, "review_summary", lambda http, appid: (928, 1460))
    g = pipeline.official_reviews(None, _game(), [])
    assert (g.positive, g.negative, g.rating_source) == (928, 532, "steam")
    assert g.steamspy_rating == 30


def test_official_reviews_fall_back(monkeypatch):
    from steam_researcher import pipeline
    from steam_researcher.models import HistPoint

    def down(http, appid):
        raise RuntimeError("redirected")

    monkeypatch.setattr(steam_store, "review_summary", down)
    hist = [HistPoint(date=0, up=60, down=40), HistPoint(date=1, up=20, down=0)]
    g = pipeline.official_reviews(None, _game(), hist)
    assert (g.positive, g.negative, g.rating_source) == (80, 40, "histogram")
    g = pipeline.official_reviews(None, _game(), [])
    assert (g.positive, g.rating_source, g.steamspy_rating) == (300, "steamspy", None)


def test_rating_source_text():
    from steam_researcher.report import rating_source_text

    assert rating_source_text(_game()) == "SteamSpy estimate"
    assert rating_source_text(_game(rating_source="steam", steamspy_rating=31)) == "Steam's own numbers"
    assert rating_source_text(_game(rating_source="steam", steamspy_rating=40)) == "Steam's own numbers (SteamSpy says 40%)"


# --- "is it already fixed?" ------------------------------------------------------------------

def _rated(old: tuple[int, int], new: tuple[int, int], old_months=24) -> list[HistPoint]:
    """old_months of (up, down) per month, then 12 recent months of (up, down)."""
    pts = [old] * old_months + [new] * 12
    n = len(pts)
    return [HistPoint(date=NOW - (n - 1 - i) * MONTH, up=u, down=d) for i, (u, d) in enumerate(pts)]


def test_recent_rating():
    assert risk.recent_rating(_rated((10, 90), (8, 2)), NOW) == 80
    assert risk.recent_rating([], NOW) is None


def test_much_better_lately_is_flagged_and_costs_points():
    from steam_researcher import scoring

    flags = risk.check_recovered(_rated((40, 60), (8, 2)), NOW)  # 40% all along, 80% lately
    assert [f.code for f in flags] == ["recovered"]
    assert "80% positive in the last 12 months" in flags[0].message
    g = Game(appid=1, name="x", positive=4000, negative=6000, price_cents=999)
    assert scoring.score(g, flags, None).penalty == 20


def test_steady_or_thin_recent_rating_is_not_flagged():
    assert risk.check_recovered(_rated((40, 60), (5, 5)), NOW) == []  # 50% lately: +6 points, under 70
    assert risk.check_recovered(_rated((40, 60), (3, 0)), NOW) == []  # 36 recent reviews: too few to judge
    assert risk.check_recovered([], NOW) == []
    # reaching 70%+ lately is enough even when the all-time rating is close
    assert risk.check_recovered(_rated((60, 40), (6, 2)), NOW)[0].code == "recovered"
