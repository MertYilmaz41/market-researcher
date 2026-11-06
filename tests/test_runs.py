from steam_researcher import runs
from steam_researcher.market import TagMarket, market_stats
from steam_researcher.pipeline import MarketsResult, TagResult
from steam_researcher.runs import RunStore

from test_m4 import analysis, game

PARAMS = {"tags": ["Crafting", "Survival"], "min_reviews": 100, "lo": 5, "hi": 70, "max_games": 15, "reviews": 200}


def test_tag_run_round_trip(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    result = TagResult(n_tag_games=9, candidates=[game()], analyses=[analysis(40, "A")],
                       failed=[("B", "timed out")], market=market_stats([game()], 100, 5, 70))
    run_id = store.save("tag", "Crafting + Survival", PARAMS, result)
    saved = store.load(run_id)
    assert saved["result"] == result and saved["params"] == PARAMS and saved["kind"] == "tag"
    assert store.list()[0] | {"created": 0} == {"id": run_id, "created": 0, "kind": "tag",
                                                  "label": "Crafting + Survival", "n": 1}
    assert store.delete(run_id) and store.load(run_id) is None and not store.delete(run_id)


def test_market_run_round_trip(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    result = MarketsResult(rows=[TagMarket(tag="Hot", stats=market_stats([game()], 100, 5, 70))], skipped=["Zoo"])
    run_id = store.save("market", "All tags", {"min_reviews": 100, "lo": 5, "hi": 70}, result)
    assert store.load(run_id)["result"] == result
    assert store.previous_scores(run_id) is None  # market runs aren't compared


def test_store_creates_no_file_until_used(tmp_path):
    RunStore(tmp_path / "sub" / "runs.sqlite")
    assert not (tmp_path / "sub").exists()


def test_compare_key_ignores_tag_order_and_case():
    assert runs.compare_key(["A", "b"], 100, 5, 70) == runs.compare_key(["B", "a"], 100, 5, 70)
    assert runs.compare_key(["A"], 100, 5, 70) != runs.compare_key(["A"], 100, 5, 60)
    assert runs.compare_key(["A"], 100, 5, 70, 200) != runs.compare_key(["A"], 100, 5, 70, 1000)


def test_changes():
    assert runs.changes({1: 50, 2: 10}, None) == {}
    assert runs.changes({1: 50, 2: 10}, {1: 40, 3: 9}) == {1: 10, 2: None}


def test_cli_runs_lists_saved_runs(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from steam_researcher import config
    from steam_researcher.cli import app

    monkeypatch.setattr(config, "RUNS_DB", tmp_path / "runs.sqlite")
    monkeypatch.setattr(RunStore.__init__, "__defaults__", (tmp_path / "runs.sqlite",))
    assert "No saved runs" in CliRunner().invoke(app, ["runs"]).output
    RunStore().save("tag", "Crafting", PARAMS | {"tags": ["Crafting"]}, TagResult(n_tag_games=1, candidates=[]))
    out = CliRunner().invoke(app, ["runs"]).output
    assert "Crafting" in out and "tag" in out


def test_shortlist_keeps_note_and_time_when_starred_again(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    store.star(1, {"name": "A", "score": 40})
    assert store.set_note(1, "worth a look")
    added = store.shortlist()[0]["added"]
    store.star(1, {"name": "A", "score": 55})  # starred again from a newer run
    assert store.shortlist() == [{"name": "A", "score": 55, "appid": 1, "added": added, "note": "worth a look"}]
    assert not store.set_note(2, "x") and not store.unstar(2)
    assert store.unstar(1) and store.shortlist() == []
    assert RunStore(tmp_path / "runs.sqlite").shortlist() == []  # a fresh store reads the same file
