import pytest
from typer.testing import CliRunner

from steam_researcher import market, notices, pipeline
from steam_researcher.cli import app
from steam_researcher.market import MarketStats, market_stats

from test_m4 import game
from test_notices import post, tag_result


def g(pct_positive, n=1000, appid=1):
    pos = round(n * pct_positive / 100)
    return game(pos=pos, neg=n - pos, appid=appid)


def test_market_stats_counts_each_group():
    games = [g(40, appid=1), g(60, appid=2), g(90, appid=3), g(75, appid=4), g(40, n=50, appid=5)]
    m = market_stats(games, min_reviews=100, lo=5, hi=70)
    assert (m.n_games, m.n_demand, m.n_underserved, m.n_well_served) == (5, 4, 2, 1)
    assert m.gap == 2 / 3
    assert m.median_rating == 67.5  # of 40, 60, 75, 90
    assert m.underserved_gross == pytest.approx(2 * 1000 * 45 * 9.99)


def test_market_stats_without_demand_games():
    m = market_stats([g(40, n=10)], min_reviews=100, lo=5, hi=70)
    assert (m.n_demand, m.gap, m.median_rating, m.underserved_gross) == (0, 0.0, 0.0, 0.0)
    assert market_stats([], 100, 5, 70).n_games == 0


def test_summary_is_ascii():
    text = market.summary(market_stats([g(40), g(90, appid=2)], 100, 5, 70))
    assert text.isascii() and "gap 50%" in text


def test_well_served_market_gets_a_notice():
    stats = MarketStats(n_games=50, n_demand=20, n_underserved=1, n_well_served=9, median_rating=88,
                        underserved_gross=0, gap=0.1)
    assert "Audience already well served" in [n.title for n in post(tag_result(market=stats))]
    few = stats.model_copy(update={"n_well_served": 3, "gap": 0.25})  # too few games to judge
    assert "Audience already well served" not in [n.title for n in post(tag_result(market=few))]


def test_run_markets_ranks_tags_and_skips_slow_ones(monkeypatch):
    monkeypatch.setattr(pipeline.steam_store, "tag_names", lambda http: ["Calm", "Broken", "Hot", "Incremental", "Empty"])

    def games_by_tag(http, tag):
        if tag == "Broken":
            raise RuntimeError("boom")
        return {"Calm": [g(90), g(40, appid=2)], "Hot": [g(40), g(50, appid=2), g(95, appid=3)]}.get(tag, [])

    monkeypatch.setattr(pipeline.steamspy, "games_by_tag", games_by_tag)
    steps = []
    r = pipeline.run_markets(None, 100, 5, 70, lambda msg, done, total: steps.append((done, total)))
    assert sorted(row.tag for row in r.rows) == ["Calm", "Hot"]  # "Empty" has no games
    assert r.skipped == ["Incremental"]
    assert [t for t, _ in r.failed] == ["Broken"]
    assert steps[0] == (0, 4)


def test_cli_markets(monkeypatch):
    monkeypatch.setattr(pipeline.steam_store, "tag_names", lambda http: ["Hot"])
    monkeypatch.setattr(pipeline.steamspy, "games_by_tag", lambda http, tag: [g(40), g(95, appid=2)])
    res = CliRunner().invoke(app, ["markets"])
    assert res.exit_code == 0, res.output
    assert "Hot" in res.output and "50%" in res.output


def test_discover_prints_market_line(monkeypatch):
    monkeypatch.setattr("steam_researcher.sources.steamspy.games_by_tag", lambda http, tag: [g(40), g(95, appid=2)])
    monkeypatch.setattr("steam_researcher.cli.verify_games", lambda http, c, n, p=None: (c[:n], [], set()))
    res = CliRunner().invoke(app, ["discover", "-t", "Hot"])
    assert "Market:" in res.output and "1 underserved" in res.output


def test_market_rank_puts_specific_underserved_tags_first():
    from steam_researcher.market import TagMarket

    def row(tag, n_games, under, well):
        gap = under / (under + well) if under + well else 0
        return TagMarket(tag=tag, stats=MarketStats(n_games=n_games, n_demand=under + well, n_underserved=under,
                                                    n_well_served=well, median_rating=60, underserved_gross=0, gap=gap))

    rows = [row("Indie", 50_000, 3000, 6000), row("Rugby", 20, 1, 0), row("Job Sim", 130, 10, 24),
            row("Colony Sim", 400, 30, 10)]
    assert [r.tag for r in sorted(rows, key=pipeline.market_rank)] == ["Colony Sim", "Job Sim", "Indie", "Rugby"]
