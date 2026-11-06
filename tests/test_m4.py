import pytest

from steam_researcher import report, scoring
from steam_researcher.models import (
    Analysis, AppDetails, CategoryResult, Game, MiningResult, Opportunity, RiskFlag,
)


def game(pos=400, neg=600, appid=1, name="Sim"):
    return Game(appid=appid, name=name, positive=pos, negative=neg, price_cents=999, initial_price_cents=999)


def mining(fixable_share=1.0):
    cats = [CategoryResult(code="bugs", label="Game-breaking bugs", pillar="Flawless execution and polish",
                           fixable=True, count=10, share=0.5, quotes=["so | buggy"])]
    return MiningResult(n_negative=20, n_positive=10, categories=cats, idea_praise_share=0.2,
                        fixability=fixable_share, core_phrases=[("power washer", 5)], liked=[("ducks", 2)])


def flag(code, severity="warn"):
    return RiskFlag(code=code, severity=severity, message=code)


# --- scoring ---

def test_demand_and_dissatisfaction_bounds():
    assert scoring.demand(10) == 0 and scoring.demand(100_000) == 1
    assert scoring.demand(1000) > scoring.demand(100)
    assert scoring.dissatisfaction(5) == 1 and scoring.dissatisfaction(70) == 0 and scoring.dissatisfaction(90) == 0


def test_score_monotonic():
    worse = scoring.score(game(pos=300, neg=700), [], mining()).score
    better_rated = scoring.score(game(pos=650, neg=350), [], mining()).score
    assert worse > better_rated > 0
    more_demand = scoring.score(game(pos=3000, neg=7000), [], mining()).score
    assert more_demand > worse


def test_score_zero_when_satisfied():
    assert scoring.score(game(pos=800, neg=200), [], mining()).score == 0


def test_review_bomb_adjusted_rating_used():
    o = scoring.score(game(pos=300, neg=700), [], mining(), adjusted_rating=71)
    assert o.score == 0 and o.effective_rating == 71


def test_penalties_and_default_fixability():
    base = scoring.score(game(), [], None)
    assert base.fixability == 0.5
    hit = scoring.score(game(), [flag("netcode"), flag("niche"), flag("review_bomb", "high")], None)
    assert hit.penalty == 25 and set(hit.penalized) == {"netcode", "niche"}
    assert hit.score == pytest.approx(base.score - 25)


# --- report ---

def analysis(score, name, flags=(), mined=True, appid=1):
    o = Opportunity(score=score, demand=0.5, dissatisfaction=0.5, fixability=1, effective_rating=40,
                    penalty=0, penalized=[])
    return Analysis(game=game(name=name, appid=appid), details=None, flags=list(flags),
                    mining=mining() if mined else None, opportunity=o,
                    review_error=None if mined else "reviews down")


def test_rank_sorts_and_excludes_non_games():
    a = [analysis(10, "Low"), analysis(50, "High"), analysis(90, "DLC", [flag("not_game", "high")])]
    assert [x.game.name for x in report.rank(a)] == ["High", "Low"]


def test_render_report():
    text = report.render(
        tag="Job Simulator", analyses=[analysis(40, "Pipe | Sim", appid=7), analysis(20, "Other", mined=False)],
        n_candidates=2, n_tag_games=100, min_reviews=100, lo=5, hi=70, not_games=["Soundtrack (music)"], unlisted=[],
    )
    assert text.startswith("# Underserved Audience Report: Job Simulator")
    assert "Pipe \\| Sim" in text  # pipes escaped for tables
    assert text.index("Pipe \\| Sim") < text.index("Other")
    assert "**Do:** flawless execution and polish" in text
    assert "power washer" in text and "Review texts unavailable: reviews down" in text
    assert "Soundtrack (music)" in text
    assert "\n\n\n" not in text


def test_slug():
    assert report.slug("Job Simulator") == "job-simulator"


# --- score explanation -------------------------------------------------------------------------

def _analysis_for(g, flags=(), mined=True, adjusted=None):
    flags = list(flags)
    m = mining() if mined else None
    o = scoring.score(g, flags, m, adjusted)
    return Analysis(game=g, details=None, flags=flags, mining=m, opportunity=o)


def test_explain_walks_from_parts_to_score():
    a = _analysis_for(game(), [flag("netcode"), flag("niche_x")])
    e = scoring.explain(a)
    assert [p["label"] for p in e["parts"]] == ["Demand", "Dissatisfaction", "Fixability"]
    assert [p["weight"] for p in e["parts"]] == [0.40, 0.35, 0.25]
    assert e["combined"] - 15 == pytest.approx(e["score"])  # only netcode is penalized
    assert e["penalties"] == [{"code": "netcode", "label": "Online multiplayer", "points": 15, "reason": "netcode"}]
    assert "1,000 reviews" in e["parts"][0]["basis"] and "40% positive" in e["parts"][1]["basis"]
    assert e["zero_part"] is None


def test_explain_notes_review_bombs_and_unmined_reviews():
    e = scoring.explain(_analysis_for(game(), mined=False, adjusted=55))
    assert "55% with review-bomb periods removed" in e["parts"][1]["basis"]
    assert "assumed" in e["parts"][2]["basis"] and e["parts"][2]["value"] == 0.5


def test_explain_names_a_zero_part():
    e = scoring.explain(_analysis_for(game(pos=900, neg=100)))  # 90% positive: not dissatisfied
    assert e["zero_part"] == "Dissatisfaction" and e["score"] == 0 and e["combined"] == 0


def test_analyze_game_keeps_the_negatives_when_positives_fail(monkeypatch):
    """A failed positive fetch must not throw away the negative sample: complaints and fixability still count."""
    import httpx

    from steam_researcher import pipeline
    from steam_researcher.models import Review

    def sample(http, appid, kind, limit):
        if kind == "positive":
            raise httpx.ReadTimeout("slow")
        return [Review(recommendation_id=str(i), text="Crashes constantly, full of bugs.", voted_up=False,
                       votes_up=1, playtime_minutes=600, timestamp=0) for i in range(5)]

    monkeypatch.setattr(pipeline.steamspy, "game_details", lambda http, appid: game())
    monkeypatch.setattr(pipeline.steam_store, "app_details", lambda http, appid: None)
    monkeypatch.setattr(pipeline.steam_store, "review_histogram", lambda http, appid: [])
    monkeypatch.setattr(pipeline, "official_reviews", lambda http, g, hist: g)
    monkeypatch.setattr(pipeline, "review_sample", sample)
    a = pipeline.analyze_game(None, 1)
    assert a.review_error is None and a.mining.categories[0].code == "bugs"
    assert a.opportunity.fixability == 1.0  # mined, not the 0.5 default

    def down(http, appid, kind, limit):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(pipeline, "review_sample", down)
    a = pipeline.analyze_game(None, 1)
    assert a.mining is None and a.review_error
