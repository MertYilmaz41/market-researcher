"""The keyword miner, scored against hand-labeled real reviews (see mining/evaluate.py).

Floors sit just under the measured scores, so a lexicon change that makes the miner worse fails here.
Measured Nov 2026 (precision / recall over complaint categories):
  tuning set   (153 reviews, 9 games): before tuning 79% / 54%, after 90% / 87%
  held-out set (47 reviews, 6 other games, never tuned on): before 86% / 53%, after 86% / 62%
After 12 "content" labels were corrected by a blind human check: tuning 90% / 86%, held-out 83% / 62%.
holdout2 (73 sure reviews, 6 more games, labeled by the user, never tuned on): 78% / 63%.
After tuning on the Claude-labeled set (40 of its 50 games): tuning 90% / 86%, held-out 85% / 62%,
holdout2 77% / 65%; idea praise recall on holdout2 31% -> 50%.
After the bait-and-switch rule (6 reviews relabeled abandoned by the user): tuning 90% / 85%, held-out 85% / 60%,
holdout2 77% / 65%.
"""

import pytest

from market_researcher.mining.evaluate import FIXTURE, FIXTURES, HOLDOUT, IDEA, evaluate, load

HOLDOUT2 = FIXTURES / "labeled_reviews_holdout2.jsonl"


@pytest.mark.parametrize("path, precision, recall, idea", [(FIXTURE, 0.88, 0.84, 0.80), (HOLDOUT, 0.83, 0.60, 0.80),
                                                         (HOLDOUT2, 0.75, 0.63, 0.45)])
def test_complaint_detection_stays_accurate(path, precision, recall, idea):
    scores, total = evaluate(load(path))
    assert total.precision >= precision and total.recall >= recall, f"{total.precision:.0%} / {total.recall:.0%}"
    assert scores[IDEA].recall >= idea


def test_each_common_category_is_usable():
    scores, _ = evaluate(load(FIXTURE))
    for code, s in scores.items():
        if s.tp + s.fn >= 10:  # enough labeled examples to judge
            assert s.precision >= 0.80 and s.recall >= 0.55, f"{code}: {s.precision:.0%} / {s.recall:.0%}"


def test_driving_crash_is_not_a_bug():
    from market_researcher.mining.evaluate import detect

    assert "bugs" not in detect("I turned too far and crashed into a tree.")
    assert "bugs" in detect("The game crashed twice in an hour.")
    assert "performance" in detect("There is next to no optimization at all.")


def test_patterns_from_the_claude_labeled_set():
    from market_researcher.mining.evaluate import detect

    assert "abandoned" in detect("They removed multiplayer from the game.")
    assert "abandoned" in detect("The official servers were shut down last year.")
    assert IDEA in detect("The game is really fun, but it crashes all the time.")
    assert IDEA not in detect("The game is not fun at all.")
    assert "controls" not in detect("The controls feel great, the story does not.")
    assert "ui_ux" in detect("The English translation is half baked.")
    assert "abandoned" in detect("Why would they remove multiplayer? It was fun with friends, but it's gone now.")
    assert "abandoned" in detect("If companies can terminate a game at anytime, I should get a refund.")
    assert "abandoned" in detect("Don't buy it, it'll be shut down in 8 months.")
    assert "abandoned" in detect("Complete lack of developers response on the forums.")
    assert "abandoned" not in detect("The game terminated unexpectedly twice.")
    assert "abandoned" in detect("Classic bait and switch, this is not an MMO at all.")
    assert "abandoned" not in detect("False advertising, terrible game.")  # says nothing about what is missing


def test_game_level_comparison():
    from market_researcher.mining.evaluate import games

    rows = [
        {"appid": 1, "playtime_minutes": 600, "text": "Crashes constantly, lots of bugs.", "labels": ["bugs"]},
        {"appid": 1, "playtime_minutes": 600, "text": "Buggy and the devs abandoned it.", "labels": ["bugs", "abandoned"]},
        {"appid": 1, "playtime_minutes": 30, "text": "So little to do here.", "labels": ["content"]},
        {"appid": 2, "playtime_minutes": 600, "text": "Nothing wrong, just not for me.", "labels": []},
    ]
    found = [{"bugs"}, {"bugs"}, {"content", IDEA}, set()]
    g1, g2 = games(rows, found)
    assert g1.labeled["bugs"] == g1.found["bugs"] == 2 / 2.5  # the short-playtime review counts half
    assert g1.labeled["abandoned"] == 1 / 2.5 and g1.found["abandoned"] == 0
    assert g1.top_agrees and g1.top3_overlap == 2 / 3
    assert g1.fixability == (1.0, 1.0)
    assert g2.fixability == (None, None) and not g2.top_agrees
