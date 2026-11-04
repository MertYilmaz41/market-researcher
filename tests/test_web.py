import time

import pytest
from fastapi.testclient import TestClient

from steam_researcher import pipeline
from steam_researcher.models import HistPoint
from steam_researcher.pipeline import TagResult
from steam_researcher.web.server import app

from test_m4 import analysis, flag


@pytest.fixture
def client():
    return TestClient(app)


def wait(client, run_id):
    for _ in range(100):
        job = client.get(f"/api/tag-runs/{run_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def fake_result():
    best = analysis(60, "Best Sim", appid=1)
    best.histogram = [HistPoint(date=1_700_000_000, up=10, down=5)]
    dlc = analysis(90, "Some DLC", [flag("not_game", "high")], appid=3)
    return TagResult(n_tag_games=50, candidates=[best.game], analyses=[analysis(20, "Other", appid=2), best, dlc],
                     not_games=["Soundtrack (music)"])


def test_index_and_static(client):
    html = client.get("/")
    assert html.status_code == 200 and "map3d.js" not in html.text  # loaded by app.js
    assert "/static/app.js" in html.text and "three@0.170.0" in html.text
    for f in ["app.js", "map3d.js", "style.css"]:
        assert client.get(f"/static/{f}").status_code == 200


def test_tag_run_ranks_and_serializes(client, monkeypatch):
    calls = []

    def fake_run_tag(http, tag, *args):
        calls.append((tag, args))
        args[-1]("Analyzing Best Sim", 1, 2)  # progress callback works
        return fake_result()

    monkeypatch.setattr(pipeline, "run_tag", fake_run_tag)
    run_id = client.post("/api/tag-runs", json={"tag": "Job Simulator", "lo": 10, "hi": 60}).json()["id"]
    job = wait(client, run_id)
    assert job["status"] == "done" and job["error"] is None
    res = job["result"]
    assert [g["game"]["name"] for g in res["games"]] == ["Best Sim", "Other"]  # ranked, DLC excluded
    g = res["games"][0]
    assert g["store_url"].endswith("/app/1/") and g["box"]["gross_mid"] > 0
    assert g["mining"]["categories"][0]["code"] == "bugs" and g["has_histogram"] is True
    assert res["not_games"] == ["Soundtrack (music)"] and res["n_tag_games"] == 50
    assert calls[0][0] == "Job Simulator" and calls[0][1][1:3] == (10, 60)

    md = client.get(f"/api/tag-runs/{run_id}/report.md")
    assert md.status_code == 200 and md.text.startswith("# Underserved Audience Report: Job Simulator")
    assert 'filename="job-simulator.md"' in md.headers["content-disposition"]


def test_unknown_tag_is_error(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: None)
    job = wait(client, client.post("/api/tag-runs", json={"tag": "Nope"}).json()["id"])
    assert job["status"] == "error" and "No games found" in job["error"]


def test_pipeline_exception_is_reported(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("SteamSpy down")

    monkeypatch.setattr(pipeline, "run_tag", boom)
    job = wait(client, client.post("/api/tag-runs", json={"tag": "X"}).json()["id"])
    assert job["status"] == "error" and "SteamSpy down" in job["error"]


@pytest.mark.parametrize("body", [{"tag": "X", "lo": 80, "hi": 20}, {"tag": "X", "hi": 101}, {"tag": ""}])
def test_invalid_request_422(client, body):
    assert client.post("/api/tag-runs", json=body).status_code == 422


def test_unknown_run_404(client):
    assert client.get("/api/tag-runs/nope").status_code == 404


def test_game_endpoint(client, monkeypatch):
    monkeypatch.setattr(pipeline, "analyze_game", lambda http, appid, n: analysis(42, "Solo", appid=appid) if appid == 5 else None)
    ok = client.get("/api/games/5")
    assert ok.status_code == 200 and ok.json()["game"]["name"] == "Solo"
    assert client.get("/api/games/6").status_code == 404
