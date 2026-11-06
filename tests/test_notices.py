import re

import httpx
import pytest
from typer.testing import CliRunner

from steam_researcher import notices, pipeline
from steam_researcher.cli import app
from steam_researcher.http import RetryableStatus
from steam_researcher.models import AppDetails
from steam_researcher.pipeline import TagResult

from test_m4 import analysis, flag, game

REQ = httpx.Request("GET", "https://steamspy.com/api.php?request=tag")


def titles(items):
    return [n.title for n in items]


def tag_result(**kw):
    base = dict(n_tag_games=100, candidates=[game()], analyses=[analysis(40, "Best", appid=1)], n_enough_reviews=20)
    return TagResult(**(base | kw))


def post(result, max_games=15, tag="Job Simulator"):
    return notices.for_tag_result(tag, 100, 5, 70, max_games, result)


# ---------- before a run ----------

def test_filters_clean_by_default():
    assert notices.for_filters(100, 5, 70, 15, 200) == []


def test_filters_each_rule():
    assert titles(notices.for_filters(50, 5, 70, 15, 200)) == ["Demand not proven"]
    assert titles(notices.for_filters(100, 5, 90, 15, 200)) == ["Above 70% isn't underserved"]
    assert titles(notices.for_filters(100, 0, 70, 15, 200)) == ["Very low ratings included"]
    assert titles(notices.for_filters(100, 5, 70, 40, 400)) == ["This may take a while"]


# ---------- after a tag run ----------

def test_success_notice_names_top_game():
    out = post(tag_result())
    assert out[-1].level == "success" and "Best" in out[-1].message


def test_no_candidates_explains_which_filter():
    none_enough = post(tag_result(candidates=[], analyses=[], n_enough_reviews=0))
    assert titles(none_enough) == ["No games with enough reviews"] and "Minimum reviews" in none_enough[0].hint
    none_in_range = post(tag_result(candidates=[], analyses=[], n_enough_reviews=12))
    assert titles(none_in_range) == ["No games in the rating range"] and "12" in none_in_range[0].message


def test_only_non_games():
    dlc = analysis(50, "DLC", [flag("not_game", "high")])
    assert "Nothing left to rank" in titles(post(tag_result(analyses=[dlc])))


def test_few_and_capped_candidates():
    assert "Few candidates" in titles(post(tag_result()))
    many = tag_result(candidates=[game(appid=i) for i in range(30)])
    out = titles(post(many, max_games=15))
    assert "Not every candidate analyzed" in out and "Few candidates" not in out


def test_no_game_has_all_tags():
    out = post(tag_result(n_tag_games=0, candidates=[], analyses=[], n_enough_reviews=0), tag="Crafting + Survival")
    assert titles(out) == ["No game has all these tags"] and "Crafting + Survival" in out[0].message


def test_broad_tag():
    assert "Very broad tag" in titles(post(tag_result(n_tag_games=5000), tag="Action"))


def test_failed_and_missing_reviews():
    no_reviews = analysis(30, "NoRev", mined=False, appid=2)
    out = post(tag_result(analyses=[analysis(40, "Best", appid=1), no_reviews],
                          failed=[("Broken Game", "The connection to steamspy.com failed.")]))
    assert "1 game(s) couldn't be analyzed" in titles(out)
    assert "Review texts unavailable" in titles(out)
    assert "Broken Game" in next(n for n in out if n.title.startswith("1 game")).message


def test_zero_and_weak_scores():
    assert "No real opportunity found" in titles(post(tag_result(analyses=[analysis(0, "Meh")])))
    weak = titles(post(tag_result(analyses=[analysis(12, "Meh")])))
    assert "Only weak opportunities" in weak and "Analysis complete" in weak


# ---------- single game ----------

def test_for_game_clean():
    assert notices.for_game(analysis(40, "Fine")) == []


def test_for_game_rules():
    a = analysis(0, "Liked")
    a.opportunity.effective_rating = 85
    assert titles(notices.for_game(a)) == ["Players are satisfied"]

    dlc = analysis(0, "Pack", [flag("not_game", "high")])
    dlc.details = AppDetails(appid=1, type="dlc", name="Pack")
    out = notices.for_game(dlc)
    assert out[0].level == "error" and "dlc" in out[0].message

    small = analysis(30, "Small")
    small.game.positive, small.game.negative = 20, 30
    assert "Demand not proven" in titles(notices.for_game(small))

    free = analysis(30, "Free")
    free.game.price_cents = free.game.initial_price_cents = 0
    assert "Free game" in titles(notices.for_game(free))

    assert "Review texts unavailable" in titles(notices.for_game(analysis(30, "X", mined=False)))
    assert "No store page" in titles(notices.for_game(analysis(30, "X", [flag("unlisted", "info")])))


# ---------- errors ----------

@pytest.mark.parametrize("exc, title", [
    (httpx.ConnectError("x", request=REQ), "Can't reach steamspy.com"),
    (httpx.ReadTimeout("x", request=REQ), "steamspy.com timed out"),
    (RetryableStatus("https://steamspy.com/api.php returned HTTP 503"), "steamspy.com is busy"),
    (httpx.HTTPStatusError("x", request=REQ, response=httpx.Response(403, request=REQ)), "steamspy.com refused the request"),
    (RuntimeError("https://store.steampowered.com/x redirected to '/'; endpoint unavailable"),
     "Unexpected answer from store.steampowered.com"),
    (ValueError("weird"), "Unexpected error"),
])
def test_friendly_error(exc, title):
    n = notices.friendly_error(exc)
    assert n.level == "error" and n.title == title and n.hint


# ---------- pipeline resilience ----------

def fake_verify(http, candidates, limit, progress=None, on_hit=None):
    for g in candidates:
        on_hit(g)
    return candidates, [], set()


def test_run_tag_survives_one_broken_game(monkeypatch):
    games = [game(appid=1, name="Good"), game(appid=2, name="Broken")]
    monkeypatch.setattr(pipeline.steamspy, "games_by_tag", lambda http, tag: games)
    monkeypatch.setattr(pipeline, "verify_games", fake_verify)

    def analyze(http, appid, n):
        if appid == 2:
            raise httpx.ConnectError("x", request=REQ)
        return analysis(40, "Good", appid=1)

    monkeypatch.setattr(pipeline, "analyze_game", analyze)
    result = pipeline.run_tag(None, ["T"], 100, 5, 70, 10, 50)
    assert [a.game.name for a in result.analyses] == ["Good"]
    assert result.failed == [("Broken", "The connection to steamspy.com failed.")]
    assert result.n_enough_reviews == 2


# ---------- CLI ----------

def test_cli_network_error_is_friendly(monkeypatch):
    def down(http, tag):
        raise httpx.ConnectError("x", request=REQ)

    monkeypatch.setattr("steam_researcher.sources.steamspy.games_by_tag", down)
    monkeypatch.delenv("SR_DEBUG", raising=False)
    res = CliRunner().invoke(app, ["discover", "--tag", "Job Simulator"])
    assert res.exit_code == 1
    assert "Can't reach steamspy.com" in res.output and "Traceback" not in res.output


def test_cli_unknown_tag(monkeypatch):
    monkeypatch.setattr("steam_researcher.sources.steamspy.games_by_tag", lambda http, tag: [])
    monkeypatch.setattr(notices, "known_tags", lambda http: ["Xyz Sim", "Colony Sim"])
    res = CliRunner().invoke(app, ["discover", "--tag", "Xyzzy"])
    assert res.exit_code == 1 and "Tag not found" in res.output


def test_tag_games_keeps_only_games_with_every_tag(monkeypatch):
    by_tag = {"A": [game(appid=1, name="One"), game(appid=2, name="Two"), game(appid=3, name="Three")],
              "B": [game(appid=3), game(appid=2)], "C": [game(appid=2), game(appid=9)]}
    monkeypatch.setattr(pipeline.steamspy, "games_by_tag", lambda http, tag: by_tag.get(tag, []))
    assert [g.name for g in pipeline.tag_games(None, ["A", "B"])] == ["Two", "Three"]
    assert [g.appid for g in pipeline.tag_games(None, ["A", "B", "C"])] == [2]
    assert pipeline.tag_games(None, ["A", "C", "B"]) and pipeline.tag_label(["A", "B"]) == "A + B"
    with pytest.raises(pipeline.UnknownTag) as e:
        pipeline.tag_games(None, ["A", "Nope", "B"])
    assert e.value.tag == "Nope"


def test_cli_multiple_tags(monkeypatch):
    by_tag = {"Crafting": [game(appid=1, name="Only Crafting"), game(appid=2, name="Both Games")],
              "Survival": [game(appid=2, name="Both Games"), game(appid=3, name="Only Survival")]}
    monkeypatch.setattr("steam_researcher.sources.steamspy.games_by_tag", lambda http, tag: by_tag.get(tag, []))
    monkeypatch.setattr("steam_researcher.cli.verify_games", lambda http, c, n, p=None: (c[:n], [], set()))
    res = CliRunner().invoke(app, ["discover", "-t", "Crafting", "-t", "Survival", "--min-reviews", "1", "--rating", "0-100"])
    assert res.exit_code == 0, res.output
    assert "Crafting + Survival" in res.output and "Both Games" in res.output and "Only" not in res.output
    res = CliRunner().invoke(app, ["discover"] + [x for t in "ABCDEF" for x in ("-t", t)])
    assert res.exit_code == 2 and "at most 5 tags" in res.output


def test_cli_option_bounds():
    res = CliRunner().invoke(app, ["report", "--tag", "X", "--max-games", "99"])
    text = re.sub(r"\x1b\[[0-9;]*m", "", res.output)  # CI (GitHub Actions) gets colored output
    assert res.exit_code == 2 and "max-games" in text


def test_cli_game_not_found_is_not_unexpected(monkeypatch):
    monkeypatch.setattr("steam_researcher.pipeline.analyze_game", lambda http, appid, n: None)
    res = CliRunner().invoke(app, ["analyze", "999999999"])
    assert res.exit_code == 1 and "Game not found" in res.output and "Unexpected error" not in res.output


def test_unknown_tag_detected_by_steamspy_fallback():
    from steam_researcher.sources import steamspy

    fallback = {"10": {"appid": 10, "name": "Fallback"}}
    real = {"20": {"appid": 20, "name": "Real"}}

    class FakeHttp:
        def get_json(self, url, params, ttl):
            return real if params["tag"] == "Job Simulator" else fallback

    assert steamspy.games_by_tag(FakeHttp(), "Qwzzqxnope") == []
    assert [g.name for g in steamspy.games_by_tag(FakeHttp(), "Job Simulator")] == ["Real"]
    assert steamspy.games_by_tag(FakeHttp(), "  ") == []


# ---------- tag catalog ----------

def test_parse_tag_list():
    from steam_researcher.sources.steam_store import parse_tag_list

    data = {"response": {"tags": [{"tagid": 1, "name": "indie"}, {"tagid": 2, "name": "Colony Sim"},
                                  {"tagid": 3, "name": "Action"}, {"tagid": 4, "name": "Action"}, {"tagid": 5}]}}
    assert parse_tag_list(data) == ["Action", "Colony Sim", "indie"]
    assert parse_tag_list({}) == [] and parse_tag_list(None) == []


def test_unknown_tag_suggests_close_tags():
    known = ["Colony Sim", "Farming Sim", "Job Simulator", "Action"]
    assert notices.unknown_tag("Colny Sim", known).hint.startswith("Did you mean Colony Sim")
    assert "Examples:" in notices.unknown_tag("Colny Sim").hint
    assert "Examples:" in notices.unknown_tag("Qwzzqxnope", known).hint


def test_unsearchable_steam_tag_is_explained_not_suggested_back():
    n = notices.unknown_tag("Incremental", ["Incremental", "Idler", "Clicker", "Instrumental Music"])
    assert n.title == "Tag can't be searched" and "SteamSpy (the data source) can't search it" in n.message
    assert "Incremental" not in n.hint
    # also when Steam's catalog (known) already hides it
    assert notices.unknown_tag("incremental", []).title == "Tag can't be searched"


def test_renamed_tags_use_the_steamspy_name():
    from steam_researcher.sources import steamspy

    asked = []

    class FakeHttp:
        def get_json(self, url, params, ttl):
            asked.append(params["tag"])
            return {"1": {"appid": 1, "name": "Real"}} if params["tag"] else {"9": {"appid": 9, "name": "Fallback"}}

    assert [g.name for g in steamspy.games_by_tag(FakeHttp(), "Roguelite")] == ["Real"]
    steamspy.games_by_tag(FakeHttp(), "roguelike")
    steamspy.games_by_tag(FakeHttp(), "Idler")
    assert [a for a in asked if a] == ["Rogue-lite", "Rogue-like", "Idler"]


def test_tag_list_keeps_every_steam_tag():
    from steam_researcher.sources.steam_store import parse_tag_ids, parse_tag_list

    data = {"response": {"tags": [{"tagid": i, "name": n} for i, n in
                                  enumerate(["Idler", "Incremental", "Point & Click", "Roguelite"], 1)]}}
    assert parse_tag_list(data) == ["Idler", "Incremental", "Point & Click", "Roguelite"]
    assert parse_tag_ids(data)["Incremental"] == 2


# ---------- Steam store search (tags SteamSpy can't search) ----------

def _row(appid, title, reviews="", price='<div class="discount_final_price">$8.99</div>', final=899):
    tip = f' data-tooltip-html="Very Positive&lt;br&gt;{reviews} user reviews for this game are positive."' if reviews else ""
    return (f'<a href="https://store.steampowered.com/app/{appid}/X/?snr=1" data-ds-appid="{appid}" class="search_result_row">'
            f'<span class="title">{title}</span><span class="search_review_summary"{tip}></span>'
            f'<div class="search_price_discount_combined" data-price-final="{final}">{price}</div></a>')


SEARCH_PAGE = {"success": 1, "total_count": 250, "results_html": "\n".join([
    _row(1, "Plain &amp; Simple", "78% of the 3,325"),
    _row(2, "On Sale", "90% of the 100", '<div class="discount_original_price">$9.99</div>'
                                         '<div class="discount_final_price">$4.99</div>', 499),
    _row(3, "Free Game", "75% of the 21,990", '<div class="discount_final_price free">Free</div>', 0),
    _row(4, "No Reviews Yet"),
    '<a href="https://store.steampowered.com/bundle/77/B/" data-ds-bundleid="77"><span class="title">A Bundle</span></a>',
    _row("5,6", "A Package"),
])}


def test_parse_search_page():
    from steam_researcher.sources.steam_search import parse_search_page

    games, total = parse_search_page(SEARCH_PAGE)
    assert total == 250 and [g.name for g in games] == ["Plain & Simple", "On Sale", "Free Game", "No Reviews Yet"]
    plain, sale, free, new = games
    assert (plain.reviews, plain.positive, plain.price_cents) == (3325, 2594, 899)
    assert (sale.price_cents, sale.initial_price_cents, sale.base_price) == (499, 999, 9.99)
    assert free.base_price == 0 and free.reviews == 21990
    assert new.reviews == 0
    assert parse_search_page({}) == ([], 0) and parse_search_page(None) == ([], 0)


def test_steam_search_pages_through_a_tag():
    from steam_researcher.sources import steam_search

    starts, steps = [], []

    class FakeHttp:
        def get_json(self, url, params, ttl):
            starts.append(params["start"])
            rows = [_row(params["start"] + i, f"G{params['start'] + i}", "50% of the 200") for i in range(1, 4)]
            return {"total_count": 250, "results_html": "".join(rows)}

    games = steam_search.games_by_tag(FakeHttp(), 560542, lambda d, t: steps.append((d, t)))
    assert starts == [0, 100, 200] and steps == [(1, 3), (2, 3), (3, 3)] and len(games) == 9


def test_tag_games_uses_steam_search_for_tags_steamspy_cant_search(monkeypatch):
    by_spy = {"Idler": [game(appid=1, name="Both"), game(appid=2, name="Only Idler")]}
    monkeypatch.setattr(pipeline.steamspy, "games_by_tag", lambda http, tag: by_spy.get(tag, []))
    monkeypatch.setattr(pipeline.steam_store, "tag_ids", lambda http: {"Incremental": 560542, "Idler": 615955})
    asked = []

    def search(http, tag_id, on_page):
        asked.append(tag_id)
        on_page(1, 1)
        return [game(appid=1, name="Both"), game(appid=3, name="Only Incremental")]

    monkeypatch.setattr(pipeline.steam_search, "games_by_tag", search)
    steps = []
    games = pipeline.tag_games(None, ["incremental", "Idler"], lambda m, d, t: steps.append((m, d, t)))
    assert asked == [560542] and [g.name for g in games] == ["Both"]
    assert steps == [("Listing games tagged incremental from the Steam store", 1, 1)]


# ---------- parallel analysis ----------

def test_run_tag_analyzes_in_parallel_and_keeps_order(monkeypatch):
    import threading
    import time

    games = [game(appid=i, name=f"G{i}") for i in range(1, 5)]
    monkeypatch.setattr(pipeline.steamspy, "games_by_tag", lambda http, tag: games)
    monkeypatch.setattr(pipeline, "verify_games", fake_verify)
    seen, steps = set(), []

    def slow_analyze(http, appid, n):
        seen.add(threading.get_ident())
        time.sleep(0.3 if appid == 1 else 0.1)  # the first game finishes last
        return analysis(40, f"G{appid}", appid=appid)

    monkeypatch.setattr(pipeline, "analyze_game", slow_analyze)
    start = time.monotonic()
    result = pipeline.run_tag(None, ["T"], 100, 5, 70, 10, 50, lambda m, d, t: steps.append((m, d, t)))
    assert time.monotonic() - start < 0.6  # sequential would take 0.6 s
    assert len(seen) > 1
    assert [a.game.name for a in result.analyses] == ["G1", "G2", "G3", "G4"]
    assert steps[-1] == ("Analyzed G1", 4, 4)


def test_review_timeout_keeps_the_game(monkeypatch):
    """A slow review API must not drop the game: it is ranked without complaint mining."""
    from steam_researcher.sources import steam_store, steamspy

    monkeypatch.setattr(steamspy, "game_details", lambda http, appid: game(appid=appid, name="Slow"))
    monkeypatch.setattr(steam_store, "app_details", lambda http, appid: None)
    monkeypatch.setattr(steam_store, "review_histogram", lambda http, appid: [])

    def stalled(*a, **kw):
        raise httpx.ReadTimeout("x", request=httpx.Request("GET", "https://api.steampowered.com/IUserReviewsService/"))

    monkeypatch.setattr(steam_store, "reviews", stalled)
    monkeypatch.setattr(steam_store, "review_summary", stalled)
    a = pipeline.analyze_game(None, 7, 100)
    assert a is not None and a.mining is None
    assert a.review_error == "api.steampowered.com didn't answer in time."
    assert a.game.rating_source == "steamspy"  # Steam's own numbers timed out too: SteamSpy's stay



def test_run_tag_stops_when_on_step_cancels(monkeypatch):
    import threading
    games = [game(appid=i, name=f"G{i}") for i in range(1, 9)]
    started = []
    release = threading.Event()
    monkeypatch.setattr(pipeline.steamspy, "games_by_tag", lambda http, tag: games)
    monkeypatch.setattr(pipeline, "verify_games",
                        lambda http, c, n, p, on_hit: ([on_hit(g) or g for g in c[:n]], [], set()))

    def analyze(http, appid, n):
        started.append(appid)
        release.wait(5)
        return None

    monkeypatch.setattr(pipeline, "analyze_game", analyze)

    def step(message, done, total):
        if message == "Analyzing games":  # first heartbeat while games are running
            raise pipeline.Cancelled

    with pytest.raises(pipeline.Cancelled):
        pipeline.run_tag(None, ["X"], 1, 0, 100, 8, 10, step)
    release.set()
    assert len(started) <= 4  # games not started yet were dropped (ANALYZE_WORKERS = 4)
