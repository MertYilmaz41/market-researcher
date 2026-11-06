"""The keyword miner, scored against hand-labeled real reviews (see mining/evaluate.py).

Floors sit just under the measured scores, so a lexicon change that makes the miner worse fails here.
Measured Nov 2026 (precision / recall over complaint categories):
  tuning set   (153 reviews, 9 games): before tuning 79% / 54%, after 90% / 87%
  held-out set (47 reviews, 6 other games, never tuned on): before 86% / 53%, after 86% / 62%
After 12 "content" labels were corrected by a blind human check: tuning 90% / 86%, held-out 83% / 62%.
holdout2 (73 sure reviews, 6 more games, labeled by the user, never tuned on): 78% / 63%.
After tuning on the Claude-labeled set (40 of its 50 games): tuning 90% / 86%, held-out 85% / 62%,
holdout2 77% / 65%; idea praise recall on holdout2 31% -> 50%.
"""

import pytest

from steam_researcher.mining.evaluate import FIXTURE, FIXTURES, HOLDOUT, IDEA, evaluate, load

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
    from steam_researcher.mining.evaluate import detect

    assert "bugs" not in detect("I turned too far and crashed into a tree.")
    assert "bugs" in detect("The game crashed twice in an hour.")
    assert "performance" in detect("There is next to no optimization at all.")


def test_patterns_from_the_claude_labeled_set():
    from steam_researcher.mining.evaluate import detect

    assert "abandoned" in detect("They removed multiplayer from the game.")
    assert "abandoned" in detect("The official servers were shut down last year.")
    assert IDEA in detect("The game is really fun, but it crashes all the time.")
    assert IDEA not in detect("The game is not fun at all.")
    assert "controls" not in detect("The controls feel great, the story does not.")
    assert "ui_ux" in detect("The English translation is half baked.")
