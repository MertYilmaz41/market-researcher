import pytest

from steam_researcher import boxmethod
from steam_researcher.discover import filter_candidates, parse_rating_range
from steam_researcher.sources.steamspy import parse_tag_response

SAMPLE = {
    "1": {"appid": 1, "name": "Great Game", "positive": 900, "negative": 100, "price": "999", "initialprice": "999"},
    "2": {"appid": 2, "name": "Underserved Sim", "positive": 300, "negative": 300, "price": "499", "initialprice": "1999", "discount": "75"},
    "3": {"appid": 3, "name": "Tiny Game", "positive": 10, "negative": 40, "price": "0", "initialprice": "0"},
    "4": {"appid": 4, "name": "Awful Game", "positive": 20, "negative": 480, "price": "", "initialprice": None},
}


def test_box_method_guide_examples():
    # Guide: 100 reviews x 45 = 4,500 units -> $45k at $10; 900 reviews -> $405k
    assert boxmethod.estimate(100, 10).units_mid == 4_500
    assert boxmethod.estimate(100, 10).gross_mid == 45_000
    assert boxmethod.estimate(900, 10).gross_mid == 405_000
    est = boxmethod.estimate(100, 10)
    assert (est.gross_low, est.gross_high) == (30_000, 100_000)


def test_parse_and_filter():
    games = parse_tag_response(SAMPLE)
    assert len(games) == 4
    sim = next(g for g in games if g.appid == 2)
    assert sim.reviews == 600 and sim.rating == 50.0 and sim.base_price == 19.99

    hits = filter_candidates(games, min_reviews=100, min_rating=5, max_rating=70)
    # Great Game (90%) too positive, Tiny Game too few reviews, Awful Game 4% < 5%
    assert [g.appid for g in hits] == [2]


def test_filter_sorted_by_rating_ascending():
    games = parse_tag_response(SAMPLE)
    hits = filter_candidates(games, min_reviews=1, min_rating=0, max_rating=100)
    assert [round(g.rating) for g in hits] == sorted(round(g.rating) for g in hits)


def test_parse_rating_range():
    assert parse_rating_range("5-70") == (5.0, 70.0)


@pytest.mark.parametrize("bad", ["70", "a-b", "70-5", "-5-70", "5-101", ""])
def test_parse_rating_range_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_rating_range(bad)
