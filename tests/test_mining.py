import pytest

from steam_researcher import risk
from steam_researcher.mining import mine
from steam_researcher.mining.keywords import clean, core_phrases


def rev(text, up=False, votes=0, i=[0]):
    from steam_researcher.models import Review

    i[0] += 1
    return Review(recommendation_id=str(i[0]), text=text, voted_up=up, votes_up=votes)


def codes(result):
    return {c.code: c.count for c in result.categories}


def test_categories_detected():
    neg = [
        rev("The controls are clunky and the camera is awful."),
        rev("So buggy. It crashed twice and I lost my progress."),
        rev("Confusing menus, no explanation of anything."),
        rev("Gets repetitive fast, nothing to do after 2 hours."),
        rev("Terrible performance, constant stutter."),
        rev("Devs abandoned it, no updates for years."),
        rev("This is nowhere near a simulator, totally arcadey."),
    ]
    got = codes(mine(neg, []))
    for code in ["controls", "bugs", "ui_ux", "content", "performance", "abandoned", "realism"]:
        assert got.get(code, 0) >= 1, code


def test_negated_bugs_not_counted():
    got = codes(mine([rev("Not buggy at all, never crashed, but it is boring.")], []))
    assert "bugs" not in got and got["content"] == 1


def test_negation_does_not_hide_content_complaint():
    # "not enough content" IS a complaint even though it contains "not"
    assert codes(mine([rev("There is not enough content here.")], []))["content"] == 1


def test_category_counted_once_per_review():
    assert codes(mine([rev("bug bug bug, crash, glitch, broken")], []))["bugs"] == 1


def test_quote_contains_match_and_prefers_helpful():
    long = "word " * 80 + "the game is buggy beyond belief " + "word " * 80
    m = mine([rev("buggy mess everywhere here", votes=1), rev(long, votes=50)], [])
    bugs = next(c for c in m.categories if c.code == "bugs")
    assert "buggy" in bugs.quotes[0] and len(bugs.quotes[0]) <= 230  # helpful review first, windowed


def test_idea_praise_and_fixability():
    neg = [rev("Great concept but buggy."), rev("Had so much potential."), rev("Just bad, like GTA but worse.")]
    m = mine(neg, [])
    assert round(m.idea_praise_share, 2) == 0.67
    assert 0 < m.fixability < 1  # scope complaint is not fixable


def test_scope_flag_threshold():
    neg = [rev("Wanted GTA in a bus.")] + [rev("boring")] * 4
    assert risk.check_scope(mine(neg, []))[0].code == "scope_unrealistic"
    neg = [rev("Wanted GTA in a bus.")] + [rev("boring")] * 20
    assert risk.check_scope(mine(neg, [])) == []


def test_clean_strips_bbcode_and_urls():
    assert clean("[b]Hi[/b] https://youtube.com/x").split() == ["hi"]


def test_core_phrases_skip_generic():
    pos = ["I love the power washer, great game"] * 5 + ["power washer is fun"] * 3
    phrases = dict(core_phrases(pos))
    assert phrases.get("power washer") == 8
    assert "great game" not in phrases


def test_liked_capture():
    pos = ["I loved the duck hunting. Cool"] * 3
    assert mine([], [rev(t, up=True) for t in pos]).liked[0] == ("duck hunting", 3)


# --- review sample: playtime weights, recent complaints ----------------------------------------

def timed(text, playtime=0, timestamp=0, i=[1000]):
    from steam_researcher.models import Review

    i[0] += 1
    return Review(recommendation_id=str(i[0]), text=text, voted_up=False, playtime_minutes=playtime, timestamp=timestamp)


def test_short_playtime_reviews_count_half():
    # one bug review after 10 minutes, one boring review after 50 hours
    m = mine([timed("It crashed.", playtime=10), timed("So boring.", playtime=3000)], [])
    share = {c.code: c.share for c in m.categories}
    assert share["bugs"] == pytest.approx(0.5 / 1.5) and share["content"] == pytest.approx(1 / 1.5)
    assert [c.code for c in m.categories] == ["content", "bugs"]  # sorted by weighted share
    assert {c.code: c.count for c in m.categories} == {"content": 1, "bugs": 1}  # counts stay raw


def test_recent_share_and_trend():
    now = 2_000_000_000
    old, new = now - 3 * 365 * 86400, now - 30 * 86400
    neg = ([timed("Crashes all the time.", timestamp=old)] * 10
           + [timed("Boring and repetitive.", timestamp=new)] * 10)
    m = mine(neg, [], now=now)
    by = {c.code: c for c in m.categories}
    assert m.n_recent_negative == 10
    assert by["bugs"].recent_share == 0 and by["bugs"].trend == "rarely mentioned lately"
    assert by["content"].recent_share == 1 and by["content"].trend == "still common lately"


def test_no_trend_with_few_recent_reviews():
    m = mine([timed("buggy", timestamp=0)] * 20 + [timed("buggy", timestamp=2_000_000_000)] * 3, [], now=2_000_000_000)
    assert m.categories[0].recent_share is None and m.categories[0].trend == ""
