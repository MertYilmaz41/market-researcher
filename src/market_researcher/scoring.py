"""Opportunity score: how often the game's similar games became hits (peers.py, #12), minus risk penalties.

Until Nov 23 2026 it was demand x dissatisfaction ("Proven Demand + Poor Execution"). The game-level backtest
found dissatisfaction predicts nothing and the similar games' hit rate predicts far more than demand; demand added
nothing to it. Demand, dissatisfaction and fixability are still computed and shown, not counted."""

import math

from . import config
from .i18n import N_, _
from .models import Analysis, Game, MiningResult, Opportunity, Peers, RiskFlag


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def demand(reviews: int) -> float:
    if reviews <= 0:
        return 0.0
    span = config.DEMAND_LOG_MAX - config.DEMAND_LOG_MIN
    return _clamp((math.log10(reviews) - config.DEMAND_LOG_MIN) / span)


def dissatisfaction(rating: float) -> float:
    """1 at MIN_RATING (5%), 0 at MAX_RATING (70%) and above."""
    return _clamp((config.MAX_RATING - rating) / (config.MAX_RATING - config.MIN_RATING))


def peer_score(peers: Peers | None) -> float | None:
    """100 x the similar games' hit rate / PEER_RATE_FULL (capped at 100); None if unread or too few."""
    if peers is None or peers.entrants < config.MIN_PEERS:
        return None
    return 100 * min(1.0, peers.hit_rate / config.PEER_RATE_FULL)


def score(
    game: Game,
    flags: list[RiskFlag],
    mining: MiningResult | None,
    adjusted_rating: float | None = None,
    peers: Peers | None = None,
) -> Opportunity:
    rating = adjusted_rating if adjusted_rating is not None else game.rating
    fix = mining.fixability if mining and mining.categories else config.DEFAULT_FIXABILITY
    parts = {"demand": demand(game.reviews), "dissatisfaction": dissatisfaction(rating), "fixability": fix}

    base = peer_score(peers)
    penalized = [f.code for f in flags if f.code in config.RISK_PENALTIES]
    penalty = sum(config.RISK_PENALTIES[c] for c in penalized)
    return Opportunity(
        score=None if base is None else max(0.0, base - penalty),
        effective_rating=rating,
        penalty=penalty,
        penalized=penalized,
        peers=peers,
        **parts,
    )


def rescore(a: Analysis, peers: Peers) -> None:
    """Score an analysis with its similar games, read after it was analyzed."""
    a.opportunity = score(a.game, a.flags, a.mining, a.opportunity.effective_rating, peers)


def months(p: Peers) -> tuple[str, str]:
    """("2020-11", "2022-10"): the first and last release month of the similar games counted."""
    end = p.start + 23
    return f"{p.start // 12}-{p.start % 12 + 1:02d}", f"{end // 12}-{end % 12 + 1:02d}"


PART_LABELS = {"peers": N_("Similar games' hits"), "demand": N_("Demand"), "dissatisfaction": N_("Dissatisfaction"),
               "fixability": N_("Fixability")}
SHOWN_PARTS = ("peers", "demand", "dissatisfaction", "fixability")  # only peers is counted


def peers_text(p: Peers | None) -> str:
    """One sentence on the similar games (current language)."""
    if p is None:
        return _("Not measured yet: it needs the list of every rated Steam game (~36 min the first time, "
                 "then cached for a week).")
    if not p.tags:
        return _("Steam's store search doesn't list this game (it needs 10+ reviews), so its similar games "
                 "can't be found.")
    first, last = months(p)
    tags = ", ".join(p.tags)
    if p.entrants < config.MIN_PEERS:
        return _("Only {n} similar games (sharing 2 of its first 3 tags: {tags}) were released {first} to {last}; "
                 "too few to tell.", n=p.entrants, tags=tags, first=first, last=last)
    return _("{hits} of {n} similar games (sharing 2 of its first 3 tags: {tags}) released {first} to {last} now "
             "have 500+ reviews at 80%+ positive ({rate:.0%}).", hits=p.hits, n=p.entrants, tags=tags, first=first,
             last=last, rate=p.hit_rate)


def explain(a: Analysis) -> dict:
    """How a game's score was reached, in plain words (current language), for the web UI's score card."""
    o, g = a.opportunity, a.game
    lo_reviews, hi_reviews = round(10 ** config.DEMAND_LOG_MIN), round(10 ** config.DEMAND_LOG_MAX)
    rating = _("{rating:.0f}% positive", rating=g.rating)
    if round(o.effective_rating) != round(g.rating):
        rating += _(" ({adjusted:.0f}% with review-bomb periods removed)", adjusted=o.effective_rating)
    mined = a.mining is not None and bool(a.mining.categories)
    base = peer_score(o.peers)
    basis = {
        "peers": peers_text(o.peers) + " " + _("{full:.0%}+ = 100%.", full=config.PEER_RATE_FULL),
        "demand": _("{n:,} reviews. Log scale: {lo} reviews = 0%, {hi:,}+ = 100%. Not counted: once the similar "
                    "games are known, it adds nothing.", n=g.reviews, lo=lo_reviews, hi=hi_reviews),
        "dissatisfaction": _("{rating}. {max:g}%+ positive = 0%, {min:g}% = 100%. Not counted: in the backtest, "
                             "how unhappy (or happy) a game's players were said nothing about how new games did.",
                             rating=rating, max=config.MAX_RATING, min=config.MIN_RATING),
        "fixability": (_("{fix:.0%} of complaint mentions are things a small team can fix "
                         "(bugs, UI, performance...), not scope or genre. Not counted in the score: "
                         "it is close to 100% for almost every game.", fix=o.fixability) if mined else
                       _("Reviews couldn't be mined, so {fix:.0%} is assumed.", fix=config.DEFAULT_FIXABILITY)
                       if a.mining is None else
                       _("Reviews were read, but none matched a complaint category, so {fix:.0%} is assumed.",
                         fix=config.DEFAULT_FIXABILITY)),
    }
    values = {"peers": None if base is None else base / 100}
    parts = [{"key": k, "label": _(PART_LABELS[k]), "value": values[k] if k in values else getattr(o, k),
              "weight": 1.0 if k == "peers" else 0.0, "basis": basis[k]} for k in SHOWN_PARTS]
    reasons = {f.code: f.text() for f in a.flags}
    return {
        "score": o.score,
        "parts": parts,
        "combined": base,
        "penalties": [{"code": c, "label": _(config.RISK_LABELS.get(c, c)), "points": config.RISK_PENALTIES[c],
                       "reason": reasons.get(c, "")} for c in o.penalized],
        "pending": o.peers is None,
    }


LEVELS = (N_("Similar games often became hits"), N_("Similar games sometimes became hits"),
          N_("Similar games rarely became hits"))


def _bands(o) -> tuple[int, int]:
    """Demand and dissatisfaction bands for why()."""
    b = 0 if o.demand >= 0.7 else 1 if o.demand >= 0.4 else 2
    u = 0 if o.dissatisfaction >= 0.6 else 1 if o.dissatisfaction >= 0.3 else 2 if o.dissatisfaction > 0 else 3
    return b, u


def verdict(a: Analysis) -> str:
    """What the evidence shows, beside the ring in the web UI's game panel ("Similar games often became hits").
    Not a judgement such as "Strong opportunity". Bands as the pills' (palette.scoreLevel: 67/42), before penalties."""
    o = a.opportunity
    base = peer_score(o.peers)
    if o.peers is None:
        return _("Score not measured yet")
    if base is None:
        return _("Too few similar games")
    return _(LEVELS[0 if base >= 67 else 1 if base >= 42 else 2])


def why(a: Analysis) -> str:
    """The score's evidence in plain sentences (current language): the similar games, then demand and rating."""
    o, g = a.opportunity, a.game
    b, u = _bands(o)
    buyers = (_("Many buyers ({n:,} reviews)", n=g.reviews), _("Solid demand ({n:,} reviews)", n=g.reviews),
              _("Few buyers ({n:,} reviews)", n=g.reviews))[b]
    rating = o.effective_rating
    unhappy = (_("most of them unhappy ({rating:.0f}% positive)", rating=rating),
               _("many of them unhappy ({rating:.0f}% positive)", rating=rating),
               _("only mildly unhappy ({rating:.0f}% positive)", rating=rating),
               _("and players mostly like it ({rating:.0f}% positive)", rating=rating))[u]
    return peers_text(o.peers) + " " + _("{buyers}, {unhappy}.", buyers=buyers, unhappy=unhappy)
