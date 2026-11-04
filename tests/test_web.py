import time

import pytest
from fastapi.testclient import TestClient

from steam_researcher import notices, pipeline
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
    started = client.post("/api/tag-runs", json={"tag": "Job Simulator", "lo": 10, "hi": 60}).json()
    assert started["notices"] == []  # sensible filters: no pre-run warnings
    run_id = started["id"]
    job = wait(client, run_id)
    assert job["status"] == "done" and job["error"] is None
    res = job["result"]
    assert [g["game"]["name"] for g in res["games"]] == ["Best Sim", "Other"]  # ranked, DLC excluded
    g = res["games"][0]
    assert g["store_url"].endswith("/app/1/") and g["box"]["gross_mid"] > 0
    assert g["mining"]["categories"][0]["code"] == "bugs" and g["has_histogram"] is True
    assert res["not_games"] == ["Soundtrack (music)"] and res["n_tag_games"] == 50
    assert any(n["level"] == "success" and "Best Sim" in n["message"] for n in res["notices"])
    assert calls[0][0] == "Job Simulator" and calls[0][1][1:3] == (10, 60)

    md = client.get(f"/api/tag-runs/{run_id}/report.md")
    assert md.status_code == 200 and md.text.startswith("# Underserved Audience Report: Job Simulator")
    assert 'filename="job-simulator.md"' in md.headers["content-disposition"]


def test_unknown_tag_is_error(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: None)
    monkeypatch.setattr(notices, "known_tags", lambda http: [])  # no network in tests
    job = wait(client, client.post("/api/tag-runs", json={"tag": "Nope"}).json()["id"])
    assert job["status"] == "error" and job["error"]["title"] == "Tag not found"
    assert "Job Simulator" in job["error"]["hint"]  # tells the user what to type instead


def test_pipeline_exception_is_reported(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("SteamSpy down")

    monkeypatch.setattr(pipeline, "run_tag", boom)
    job = wait(client, client.post("/api/tag-runs", json={"tag": "X"}).json()["id"])
    assert job["status"] == "error" and "SteamSpy down" in job["error"]["message"]


@pytest.mark.parametrize("body", [{"tag": "X", "lo": 80, "hi": 20}, {"tag": "X", "hi": 101}, {"tag": ""}])
def test_invalid_request_422(client, body):
    assert client.post("/api/tag-runs", json=body).status_code == 422


def test_unknown_run_404(client):
    assert client.get("/api/tag-runs/nope").status_code == 404


def test_game_endpoint(client, monkeypatch):
    monkeypatch.setattr(pipeline, "analyze_game", lambda http, appid, n: analysis(42, "Solo", appid=appid) if appid == 5 else None)
    ok = client.get("/api/games/5")
    assert ok.status_code == 200 and ok.json()["game"]["name"] == "Solo"
    assert isinstance(ok.json()["notices"], list)
    missing = client.get("/api/games/6")
    assert missing.status_code == 404 and missing.json()["notice"]["title"] == "Game not found"


def test_pre_run_notices(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: fake_result())
    body = {"tag": "X", "min_reviews": 20, "lo": 0, "hi": 90, "max_games": 50, "reviews": 500}
    titles = {n["title"] for n in client.post("/api/tag-runs", json=body).json()["notices"]}
    assert titles == {"Demand not proven", "Above 70% isn't underserved", "Very low ratings included",
                      "This may take a while"}


def test_validation_message_is_readable(client):
    res = client.post("/api/tag-runs", json={"tag": "X", "lo": 80, "hi": 20})
    assert res.status_code == 422
    assert "'% positive from' must not be higher than '% positive to'" in res.json()["detail"]
    res = client.post("/api/tag-runs", json={"tag": "X", "max_games": 99})
    assert res.json()["detail"].startswith("Games to analyze:")


def test_game_network_error_is_friendly(client, monkeypatch):
    import httpx

    def down(*a):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "https://steamspy.com/api.php"))

    monkeypatch.setattr(pipeline, "analyze_game", down)
    res = client.get("/api/games/5")
    assert res.status_code == 502 and res.json()["notice"]["title"] == "Can't reach steamspy.com"


def test_lost_run_message(client):
    assert "restarted" in client.get("/api/tag-runs/nope").json()["detail"]


def test_tags_endpoint(client, monkeypatch):
    from steam_researcher.web import server

    monkeypatch.setattr(server.steam_store, "tag_names", lambda http: ["Colony Sim", "Job Simulator"])
    assert client.get("/api/tags").json() == {"tags": ["Colony Sim", "Job Simulator"]}

    def down(http):
        raise RuntimeError("https://api.steampowered.com/x redirected to '/'; endpoint unavailable")

    monkeypatch.setattr(server.steam_store, "tag_names", down)
    res = client.get("/api/tags")
    assert res.status_code == 502 and res.json()["notice"]["title"] == "Unexpected answer from api.steampowered.com"
