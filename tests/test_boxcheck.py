import datetime as dt

from market_researcher import boxcheck as b
from market_researcher.models import HistPoint


def ts(day: str) -> int:
    return b.timestamp(day)


def test_reviews_at_interpolates_the_current_month():
    hist = [HistPoint(date=ts("2024-01-01"), up=100, down=0), HistPoint(date=ts("2024-02-01"), up=60, down=2)]
    assert b.reviews_at(hist, ts("2024-01-01")) == 0
    assert b.reviews_at(hist, ts("2024-02-01")) == 100
    assert abs(b.reviews_at(hist, ts("2024-01-16")) - 100 * 15 / 31) < 0.01
    assert b.reviews_at(hist, ts("2025-01-01")) == 162  # the last period lasts at most a month


def item(appid, units, reviews, released=2022, price=15.0, steam_only=True):
    return b.Item(appid, str(appid), units, reviews, released, price, steam_only, False)


def test_scored_and_split():
    assert not item(10, 100, 5).scored  # too few reviews
    assert not item(10, 1000, 50, steam_only=False).scored  # other stores counted
    assert item(20, 1000, 50).fitting and not item(30, 1000, 50).fitting  # AppIDs are multiples of 10


def test_error_is_symmetric():
    assert b.error(90, 45) == b.error(45, 90) == 2


def test_a_rule_that_fits_the_data_is_adopted():
    # copies per review: cheap games 20x, the rest 80x; x45 is off by ~2x for all of them
    rows = [item(10 * i, (20 if i % 4 < 2 else 80) * 100, 100, price=5 if i % 4 < 2 else 20) for i in range(1, 17)]
    res = b.compare(rows)
    adopted = [name for name, (_, _, ok) in res.items() if ok]
    assert adopted == [name for name in b.RULES if name.startswith("D.")]


def test_disclosures_fixture_is_well_formed():
    rows = b.load()
    assert len({r["appid"] for r in rows}) == len(rows)
    for r in rows:
        assert r["units"] > 0 and r["source"].startswith("http"), r["name"]
        assert dt.date.fromisoformat(r["as_of"]) < dt.date(2027, 1, 1), r["name"]


def test_small_games_test_needs_enough_new_small_games():
    few = b.SmallTest(new_small=[10, 12, 14], large=[50, 60], rule_e=True)
    assert not few.holds
    enough = b.SmallTest(new_small=[10] * 8, large=[50, 60], rule_e=True)
    assert enough.holds
    assert not b.SmallTest(new_small=[10] * 8, large=[50, 60], rule_e=False).holds
    assert not b.SmallTest(new_small=[70] * 8, large=[50, 60], rule_e=True).holds
