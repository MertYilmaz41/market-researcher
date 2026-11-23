import datetime as dt
import random

import pytest

from market_researcher import backtest, game_backtest as gb
from market_researcher.backtest import parse_month
from market_researcher.models import Game, HistPoint


def ts(m: int) -> int:
    """Unix time of the first day of backtest month m."""
    return int(dt.datetime(m // 12, m % 12 + 1, 1, tzinfo=dt.UTC).timestamp())


def hist(start: int, per_month: list[tuple[int, int]]) -> list[HistPoint]:
    return [HistPoint(date=ts(start + i), up=u, down=d) for i, (u, d) in enumerate(per_month)]


def test_niche_counts_match_brute_force():
    rng = random.Random(1)
    games = [(tuple(rng.sample(range(8), rng.randint(1, 7))), rng.random() < 0.3, rng.random() < 0.5) for _ in range(300)]
    index = gb.NicheIndex()
    for tags, hit, sold in games:
        index.add(tags, hit, sold)
    for x in [(0, 1, 2), (3, 5, 7), (2, 6), (4, 4, 1), (5,)]:
        want = [g for g in games if len(set(g[0]) & set(x)) >= min(2, len(set(x)))] if len(set(x)) >= 2 else []
        got = index.niche(x)
        assert (got.entrants, got.hits, got.sold) == (len(want), sum(g[1] for g in want), sum(g[2] for g in want)), x


def test_rows_use_only_what_was_known_at_t():
    t = parse_month("2020-01")
    x = gb.Entry(1, (10, 20, 30, 40), hist(t - 12, [(5, 5)] * 12 + [(1000, 0)] * 12))  # 50% before T, loved after
    entrants = [gb.Entry(100 + i, (10, 20), hist(t + 3, [(600, 10)])) for i in range(12)]  # hits, released after T
    [row] = gb.game_rows([x, *entrants], t)
    assert (row.reviews, row.rating) == (120, 50.0)
    assert (row.after.entrants, row.after.hits, row.tag) == (12, 12, 10)
    assert row.market.n_demand == 1 and row.usable


def test_small_games_are_dated_by_the_store():
    t = parse_month("2020-01")
    g = Game(appid=5, name="Small", positive=40, negative=10, tag_ids=[1, 2], release_date=dt.date(2020, 3, 5))
    e = gb.entry(g, [])
    assert e.release == t + 2 and e.outcome(24) == (False, False)
    index = gb.entrant_index([e], t, 24, 24)
    assert index.niche((1, 2)).entrants == 1 and index.niche((1, 2)).hits == 0


def synthetic_rows(signal) -> list[gb.GameRow]:
    """X games whose niche hit rate follows `signal(rating, rng)`; 40 first tags so the bootstrap has clusters."""
    rng = random.Random(7)
    rows = []
    for t in [*backtest.CUTOFFS, *backtest.RECENT_CUTOFFS]:
        for i in range(400):
            rating = rng.uniform(10, 99)
            hits = max(0, min(100, round(signal(rating, rng))))
            rows.append(gb.GameRow(tag=i % 40, t=parse_month(t), appid=i, reviews=rng.randint(100, 50_000), rating=rating,
                                   market=gb.NicheMarket(rng.randint(5, 500)),
                                   after=backtest.Outcomes(entrants=100, hits=hits, sold=hits)))
    return rows


@pytest.mark.parametrize("signal, passes", [
    (lambda rating, rng: rating / 5 + rng.gauss(0, 3), True),  # niches of liked games do better
    (lambda rating, rng: 10 + rng.gauss(0, 3), False),  # noise
])
def test_planted_signal_passes_and_noise_fails(signal, passes):
    rows = synthetic_rows(signal)
    recent = [r for r in rows if backtest.month_text(r.t) in backtest.RECENT_CUTOFFS]
    main = [r for r in rows if r not in recent]
    c = backtest.candidate("% positive", gb.MEASURES["% positive"], main, recent)
    assert c.passed is passes


def test_measures():
    row = gb.GameRow(tag=1, t=0, appid=1, reviews=9341, rating=77.0, market=gb.NicheMarket(10), after=backtest.Outcomes())
    assert gb.MEASURES["score before Nov 23 2026 (no floor, no penalties)"](row) == 0  # Moon Sweepers: above 70%
    assert gb.MEASURES["current score (no penalties)"](row) == pytest.approx(52, abs=0.5)  # floored (#6)
    assert gb.MEASURES["demand x satisfaction"](row) > 50
    assert gb.MEASURES["niche's earlier entrants' hit rate"](row) is None  # under MIN_ENTRANTS earlier entrants
