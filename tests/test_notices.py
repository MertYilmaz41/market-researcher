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
    result = pipeline.run_tag(None, "T", 100, 5, 70, 10, 50)
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


def test_cli_option_bounds():
    res = CliRunner().invoke(app, ["report", "--tag", "X", "--max-games", "99"])
    assert res.exit_code == 2 and "max-games" in res.output


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
    result = pipeline.run_tag(None, "T", 100, 5, 70, 10, 50, lambda m, d, t: steps.append((m, d, t)))
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
    a = pipeline.analyze_game(None, 7, 100)
    assert a is not None and a.mining is None
    assert a.review_error == "api.steampowered.com didn't answer in time."
