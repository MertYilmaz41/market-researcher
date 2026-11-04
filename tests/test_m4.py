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
