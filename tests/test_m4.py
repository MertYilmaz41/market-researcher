import pytest

from market_researcher import report, scoring
from market_researcher.models import (
    Analysis, AppDetails, CategoryResult, Game, MiningResult, Opportunity, Peers, RiskFlag,
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


def peers(hits=15, entrants=100, tags=("Simulation", "Casual", "Indie")):
    return Peers(tags=list(tags), entrants=entrants, hits=hits, start=2020 * 12 + 10)


# --- scoring ---

def test_demand_and_dissatisfaction_bounds():
    assert scoring.demand(10) == 0 and scoring.demand(100_000) == 1
    assert scoring.demand(1000) > scoring.demand(100)
    assert scoring.dissatisfaction(5) == 1 and scoring.dissatisfaction(70) == 0 and scoring.dissatisfaction(90) == 0


def test_score_is_the_similar_games_hit_rate():
    """#12: 100 x hit rate / PEER_RATE_FULL (25%), capped; demand and dissatisfaction don't move it."""
    assert scoring.score(game(), [], mining(), peers=peers(15)).score == pytest.approx(60)
    assert scoring.score(game(), [], mining(), peers=peers(40)).score == 100
    same = [scoring.score(game(pos=p, neg=n), [], mining(), peers=peers(10)).score
            for p, n in [(300, 700), (900, 100), (30_000, 70_000), (40, 10)]]
    assert same == [pytest.approx(40)] * 4


def test_no_score_without_enough_similar_games():
    assert scoring.score(game(), [], mining()).score is None  # not read yet
    assert scoring.score(game(), [], mining(), peers=peers(5, entrants=9)).score is None  # too few
    assert scoring.score(game(), [], mining(), peers=peers(0, entrants=10)).score == 0


def test_old_saved_scores_are_not_shown_as_todays():
    """A run saved before #12 has no peers: its demand x dissatisfaction score is dropped when loaded."""
    old = {"score": 48.0, "demand": 0.5, "dissatisfaction": 0.5, "fixability": 1, "effective_rating": 40,
           "penalty": 0}
    assert Opportunity.model_validate(old).score is None
    assert Opportunity.model_validate({**old, "peers": None}).score == 48.0


def test_review_bomb_adjusted_rating_used():
    o = scoring.score(game(pos=300, neg=700), [], mining(), adjusted_rating=71, peers=peers())
    assert o.dissatisfaction == 0 and o.effective_rating == 71


def test_penalties_and_default_fixability():
    base = scoring.score(game(), [], None, peers=peers())
    assert base.fixability == 0.5
    hit = scoring.score(game(), [flag("netcode"), flag("niche"), flag("review_bomb", "high")], None, peers=peers())
    assert hit.penalty == 25 and set(hit.penalized) == {"netcode", "niche"}
    assert hit.score == pytest.approx(base.score - 25)
    assert scoring.score(game(), [flag("recovered")], None, peers=peers(2)).score == 0  # never below 0


def test_rescore_fills_in_the_similar_games():
    a = _analysis_for(game(), [flag("netcode")])
    assert a.opportunity.score is None
    scoring.rescore(a, peers(15))
    assert a.opportunity.score == pytest.approx(45) and a.opportunity.peers.hits == 15


# --- report ---

def analysis(score, name, flags=(), mined=True, appid=1):
    o = Opportunity(score=score, demand=0.5, dissatisfaction=0.5, fixability=1, effective_rating=40,
                    penalty=0, penalized=[], peers=None if score is None else peers(round(score / 4)))
    return Analysis(game=game(name=name, appid=appid), details=None, flags=list(flags),
                    mining=mining() if mined else None, opportunity=o,
                    review_error=None if mined else "reviews down")


def test_rank_sorts_and_excludes_non_games():
    a = [analysis(10, "Low"), analysis(50, "High"), analysis(90, "DLC", [flag("not_game", "high")])]
    assert [x.game.name for x in report.rank(a)] == ["High", "Low"]


def test_rank_puts_unscored_last_and_breaks_ties_by_reviews():
    a = [analysis(None, "Pending", appid=1), analysis(40, "Small", appid=2), analysis(40, "Big", appid=3),
         analysis(20, "Low", appid=4)]
    a[2].game.positive = 5000
    assert [x.game.name for x in report.rank(a)] == ["Big", "Small", "Low", "Pending"]


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

def _analysis_for(g, flags=(), mined=True, adjusted=None, similar=None):
    flags = list(flags)
    m = mining() if mined else None
    o = scoring.score(g, flags, m, adjusted, similar)
    return Analysis(game=g, details=None, flags=flags, mining=m, opportunity=o)


def test_explain_walks_from_parts_to_score():
    a = _analysis_for(game(), [flag("netcode"), flag("niche_x")], similar=peers(15))
    e = scoring.explain(a)
    assert [p["label"] for p in e["parts"]] == ["Similar games' hits", "Demand", "Dissatisfaction", "Fixability"]
    assert [p["weight"] for p in e["parts"]] == [1.0, 0.0, 0.0, 0.0]  # only the similar games count
    assert e["parts"][0]["value"] == pytest.approx(0.6)
    assert "15 of 100 similar games (sharing 2 of its first 3 tags: Simulation, Casual, Indie) released " \
           "2020-11 to 2022-10" in e["parts"][0]["basis"]
    assert "Not counted" in e["parts"][1]["basis"] and "Not counted" in e["parts"][3]["basis"]
    assert e["combined"] == pytest.approx(60) and e["score"] == pytest.approx(45)  # only netcode is penalized
    assert e["penalties"] == [{"code": "netcode", "label": "Online multiplayer", "points": 15, "reason": "netcode"}]
    assert "1,000 reviews" in e["parts"][1]["basis"] and "40% positive" in e["parts"][2]["basis"]
    assert e["pending"] is False


def test_explain_without_a_score():
    e = scoring.explain(_analysis_for(game()))
    assert e["pending"] and e["score"] is None and e["combined"] is None and e["parts"][0]["value"] is None
    assert "Not measured yet" in e["parts"][0]["basis"]
    few = scoring.explain(_analysis_for(game(), similar=peers(3, entrants=8)))
    assert not few["pending"] and few["score"] is None and "Only 8 similar games" in few["parts"][0]["basis"]
    unlisted = scoring.explain(_analysis_for(game(), similar=peers(0, entrants=0, tags=())))
    assert "doesn't list this game" in unlisted["parts"][0]["basis"]


def test_explain_notes_review_bombs_and_unmined_reviews():
    e = scoring.explain(_analysis_for(game(), mined=False, adjusted=55))
    assert "55% with review-bomb periods removed" in e["parts"][2]["basis"]
    assert "assumed" in e["parts"][3]["basis"] and e["parts"][3]["value"] == 0.5


def test_explain_tells_unread_reviews_from_reviews_without_complaints():
    from market_researcher.models import MiningResult

    a = _analysis_for(game(), mined=False)
    assert a.mining is None and "couldn't be mined" in scoring.explain(a)["parts"][3]["basis"]
    a.mining = MiningResult(n_negative=40, n_positive=40, categories=[], idea_praise_share=0, fixability=0,
                            core_phrases=[], liked=[])
    assert "none matched a complaint category" in scoring.explain(a)["parts"][3]["basis"]


def test_analyze_game_keeps_the_negatives_when_positives_fail(monkeypatch):
    """A failed positive fetch must not throw away the negative sample: complaints and fixability still count."""
    import httpx

    from market_researcher import pipeline
    from market_researcher.models import Review

    def sample(http, appid, kind, limit, on_page=None):
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

    def down(http, appid, kind, limit, on_page=None):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(pipeline, "review_sample", down)
    a = pipeline.analyze_game(None, 1)
    assert a.mining is None and a.review_error


def test_recent_figures_count_back_from_the_analysis_time():
    """A saved run shows the last-12-months figures of the day it was made, not of today."""
    from market_researcher.models import HistPoint

    day = 24 * 3600
    then = 1_700_000_000  # Nov 2023
    a = analysis(50, "Sim")
    a.histogram = [HistPoint(date=then - 400 * day, up=100, down=0), HistPoint(date=then - 30 * day, up=10, down=10)]
    a.analyzed_at = then
    assert report.recent_text(a) == "20 (17%), 50% positive"
    a.analyzed_at = None  # older saved runs: count back from now, as before (nothing in the last year)
    assert report.recent_text(a) == "0 (0%)"


# --- plain-language verdict and checks (web UI game panel) -----------------------------------------

def test_verdict_says_what_the_evidence_shows():
    def v(hits, entrants=100):
        return scoring.verdict(_analysis_for(game(), similar=None if hits is None else peers(hits, entrants)))

    assert v(20) == "Similar games often became hits"  # 80
    assert v(12) == "Similar games sometimes became hits"  # 48
    assert v(5) == "Similar games rarely became hits"  # 20
    assert v(None) == "Score not measured yet"
    assert v(2, 5) == "Too few similar games"
    from market_researcher.i18n import use
    with use("tr"):
        assert v(20) == "Benzer oyunlar sık sık hit oldu"


def test_fixability_does_not_change_the_score():
    def scored(fix):
        m = mining()
        m.fixability = fix
        return scoring.score(game(), [], m, peers=peers()).score

    assert scored(0.2) == scored(1.0) > 0


def test_why_reads_the_evidence():
    a = _analysis_for(game(), [flag("netcode")], similar=peers(15))  # 1,000 reviews at 40%
    assert scoring.why(a).endswith(" now have 500+ reviews at 80%+ positive (15%). "
                                   "Solid demand (1,000 reviews), many of them unhappy (40% positive).")
    assert "players mostly like it" in scoring.why(_analysis_for(game(pos=900, neg=100)))
    from market_researcher.i18n import use
    with use("tr"):
        assert "1.000" in scoring.why(a)


def test_checks_list_every_check_passed_or_flagged():
    from market_researcher import config, risk

    a = _analysis_for(game(), [flag("netcode")])
    out = risk.checks(a)
    assert [c["code"] for c in out] == [c for c in config.RISK_LABELS
                                        if c not in ("rating_without_spikes", "not_game", "unlisted")]
    net = next(c for c in out if c["code"] == "netcode")
    assert net["flagged"] and net["points"] == 15 and net["detail"] == "netcode"
    passed = {c["code"]: c for c in out if not c["flagged"]}
    assert passed["deep_discount"]["detail"] == "full price" and passed["cheap_price"]["detail"] == "$9.99"
    assert all(c["points"] == 0 and c["severity"] is None for c in passed.values())
