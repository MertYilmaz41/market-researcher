"""The keyword miner, scored against hand-labeled real reviews (see mining/evaluate.py).

Floors sit just under the measured scores, so a lexicon change that makes the miner worse fails here.
Measured Nov 2026 (precision / recall over complaint categories):
  tuning set   (153 reviews, 9 games): before tuning 79% / 54%, after 90% / 87%
  held-out set (47 reviews, 6 other games, never tuned on): before 86% / 53%, after 86% / 62%
"""

import pytest

from steam_researcher.mining.evaluate import FIXTURE, HOLDOUT, IDEA, evaluate, load


@pytest.mark.parametrize("path, precision, recall", [(FIXTURE, 0.88, 0.85), (HOLDOUT, 0.83, 0.60)])
def test_complaint_detection_stays_accurate(path, precision, recall):
    scores, total = evaluate(load(path))
    assert total.precision >= precision and total.recall >= recall, f"{total.precision:.0%} / {total.recall:.0%}"
    assert scores[IDEA].recall >= 0.80


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
