"""summary.py (opportunity summary by a local LLM), with Ollama faked: no network, no GPU."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from market_researcher import config, pipeline, summary
from market_researcher.market import MarketStats
from market_researcher.mining import llm
from market_researcher.models import GameSummary, OpportunitySummary, OtherComplaint, Review, SummaryPoint
from market_researcher.pipeline import TagResult
from market_researcher.report import render
from market_researcher.runs import ADAPTERS, RunStore
from market_researcher.web import server
from test_llm import fake_ollama
from test_m4 import analysis, flag
from test_web import wait

NAMES = ["Bus Sim", "Forest Ranger Simulator", "Cinema Tycoon"]


def answer(body):
    return {
        "pitch": "Players want a calm job sim that works.",
        "loved": [{"text": "Driving the bus.", "games": ["bus sim"]},  # case differs: still matched
                  {"text": "Made up.", "games": ["Not A Game We Analyzed"]}],  # no real game: dropped
        "complaints": [{"text": "Bugs.", "games": ["Bus Sim", "Forest Ranger", "Imaginary"]}],
        "build": [{"text": "Autosave often.", "games": []}],  # rests on no game: dropped
        "caveats": [{"text": "Small market.", "games": []}],  # a caveat may be about the whole tag
    }


def test_parse_keeps_only_points_about_analyzed_games():
    s = summary.parse(json.dumps(answer(None)), NAMES)
    assert s.pitch == "Players want a calm job sim that works."
    assert [(p.text, p.games) for p in s.loved] == [("Driving the bus.", ["Bus Sim"])]
    assert s.complaints[0].games == ["Bus Sim", "Forest Ranger Simulator"]  # a unique partial name counts
    assert s.build == [] and s.caveats[0].games == []


def test_evidence_reads_the_ranked_games_only():
    dlc = analysis(90, "Some DLC", [flag("not_game", "high")], appid=9)
    games = [analysis(60 - i, f"Game {i}", appid=i + 1) for i in range(config.SUMMARY_GAMES + 2)]
    m = MarketStats(n_games=50, n_demand=20, n_underserved=8, n_well_served=4, median_rating=60,
                    underserved_gross=1e6, gap=8 / 12)
    text, names = summary.evidence("Job Simulator", games + [dlc], m)
    assert names == [f"Game {i}" for i in range(config.SUMMARY_GAMES)]  # top N by score, DLC excluded
    assert "Some DLC" not in text and "Whole tag: 50 games" in text and "# Tag: Job Simulator" in text


def test_write_asks_the_model_in_the_interface_language():
    requests = []
    s = summary.write("Job Simulator", [analysis(60, "Bus Sim")], None, "tr",
                      client=fake_ollama(answer, requests))
    assert s.loved[0].games == ["Bus Sim"] and s.model == config.LLM_MODEL
    body = requests[0]
    assert "Turkish" in body["messages"][0]["content"] and body["options"]["num_ctx"] == config.SUMMARY_CTX
    assert body["format"]["required"] == ["pitch", "loved", "complaints", "build", "caveats"]


def test_missing_model_names_the_pull_command():
    with pytest.raises(llm.LLMUnavailable) as e:
        summary.write("X", [analysis(60, "Bus Sim")], None, "en", client=fake_ollama(None, status=404))
    assert e.value.missing_model == config.LLM_MODEL


def sample() -> OpportunitySummary:
    return OpportunitySummary(pitch="A calm bus sim that works.", model="gemma3:12b",
                              loved=[SummaryPoint(text="Driving | the bus.", games=["Bus Sim"])],
                              caveats=[SummaryPoint(text="Small market.", games=[])])


def report(**kw) -> str:
    return render(tag="Job Simulator", analyses=[analysis(60, "Bus Sim")], n_candidates=1, n_tag_games=5,
                  min_reviews=50, lo=5, hi=70, not_games=[], unlisted=[], **kw)


def test_report_section_only_with_a_summary():
    assert "Opportunity summary" not in report()
    text = report(summary=sample())
    assert "## Opportunity summary" in text and "**A calm bus sim that works.**" in text
    assert "- Driving \\| the bus. *(Bus Sim)*" in text  # escaped for the Markdown table syntax
    assert "### Shared complaints" not in text  # empty sections are left out


def test_update_result_keeps_the_run_time_and_old_runs_still_load(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    result = TagResult(n_tag_games=5, candidates=[], analyses=[analysis(60, "Bus Sim")])
    params = dict(tags=["Job Simulator"], min_reviews=50, lo=5, hi=70)
    run_id = store.save("tag", "Job Simulator", params, result)
    before = store.list()[0]["created"]
    result.summaries["en"] = sample()
    assert store.update_result(run_id, result) and not store.update_result("nope", result)
    assert store.list()[0]["created"] == before
    assert store.load(run_id)["result"].summaries["en"].pitch == "A calm bus sim that works."

    old = json.loads(ADAPTERS["tag"].dump_json(result))
    del old["summaries"]  # saved before summaries existed
    assert ADAPTERS["tag"].validate_json(json.dumps(old)).summaries == {}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_runs", RunStore(tmp_path / "runs.sqlite"))
    monkeypatch.setattr(server, "_jobs", {})
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: TagResult(
        n_tag_games=5, candidates=[], analyses=[analysis(60, "Bus Sim")]))
    return TestClient(server.app)


def test_summary_endpoint_writes_once_per_language_and_saves(client, monkeypatch):
    calls = []

    def fake_write(tag, analyses, market, lang, **kw):
        calls.append(lang)
        return sample()

    monkeypatch.setattr(server.summary, "write", fake_write)
    run_id = client.post("/api/tag-runs", json={"tags": ["Job Simulator"]}).json()["id"]
    assert wait(client, run_id)["result"]["summary"] is None

    first = client.post(f"/api/tag-runs/{run_id}/summary").json()["summary"]
    again = client.post(f"/api/tag-runs/{run_id}/summary").json()["summary"]
    assert first == again and first["pitch"] == "A calm bus sim that works." and calls == ["en"]
    client.post(f"/api/tag-runs/{run_id}/summary", headers={"X-Lang": "tr"})
    assert calls == ["en", "tr"]  # each language is written once

    monkeypatch.setattr(server, "_jobs", {})  # restart: the summary was saved with the run
    assert client.get(f"/api/tag-runs/{run_id}").json()["result"]["summary"]["pitch"] == first["pitch"]
    assert "## Opportunity summary" in client.get(f"/api/tag-runs/{run_id}/report.md").text


def test_summary_endpoint_explains_a_stopped_ollama(client, monkeypatch):
    def down(*a, **kw):
        raise llm.LLMUnavailable("Ollama isn't running")

    monkeypatch.setattr(server.summary, "write", down)
    run_id = client.post("/api/tag-runs", json={"tags": ["Job Simulator"]}).json()["id"]
    wait(client, run_id)
    res = client.post(f"/api/tag-runs/{run_id}/summary", headers={"X-Lang": "tr"})
    assert res.status_code == 503 and res.json()["notice"]["title"] == "Ollama çalışmıyor"
    assert client.get(f"/api/tag-runs/{run_id}").json()["result"]["summary"] is None


def test_summary_of_unknown_run_is_404(client):
    assert client.post("/api/tag-runs/nope/summary").status_code == 404


def test_report_names_the_penalties_of_a_penalized_game():
    a = analysis(40, "Old Sim", [flag("fading_demand", "medium")])
    a.opportunity.penalty, a.opportunity.penalized = 10, ["fading_demand"]
    assert ", penalty -10 (fading_demand)." in render(
        tag="X", analyses=[a], n_candidates=1, n_tag_games=1, min_reviews=50, lo=5, hi=70, not_games=[], unlisted=[])


# ---------- one game (write_game) ----------
def review(text, votes=0):
    return Review(recommendation_id=text[:10], text=text, voted_up=False, votes_up=votes)


NEGATIVE = [review("The game crashes every ten minutes, constant bugs.", 50),  # a category matches: not sent
            review("Way too expensive for what it is, and the DLC policy is greedy.", 5),
            review("Servers drop every single match and nobody fixes them.", 30),
            review("meh")]  # too short to say anything


def game_answer(body):
    return {"why": "It costs too much and the servers drop matches.",
            "fix": ["Fair price", " ", "Stable servers from day one"],
            "other": [{"text": "Server drops", "quote": "servers drop every single match"},
                      {"text": "Bad music", "quote": "the music is awful"}]}  # not in any review: dropped


def test_game_evidence_sends_only_reviews_no_category_matched():
    text, texts = summary.game_evidence(analysis(60, "Bus Sim"), NEGATIVE)
    assert texts[0].startswith("servers drop every") and len(texts) == 2  # most helpful first
    assert "crashes every ten minutes" not in text and "## Bus Sim" in text and "# Part 2: 2 negative" in text


def test_write_game_keeps_only_grounded_other_complaints():
    requests = []
    s = summary.write_game(analysis(60, "Bus Sim"), NEGATIVE, "tr", client=fake_ollama(game_answer, requests))
    assert s.why.startswith("It costs") and s.fix == ["Fair price", "Stable servers from day one"]
    assert [(o.text, o.quote) for o in s.other] == [("Server drops", "servers drop every single match")]
    assert s.n_uncovered == 2 and s.model == config.LLM_MODEL
    assert "Turkish" in requests[0]["messages"][0]["content"]
    assert requests[0]["format"]["required"] == ["why", "fix", "other"]


def game_sample() -> GameSummary:
    return GameSummary(why="Cheaters | everywhere.", fix=["Anti-cheat"], model="gemma3:12b",
                       other=[OtherComplaint(text="Cheaters", quote="cheaters in every match")])


def test_report_shows_a_written_game_summary():
    assert "Read by the local model" not in report()
    text = report(game_summaries={1: game_sample()})
    assert "### Read by the local model" in text and "Cheaters \\| everywhere." in text
    assert '- Cheaters *"cheaters in every match"*' in text


def test_game_summary_endpoint_writes_once_and_saves(client, monkeypatch):
    calls = []

    def fake_write_game(a, negative, lang, **kw):
        calls.append((a.game.appid, len(negative), lang))
        return game_sample()

    monkeypatch.setattr(server.summary, "write_game", fake_write_game)
    monkeypatch.setattr(server.pipeline, "review_sample", lambda http, appid, kind, limit: NEGATIVE[:limit])
    run_id = client.post("/api/tag-runs", json={"tags": ["Job Simulator"], "reviews": 10}).json()["id"]
    game = wait(client, run_id)["result"]["games"][0]
    assert game["summary"] is None
    appid = game["game"]["appid"]

    first = client.post(f"/api/tag-runs/{run_id}/games/{appid}/summary").json()["summary"]
    client.post(f"/api/tag-runs/{run_id}/games/{appid}/summary")
    assert first["why"] == "Cheaters | everywhere." and calls == [(appid, 4, "en")]
    assert client.post(f"/api/tag-runs/{run_id}/games/999/summary").status_code == 404

    monkeypatch.setattr(server, "_jobs", {})  # restart: saved with the run
    assert client.get(f"/api/tag-runs/{run_id}").json()["result"]["games"][0]["summary"]["why"] == first["why"]
    assert "### Read by the local model" in client.get(f"/api/tag-runs/{run_id}/report.md").text
    assert client.get(f"/api/tag-runs/{run_id}", headers={"X-Lang": "tr"}).json()["result"]["games"][0]["summary"] is None
