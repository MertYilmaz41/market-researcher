import calendar

from market_researcher import backtest as bt
from market_researcher.market import market_stats
from market_researcher.models import Game, HistPoint


def ts(text: str) -> int:
    year, mon = map(int, text.split("-"))
    return calendar.timegm((year, mon, 1, 0, 0, 0))


def hist(*points: tuple[str, int, int]) -> list[HistPoint]:
    return [HistPoint(date=ts(m), up=up, down=down) for m, up, down in points]


def game(appid: int, positive: int = 0, negative: int = 0) -> Game:
    return Game(appid=appid, name=f"g{appid}", positive=positive, negative=negative, price_cents=999)


M = bt.parse_month


def test_months():
    assert bt.month(ts("2021-01")) == M("2021-01") == M("2020-12") + 1
    assert bt.month_text(M("2021-03")) == "2021-03"


def test_as_of_window_and_release():
    h = hist(("2018-05", 0, 0), ("2018-06", 10, 5), ("2019-01", 20, 0), ("2020-06", 3, 7))
    assert bt.release_month(h) == M("2018-06")
    assert bt.as_of(h, M("2019-01")) == (10, 5)  # months before T only
    assert bt.as_of(h, M("2019-02")) == (30, 5)
    assert bt.window(h, M("2018-06"), 12) == (30, 5)  # 2018-06 .. 2019-05
    assert bt.release_month(hist(("2018-05", 0, 0))) is None


def test_game_at():
    g = game(1, positive=999, negative=999)
    h = hist(("2018-06", 80, 20), ("2022-01", 0, 100))
    past = bt.game_at(g, h, M("2020-01"))
    assert (past.positive, past.negative, past.rating) == (80, 20, 80.0)
    assert past.base_price == g.base_price
    assert bt.game_at(g, h, M("2018-06")) is None  # no reviews yet


def test_outcomes_counts_entrants_in_horizon_only():
    t = M("2020-01")
    hit = hist(("2020-03", 450, 50))  # 500 reviews at 90%
    sold_only = hist(("2021-12", 300, 200))  # 500 reviews at 60%, released in the last horizon month
    flop = hist(("2020-05", 400, 50), ("2023-01", 100, 0))  # 450 in its first 24 months
    edge = hist(("2020-02", 400, 100))  # exactly 80%: a hit
    before = hist(("2019-12", 900, 0))
    after = hist(("2022-01", 900, 0))
    out = bt.outcomes([hit, sold_only, flop, edge, before, after], t)
    assert (out.entrants, out.hits, out.sold) == (4, 2, 3)
    assert out.hit_rate == 0.5 and out.sold_rate == 0.75
    assert bt.outcomes([], t).hit_rate == 0.0


def test_tag_row_uses_market_stats_at_t():
    t = M("2020-01")
    games = [
        (game(1), hist(("2017-01", 50, 150))),  # 25% at T: underserved
        (game(2), hist(("2017-01", 180, 20))),  # 90%: well served
        (game(3), hist(("2017-01", 10, 10))),  # under MIN_REVIEWS
        (game(4), hist(("2020-02", 500, 0))),  # entrant, hit
        (game(5), hist(("2018-03", 600, 0))),  # entrant before T, hit
    ]
    row = bt.tag_row("X", games, t)
    then = [game(1, 50, 150), game(2, 180, 20), game(3, 10, 10), game(5, 600, 0)]
    assert row.market == market_stats(then, 100, 5, 70)
    assert row.market.gap == 1 / 3  # game 5 is out by T: 1 underserved, 2 well served
    assert (row.after.entrants, row.after.hits) == (1, 1)
    assert (row.before.entrants, row.before.hits) == (1, 1)
    assert not row.usable  # 1 entrant is too few


def test_spearman_and_partial():
    assert bt.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert bt.spearman([1, 2], [1, 2]) != bt.spearman([1, 2], [1, 2])  # NaN: too few
    # y follows z only; x follows z too: their link vanishes once z is held fixed
    z = [1, 2, 3, 4, 5, 6, 7, 8]
    x = [1, 2, 4, 3, 5, 6, 8, 7]
    y = [2, 1, 3, 4, 6, 5, 7, 8]
    assert bt.spearman(x, y) > 0.9
    assert abs(bt.partial_spearman(x, y, z)) < 0.1


def test_quintiles_and_render():
    rows = []
    for i in range(10):
        h = [(game(100 + j), hist(("2020-03", 600 if j < i else 10, 0))) for j in range(12)]
        h += [(game(1), hist(("2015-01", 20, 180))), (game(2), hist(("2015-01", 190, 10)))]
        h += [(game(3 + k), hist(("2015-01", 30 + 10 * i, 170))) for k in range(4)]
        row = bt.tag_row(f"T{i}", h, M("2020-01"))
        rows.append(row)
    assert all(r.usable for r in rows)
    q = bt.quintiles(rows)
    assert len(q) == 5 and sum(n for _, n, _, _ in q) == 120
    assert [hits for _, _, hits, _ in q] == [1, 5, 9, 13, 17]  # gap rises with i, and so do hits


def test_per_cutoff_ignores_the_year_trend():
    # within each year, a higher gap goes with a higher hit rate; across years both fall
    rows = []
    for t, base in ((M("2019-01"), 0.6), (M("2021-01"), 0.1)):
        for i in range(4):
            r = bt.Row(tag=f"T{i}", t=t, market=market_stats([], 100, 5, 70), after=bt.Outcomes(100, int(100 * (base + 0.05 * i)), 0), before=bt.Outcomes())
            r.market = r.market.model_copy(update={"gap": 0.9 - 0.2 * (t == M("2019-01")) + 0.02 * i})
            rows.append(r)
    stat = bt.STATS["gap vs hit rate"]
    assert stat(rows) < 0.5  # pooled: the year trend hides it
    assert bt.per_cutoff(stat)(rows) == 1.0
    text = bt.render(rows, ["Skipped"])
    assert "| gap vs hit rate |" in text and "Skipped" in text


def synthetic_rows(hits_for, n=20):
    """One cutoff, n tags with rising gap; hits_for(i) gives tag i's hits out of 100 entrants.
    Market size goes up and down, unrelated to the gap."""
    rows = []
    for i in range(n):
        m = market_stats([], 100, 5, 70).model_copy(update={"gap": i / n, "n_demand": (i * 7) % n})
        rows.append(bt.Row(tag=f"T{i}", t=M("2020-01"), market=m, after=bt.Outcomes(100, hits_for(i), 0),
                           before=bt.Outcomes()))
    return rows


def test_verdict_holds_when_all_criteria_pass():
    result, checks = bt.verdict(synthetic_rows(lambda i: 5 + i))
    assert result == "holds" and len(checks) == 4 and all(ok for _, ok in checks)


def test_verdict_fails_on_a_weak_effect_or_none():
    # rises with the gap, but the top fifth is only ~1.1x the bottom: too small to matter
    result, checks = bt.verdict(synthetic_rows(lambda i: 40 + i // 4))
    assert result == "does not hold" and not checks[3][1]
    assert bt.verdict(synthetic_rows(lambda i: 30 - i))[0] == "does not hold"  # falls with the gap


def test_verdict_without_enough_rows():
    assert bt.verdict(synthetic_rows(lambda i: i, n=2)) == ("not enough data", [])
    assert "## Verdict: the signal not enough data" in bt.render(synthetic_rows(lambda i: i, n=2), [])


def test_past_entrants_finished_their_outcome_window_by_t():
    t = M("2020-01")
    games = [(game(1), hist(("2016-06", 600, 0))),  # released 43 months before T: known at T
             (game(2), hist(("2018-06", 600, 0)))]  # 19 months before: its outcome runs past T
    row = bt.tag_row("X", games, t)
    assert (row.past.entrants, row.past.hits) == (1, 1)
    assert (row.before.entrants, row.before.hits) == (1, 1)


def test_a_candidate_must_hold_on_the_check_cutoffs():
    def rows(hits_for, cutoffs=("2019-01", "2020-01", "2021-01", "2022-01")):
        out = []
        for t in cutoffs:
            for r in synthetic_rows(hits_for):
                r.t = M(t)
                r.market = r.market.model_copy(update={"n_underserved": int(r.tag[1:])})
                out.append(r)
        return out
    measure = bt.CANDIDATES["underserved games"]
    recent = rows(lambda i: 5 + i, bt.RECENT_CUTOFFS)
    assert bt.candidate("underserved games", measure, rows(lambda i: 5 + i), recent).passed
    assert not bt.candidate("underserved games", measure, rows(lambda i: 5 + i)).passed  # no recent rows
    assert not bt.candidate("underserved games", measure, rows(lambda i: 5 + i),
                            rows(lambda i: 30 - i, bt.RECENT_CUTOFFS)).passed  # reversed lately
    assert not bt.candidate("underserved games", measure, rows(lambda i: 40 + i // 4), recent).passed  # too small
    flat = bt.candidate("underserved games", measure, rows(lambda i: 20), recent)
    assert not flat.passed and flat.check[0] != flat.check[0]  # no variation: NaN
    text = bt.render(rows(lambda i: 5 + i), [], recent)
    assert "| underserved games |" in text and "## Recent check (2023-01, 2024-01" in text


def test_recent_rows_use_12_month_windows():
    t = M("2023-01")
    games = [(game(1), hist(("2023-06", 300, 0), ("2024-03", 300, 0))),  # 600 in its first 12 months
             (game(2), hist(("2023-06", 300, 0), ("2024-09", 300, 0))),  # only 300 within 12 months
             (game(3), hist(("2024-02", 600, 0)))]  # released 13 months after T: not an entrant
    row = bt.tag_row("X", games, t, 12, 12)
    assert (row.after.entrants, row.after.hits) == (2, 1)
