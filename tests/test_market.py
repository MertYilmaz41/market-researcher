import datetime as dt

import pytest
from typer.testing import CliRunner

from market_researcher import market, notices, pipeline
from market_researcher.cli import app
from market_researcher.market import MarketStats, market_stats

from test_m4 import game
from test_notices import fake_search, post, tag_result


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
    assert text.isascii() and "unmet share 50%" in text


def test_well_served_market_gets_a_notice():
    stats = MarketStats(n_games=50, n_demand=20, n_underserved=1, n_well_served=9, median_rating=88,
                        underserved_gross=0, gap=0.1)
    assert "Audience already well served" in [n.title for n in post(tag_result(market=stats))]
    few = stats.model_copy(update={"n_well_served": 3, "gap": 0.25})  # too few games to judge
    assert "Audience already well served" not in [n.title for n in post(tag_result(market=few))]


def tagged(pct, appid, *tag_ids):
    return g(pct, appid=appid).model_copy(update={"tag_ids": list(tag_ids)})


def fake_all_games(monkeypatch, games, tags):
    monkeypatch.setattr(pipeline.steam_store, "tag_ids", lambda http: tags)

    def search(http, tag_ids, on_page):
        assert tag_ids == []  # one read of every rated game, not one query per tag
        on_page(1, 2)
        on_page(2, 2)
        return games

    monkeypatch.setattr(pipeline.steam_search, "games_by_tags", search)


def test_run_markets_builds_every_tag_from_one_read(monkeypatch):
    games = [tagged(90, 1, 10), tagged(40, 2, 10, 20), tagged(50, 3, 20), tagged(95, 4, 20)]
    fake_all_games(monkeypatch, games, {"Calm": 10, "Hot": 20, "Empty": 30})
    steps = []
    r = pipeline.run_markets(None, 100, 5, 70, lambda msg, done, total: steps.append((done, total)))
    rows = {row.tag: row.stats for row in r.rows}
    assert sorted(rows) == ["Calm", "Hot"]  # "Empty" is no game's main tag
    assert (rows["Hot"].n_games, rows["Hot"].n_underserved, rows["Hot"].n_well_served) == (3, 2, 1)
    assert rows["Calm"].n_games == 2 and steps == [(1, 2), (2, 2)] and not r.skipped and not r.failed


def test_cli_markets(monkeypatch):
    fake_all_games(monkeypatch, [tagged(40, 1, 20), tagged(95, 2, 20)], {"Hot": 20})
    res = CliRunner().invoke(app, ["markets"])
    assert res.exit_code == 0, res.output
    assert "Hot" in res.output and "50%" in res.output and "first 7 tags" in res.output


def test_discover_prints_market_line(monkeypatch):
    fake_search(monkeypatch, {"Hot": [g(40), g(95, appid=2)]})
    monkeypatch.setattr("market_researcher.cli.verify_games", lambda http, c, n, p=None: (c[:n], [], set()))
    res = CliRunner().invoke(app, ["discover", "-t", "Hot"])
    assert "Market:" in res.output and "1 underserved" in res.output


def test_market_rank_puts_tags_with_many_well_served_games_first():
    from market_researcher.market import TagMarket

    def row(tag, n_games, under, well):
        gap = under / (under + well) if under + well else 0
        return TagMarket(tag=tag, stats=MarketStats(n_games=n_games, n_demand=under + well, n_underserved=under,
                                                    n_well_served=well, median_rating=60, underserved_gross=0, gap=gap))

    rows = [row("Indie", 50_000, 3000, 6000), row("Rugby", 20, 1, 0), row("Job Sim", 130, 10, 24),
            row("Colony Sim", 400, 30, 10)]
    # by well-served games (the backtest's signal, not the unmet share); broad tags last
    assert [r.tag for r in sorted(rows, key=pipeline.market_rank)] == ["Job Sim", "Colony Sim", "Rugby", "Indie"]


def _ts(year, month):
    import datetime as dt
    return int(dt.datetime(year, month, 15, tzinfo=dt.UTC).timestamp())


def test_track_record_counts_hits_among_games_released_48_to_24_months_ago(monkeypatch):
    from market_researcher.models import HistPoint
    now = _ts(2026, 11)  # window: released 2022-11 to 2024-10
    hists = {
        1: [HistPoint(date=_ts(2023, 1), up=900, down=100)],  # hit
        2: [HistPoint(date=_ts(2023, 6), up=300, down=300)],  # sold, no hit
        3: [HistPoint(date=_ts(2024, 10), up=5, down=5)],  # entrant, neither
        4: [HistPoint(date=_ts(2021, 1), up=900, down=100)],  # released before the window
        5: [HistPoint(date=_ts(2025, 1), up=900, down=100)],  # after it
        6: [HistPoint(date=_ts(2023, 1), up=400, down=0), HistPoint(date=_ts(2025, 6), up=400, down=0)],  # 500 only later
    }
    games = [game(pos=50, neg=50, appid=a) for a in hists] + [game(pos=3, neg=3, appid=99)]  # 99: under 10 reviews
    old = game(pos=50, neg=50, appid=98).model_copy(update={"release_date": dt.date(2022, 7, 31)})  # 4 months early
    games[3] = games[3].model_copy(update={"release_date": dt.date(2022, 8, 1)})  # 3 months early: still read
    games.append(old)
    fetched = []
    monkeypatch.setattr(pipeline, "tag_games", lambda http, tags: games)
    monkeypatch.setattr(pipeline.steam_store, "review_histogram",
                        lambda http, appid, ttl: fetched.append(appid) or hists[appid])
    tr = pipeline.track_record(None, ["Colony Sim"], now=now)
    assert 99 not in fetched and 98 not in fetched and 4 in fetched
    assert (tr.entrants, tr.hits, tr.sold) == (4, 1, 2) and tr.window() == ("2022-11", "2024-10")
    assert "too few to tell" in market.track_text(tr)
    tr.entrants = 20
    assert market.track_text(tr).startswith("Track record: 1 of 20 games released 2022-11 to 2024-10 became hits (5%")


def test_track_record_skips_broad_tags(monkeypatch):
    monkeypatch.setattr(pipeline.config, "TRACK_MAX_GAMES", 2)
    monkeypatch.setattr(pipeline, "tag_games", lambda http, tags: [game(pos=50, neg=50, appid=a) for a in range(3)])
    monkeypatch.setattr(pipeline.steam_store, "review_histogram", lambda *a, **k: pytest.fail("fetched a histogram"))
    tr = pipeline.track_record(None, ["Indie"], now=_ts(2026, 11))
    assert tr.too_broad == 3 and "too broad (3 games" in market.track_text(tr)


def priced(price, pct=40, n=1000, appid=1):
    from market_researcher.models import Game
    pos = round(n * pct / 100)
    return Game(appid=appid, name="G", positive=pos, negative=n - pos, price_cents=price, initial_price_cents=price)


def test_price_range_of_the_paid_games_with_demand():
    games = [priced(999, appid=1), priced(1499, appid=2), priced(1999, appid=3), priced(2499, pct=90, appid=4),
             priced(0, appid=5), priced(9999, n=10, appid=6)]  # free, and too few reviews: left out
    m = market_stats(games, 100, 5, 70)
    assert m.n_priced == 4 and m.price_median == pytest.approx(17.49)
    assert (m.price_p25, m.price_p75) == (pytest.approx(13.74), pytest.approx(21.24))
    assert m.well_served_price_median is None  # one well-served game: too few
    text = market.summary(m)
    assert text.isascii() and "median price $17.49 (middle half $13.74-$21.24)" in text


def test_no_price_range_with_too_few_paid_games_or_in_old_runs():
    assert market_stats([priced(999), priced(1999, appid=2)], 100, 5, 70).price_median is None
    old = MarketStats.model_validate({"n_games": 5, "n_demand": 4, "n_underserved": 2, "n_well_served": 1,
                                      "median_rating": 60, "underserved_gross": 1, "gap": 0.5})
    assert old.price_median is None and market.price_text(old) == ""


def test_related_tags_offers_shared_tags_for_narrowing():
    games = [game(appid=i) for i in range(4)]
    for x, tags in zip(games, [["Crafting", "Survival", "Co-op"], ["crafting", "Survival", "Co-op"],
                               ["Survival", "Open World"], ["Survival", "Co-op", "Base Building"]]):
        x.tags = {t: 10 for t in tags}
    got = market.related_tags(games, ["Crafting"])
    # the searched tag is left out in any case; tags on a single game too; most shared first, ties by name
    assert got == [{"tag": "Survival", "n": 4}, {"tag": "Co-op", "n": 3}]
    assert market.related_tags(games, ["Crafting"], limit=1) == [{"tag": "Survival", "n": 4}]
    assert market.related_tags([], ["Crafting"]) == []
