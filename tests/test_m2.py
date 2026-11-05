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
    assert all(q["review_type"] == 2 and q["day_range"] == 0 for q in seen)


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
