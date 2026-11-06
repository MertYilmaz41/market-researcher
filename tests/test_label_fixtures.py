"""The labeled review sets stay apart: Claude's training labels never share a game with a human-labeled set."""

import json
from pathlib import Path

from steam_researcher.mining.lexicon import CATEGORIES

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = FIXTURES / "claude_labeled_reviews.jsonl"
HUMAN = ["labeled_reviews.jsonl", "labeled_reviews_holdout.jsonl", "labeled_reviews_holdout2.jsonl",
         "labeled_reviews_holdout2.unlabeled.jsonl"]


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_claude_set_shares_no_game_or_review_with_human_sets():
    claude = rows(CLAUDE)
    games, ids = {r["appid"] for r in claude}, {str(r["id"]) for r in claude}
    for name in HUMAN:
        if (FIXTURES / name).exists():
            human = rows(FIXTURES / name)
            assert not games & {r["appid"] for r in human}, name
            assert not ids & {str(r["id"]) for r in human}, name


def test_claude_labels_use_known_codes():
    codes = {c.code for c in CATEGORIES}
    claude = rows(CLAUDE)
    assert len({str(r["id"]) for r in claude}) == len(claude)
    for r in claude:
        assert set(r["labels"]) <= codes and isinstance(r["idea_praise"], bool) and r["labeler"] == "claude", r["id"]


def test_evaluate_leaves_out_unsure_answers(tmp_path):
    from steam_researcher.mining import evaluate

    path = tmp_path / "x.jsonl"
    path.write_text('{"id": 1, "text": "a", "labels": []}\n{"id": 2, "text": "b", "labels": [], "unsure": true}\n',
                    encoding="utf-8")
    assert [r["id"] for r in evaluate.load(path)] == [1]
