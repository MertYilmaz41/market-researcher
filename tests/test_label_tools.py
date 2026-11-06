"""scripts/label_server.py and scripts/label_agreement.py (labeling tools for the review fixtures)."""

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import label_agreement  # noqa: E402
import label_server  # noqa: E402

ROWS = [{"id": str(i), "appid": i % 3, "text": f"review {i}", "labels": ["bugs"], "idea_praise": False}
        for i in range(12)]


def test_page_hides_the_input_labels_and_saves_each_answer(tmp_path):
    out = tmp_path / "out.jsonl"
    client = TestClient(label_server.make_app(ROWS[:3], out))
    data = client.get("/api/items").json()
    assert data["items"][0] == {"id": "0", "text": "review 0"}  # no labels: the check is blind
    assert "Az içerik / sığ ilerleme" in [c["name"] for c in data["categories"]]
    assert "<title>" in client.get("/").text

    client.post("/api/answer", json={"id": "1", "labels": ["content", "made_up"], "idea_praise": True})
    client.post("/api/answer", json={"id": "0", "labels": ["bugs"], "unsure": True})
    client.post("/api/answer", json={"id": "1", "labels": ["performance"]})  # back and changed
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [(r["id"], r["labels"], r["idea_praise"], r["unsure"]) for r in rows] == [
        ("0", [], False, True), ("1", ["performance"], False, False)]  # input order, unknown codes dropped

    again = TestClient(label_server.make_app(ROWS[:3], out)).get("/api/items").json()
    assert again["answers"]["1"]["labels"] == ["performance"]  # reopening keeps the answers


def test_sample_spreads_over_games_and_is_repeatable():
    picked = label_server.pick(ROWS, 6)
    assert sorted(r["appid"] for r in picked) == [0, 0, 1, 1, 2, 2]
    assert picked == label_server.pick(ROWS, 6) and len(label_server.pick(ROWS, None)) == 12


def test_agreement_counts_per_category_and_skips_unsure(tmp_path):
    first, ref = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    first.write_text("\n".join(json.dumps(r) for r in [
        {"id": 1, "labels": ["bugs", "content"]}, {"id": 2, "labels": [], "idea_praise": True},
        {"id": 3, "labels": ["bugs"]}]), encoding="utf-8")
    ref.write_text("\n".join(json.dumps(r) for r in [
        {"id": 1, "labels": ["bugs"]}, {"id": 2, "labels": ["abandoned"], "idea_praise": True},
        {"id": 3, "labels": [], "unsure": True}]), encoding="utf-8")
    counts, n = label_agreement.agreement(label_agreement.load(first), label_agreement.load(ref))
    assert n == 2
    assert counts["bugs"] == (1, 0, 0) and counts["content"] == (0, 1, 0) and counts["abandoned"] == (0, 0, 1)
    assert counts["idea_praise"] == (1, 0, 0)
    assert label_agreement.f1(1, 1, 1) == 0.5
