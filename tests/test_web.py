import time

import pytest
from fastapi.testclient import TestClient

from steam_researcher import notices, pipeline
from steam_researcher.models import HistPoint
from steam_researcher.pipeline import TagResult
from steam_researcher.runs import RunStore
from steam_researcher.web import server
from steam_researcher.web.server import app

from test_m4 import analysis, flag


@pytest.fixture(autouse=True)
def run_store(tmp_path, monkeypatch):
    """Saved runs go to a temp DB, never the user's real one; jobs start from scratch."""
    store = RunStore(tmp_path / "runs.sqlite")
    monkeypatch.setattr(server, "_runs", store)
    monkeypatch.setattr(server, "_jobs", {})
    return store


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
    for f in ["app.js", "map2d.js", "map3d.js", "palette.js", "style.css"]:
        assert client.get(f"/static/{f}").status_code == 200


def test_tag_run_ranks_and_serializes(client, monkeypatch):
    calls = []

    def fake_run_tag(http, tag, *args):
        calls.append((tag, args))
        args[-1]("Analyzing Best Sim", 1, 2)  # progress callback works
        return fake_result()

    monkeypatch.setattr(pipeline, "run_tag", fake_run_tag)
    started = client.post("/api/tag-runs", json={"tags": ["Job Simulator"], "lo": 10, "hi": 60}).json()
    assert started["notices"] == []  # sensible filters: no pre-run warnings
    run_id = started["id"]
    job = wait(client, run_id)
    assert job["status"] == "done" and job["error"] is None
    res = job["result"]
    assert [g["game"]["name"] for g in res["games"]] == ["Best Sim", "Other"]  # ranked, DLC excluded
    g = res["games"][0]
    assert g["store_url"].endswith("/app/1/") and g["box"]["gross_mid"] > 0
    assert g["mining"]["categories"][0]["code"] == "bugs" and g["has_histogram"] is True
    assert [p["label"] for p in g["score_explained"]["parts"]] == ["Demand", "Dissatisfaction", "Fixability"]
    assert res["not_games"] == ["Soundtrack (music)"] and res["n_tag_games"] == 50
    assert any(n["level"] == "success" and "Best Sim" in n["message"] for n in res["notices"])
    assert calls[0][0] == ["Job Simulator"] and calls[0][1][1:3] == (10, 60)

    md = client.get(f"/api/tag-runs/{run_id}/report.md")
    assert md.status_code == 200 and md.text.startswith("# Underserved Audience Report: Job Simulator")
    assert 'filename="job-simulator.md"' in md.headers["content-disposition"]


def test_unknown_tag_is_error(client, monkeypatch):
    def unknown(*a):
        raise pipeline.UnknownTag("Nope")

    monkeypatch.setattr(pipeline, "run_tag", unknown)
    monkeypatch.setattr(notices, "known_tags", lambda http: [])  # no network in tests
    job = wait(client, client.post("/api/tag-runs", json={"tags": ["Crafting", "Nope"]}).json()["id"])
    assert job["status"] == "error" and job["error"]["title"] == "Tag not found"
    assert "Job Simulator" in job["error"]["hint"]  # tells the user what to type instead
    assert "'Nope'" in job["error"]["message"]  # names the bad tag, not the whole search


def test_pipeline_exception_is_reported(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("SteamSpy down")

    monkeypatch.setattr(pipeline, "run_tag", boom)
    job = wait(client, client.post("/api/tag-runs", json={"tags": ["X"]}).json()["id"])
    assert job["status"] == "error" and "SteamSpy down" in job["error"]["message"]


@pytest.mark.parametrize("body", [{"tags": ["X"], "lo": 80, "hi": 20}, {"tags": ["X"], "hi": 101}, {"tags": [""]},
                                  {"tags": []}, {"tags": list("ABCDEF")}, {"tag": "X"}])
def test_invalid_request_422(client, body):
    assert client.post("/api/tag-runs", json=body).status_code == 422


def test_multi_tag_run_uses_label(client, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_tag", lambda http, tags, *a: calls.append(tags) or fake_result())
    run_id = client.post("/api/tag-runs", json={"tags": ["Crafting", "Survival"]}).json()["id"]
    job = wait(client, run_id)
    assert calls == [["Crafting", "Survival"]]
    assert job["result"]["tag"] == "Crafting + Survival" and job["result"]["tags"] == ["Crafting", "Survival"]
    md = client.get(f"/api/tag-runs/{run_id}/report.md")
    assert md.text.startswith("# Underserved Audience Report: Crafting + Survival")
    assert 'filename="crafting-survival.md"' in md.headers["content-disposition"]


def test_too_many_tags_message(client):
    res = client.post("/api/tag-runs", json={"tags": list("ABCDEF")})
    assert res.status_code == 422 and res.json()["detail"].startswith("Steam tags:")


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
    body = {"tags": ["X"], "min_reviews": 20, "lo": 0, "hi": 90, "max_games": 50, "reviews": 500}
    titles = {n["title"] for n in client.post("/api/tag-runs", json=body).json()["notices"]}
    assert titles == {"Demand not proven", "Above 70% isn't underserved", "Very low ratings included",
                      "This may take a while"}


def test_validation_message_is_readable(client):
    res = client.post("/api/tag-runs", json={"tags": ["X"], "lo": 80, "hi": 20})
    assert res.status_code == 422
    assert "'% positive from' must not be higher than '% positive to'" in res.json()["detail"]
    res = client.post("/api/tag-runs", json={"tags": ["X"], "max_games": 99})
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


def test_market_run(client, monkeypatch):
    from steam_researcher.market import MarketStats, TagMarket

    stats = MarketStats(n_games=40, n_demand=10, n_underserved=4, n_well_served=2, median_rating=66,
                        underserved_gross=1e6, gap=4 / 6)

    def fake(http, min_reviews, lo, hi, step):
        step("Reading tag Hot", 1, 2)
        return pipeline.MarketsResult(rows=[TagMarket(tag="Hot", stats=stats)], failed=[("Broken", "down")],
                                      skipped=["Incremental"])

    monkeypatch.setattr(pipeline, "run_markets", fake)
    run_id = client.post("/api/market-runs", json={"min_reviews": 200}).json()["id"]
    for _ in range(100):
        job = client.get(f"/api/market-runs/{run_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.02)
    assert job["status"] == "done", job
    res = job["result"]
    assert res["rows"][0]["tag"] == "Hot" and res["rows"][0]["n_underserved"] == 4
    assert res["skipped"] == ["Incremental"] and res["failed"][0]["tag"] == "Broken"
    assert res["min_reviews"] == 200
    assert client.get(f"/api/tag-runs/{run_id}").status_code == 404  # not a tag run


def test_tag_run_includes_market_and_recent_reviews(client, monkeypatch):
    from steam_researcher.market import market_stats

    def fake_run_tag(http, tag, *args):
        r = fake_result()
        r.market = market_stats([r.analyses[0].game], 100, 5, 70)
        return r

    monkeypatch.setattr(pipeline, "run_tag", fake_run_tag)
    res = wait(client, client.post("/api/tag-runs", json={"tags": ["X"]}).json()["id"])["result"]
    assert res["market"]["n_games"] == 1 and res["well_served"] == 85
    best = res["games"][0]
    assert best["recent_reviews"] == 0 and best["recent_share"] == 0  # its only review month is old
    assert res["games"][1]["recent_share"] is None  # no histogram


# --- saved runs ---------------------------------------------------------------------------------

def test_finished_run_is_saved_and_survives_a_restart(client, monkeypatch, run_store):
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: fake_result())
    wait(client, client.post("/api/tag-runs", json={"tags": ["Job Simulator"]}).json()["id"])
    runs = client.get("/api/runs").json()["runs"]
    assert [(r["kind"], r["label"], r["n"]) for r in runs] == [("tag", "Job Simulator", 2)]
    run_id = runs[0]["id"]

    monkeypatch.setattr(server, "_jobs", {})  # "restart": only the saved copy is left
    job = client.get(f"/api/tag-runs/{run_id}").json()
    assert job["status"] == "done" and [g["game"]["name"] for g in job["result"]["games"]] == ["Best Sim", "Other"]
    assert client.get(f"/api/tag-runs/{run_id}/report.md").status_code == 200
    assert client.get(f"/api/market-runs/{run_id}").status_code == 404  # wrong kind

    assert client.delete(f"/api/runs/{run_id}").status_code == 200
    assert client.get("/api/runs").json()["runs"] == []
    assert client.get(f"/api/tag-runs/{run_id}").status_code == 404
    assert client.delete(f"/api/runs/{run_id}").status_code == 404


def test_rerun_shows_score_changes(client, monkeypatch):
    scores = iter([{1: 60, 2: 20}, {1: 55, 2: 20, 4: 30}])

    def fake_run_tag(http, tags, *args):
        s = next(scores)
        return TagResult(n_tag_games=9, candidates=[], analyses=[analysis(v, f"G{k}", appid=k) for k, v in s.items()])

    monkeypatch.setattr(pipeline, "run_tag", fake_run_tag)
    first = wait(client, client.post("/api/tag-runs", json={"tags": ["A", "B"]}).json()["id"])["result"]
    assert first["compared"] is False and "score_change" not in first["games"][0]
    time.sleep(0.01)
    second = wait(client, client.post("/api/tag-runs", json={"tags": ["b", "A"]}).json()["id"])["result"]
    by_id = {g["game"]["appid"]: g for g in second["games"]}
    assert second["compared"] is True
    assert by_id[1]["score_change"] == -5 and by_id[1]["new"] is False
    assert by_id[2]["score_change"] == 0
    assert by_id[4]["new"] is True and by_id[4]["score_change"] is None


def test_different_filters_are_not_compared(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: fake_result())
    wait(client, client.post("/api/tag-runs", json={"tags": ["A"]}).json()["id"])
    other = wait(client, client.post("/api/tag-runs", json={"tags": ["A"], "min_reviews": 500}).json()["id"])
    assert other["result"]["compared"] is False


def test_ranking_csv(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: fake_result())
    run_id = client.post("/api/tag-runs", json={"tags": ["Job Simulator"]}).json()["id"]
    wait(client, run_id)
    res = client.get(f"/api/tag-runs/{run_id}/ranking.csv")
    assert res.status_code == 200 and 'filename="job-simulator.csv"' in res.headers["content-disposition"]
    lines = res.text.splitlines()
    assert lines[0].startswith("rank,appid,name,score,score_change,reviews,pct_positive,reviews_last_12_months")
    assert lines[1].startswith("1,1,Best Sim,60,,1000,40,0,")  # its only histogram month is long ago
    assert len(lines) == 3  # the DLC is excluded, like in the ranking


# --- cancel ---------------------------------------------------------------------------------------

def test_cancel_stops_a_running_search(client, monkeypatch, run_store):
    import threading
    stopped = threading.Event()

    def slow_run_tag(http, tags, *args):
        step = args[-1]
        try:
            for i in range(500):
                step("Analyzing", i, 500)
                time.sleep(0.01)
        except pipeline.Cancelled:
            stopped.set()
            raise
        return fake_result()

    monkeypatch.setattr(pipeline, "run_tag", slow_run_tag)
    run_id = client.post("/api/tag-runs", json={"tags": ["X"]}).json()["id"]
    time.sleep(0.05)
    assert client.post(f"/api/tag-runs/{run_id}/cancel").json() == {"status": "cancelled"}
    assert client.get(f"/api/tag-runs/{run_id}").json()["status"] == "cancelled"  # at once
    assert stopped.wait(2)  # and the pipeline stops at its next step
    time.sleep(0.05)
    job = client.get(f"/api/tag-runs/{run_id}").json()
    assert job["status"] == "cancelled" and "result" not in job
    assert run_store.list() == []  # a cancelled run isn't saved


def test_cancel_after_finish_changes_nothing(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tag", lambda *a: fake_result())
    run_id = client.post("/api/tag-runs", json={"tags": ["X"]}).json()["id"]
    wait(client, run_id)
    assert client.post(f"/api/tag-runs/{run_id}/cancel").json() == {"status": "done"}
    assert client.post("/api/tag-runs/nope/cancel").status_code == 404


def test_page_files_are_revalidated(client):
    for path in ["/", "/static/app.js"]:
        assert client.get(path).headers["cache-control"] == "no-cache"
