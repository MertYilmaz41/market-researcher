"""Opportunity summary of a tag run, written by a local LLM (Ollama).

The model reads what the run already found for its top-ranked games (complaint shares, quotes,
phrases from positive reviews, recent ratings) and writes what players love, the complaints the
games share, what a better game should do, and the caveats. Scores and rankings don't change.

Every point names the games it rests on; points naming none of the analyzed games are dropped
(the model made them up), and unknown names are removed from the rest.
"""

import json
import re
import time

import httpx

from . import config, risk
from .i18n import use
from .market import MarketStats, summary as market_line
from .mining import llm
from .models import Analysis, OpportunitySummary, SummaryPoint
from .report import rank

SECTIONS = ("loved", "complaints", "build", "caveats")
LANGUAGES = {"en": "English", "tr": "Turkish"}
QUOTE_CHARS = 160

SYSTEM = """You help an indie game designer find an underserved audience on Steam. The evidence below
describes the top-ranked games for a tag: games many people bought (many reviews) but rate poorly.

Using only this evidence, write:
- loved: what players come for and enjoy in these games (the core fantasy worth keeping).
- complaints: the problems several of these games share.
- build: concrete design advice for a new game for this audience: keep what is loved, fix what is
  complained about. Each piece of advice names a concrete feature or fix and rests on a quote,
  phrase or share from the evidence; not generic advice such as "polish the game" or "fix the bugs".
- caveats: risks and limits, e.g. complaints that are rarely mentioned lately (already fixed),
  developers that abandoned their games, a small market, weak evidence.

Also write pitch: the opportunity in one sentence (who the players are, what they want, what no
game here gives them yet).

3 to 5 points per section, each one or two sentences. Put the exact names of the games a point is
based on in its games list, as written in the evidence; don't repeat the names in the text. A
complaint point needs games where that complaint has a large share. Don't invent games, numbers or
features that the evidence doesn't mention. Write all text, the pitch too, in {language}.
Answer with JSON only."""


def schema() -> dict:
    point = {"type": "object", "properties": {"text": {"type": "string"},
                                              "games": {"type": "array", "items": {"type": "string"}}},
             "required": ["text", "games"]}
    props = {"pitch": {"type": "string"}, **{s: {"type": "array", "items": point} for s in SECTIONS}}
    return {"type": "object", "properties": props, "required": ["pitch", *SECTIONS]}


def _quote(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= QUOTE_CHARS else text[:QUOTE_CHARS].rsplit(" ", 1)[0] + "..."


def _game(a: Analysis) -> str:
    g, m = a.game, a.mining
    recent, _total, _age = risk.recent_activity(a.histogram)
    lately = risk.recent_rating(a.histogram)
    head = (f"## {g.name}\nScore {a.opportunity.score:.0f}/100, {g.reviews:,} reviews, {g.rating:.0f}% positive")
    if lately is not None:
        head += f" (last 12 months: {lately:.0f}% positive of {recent:,} reviews)"
    lines = [head]
    for f in a.flags:
        lines.append(f"Risk: {f.message}")
    if m is None:
        return "\n".join(lines + ["(no reviews mined)"])
    lines.append(f"Fixable complaints: {m.fixability:.0%}. Negative reviews that still praise the idea: "
                 f"{m.idea_praise_share:.0%}.")
    lines.append(f"Complaints (share of {m.n_negative} negative reviews):")
    for c in m.categories[:4]:
        trend = f", {c.trend}" if c.trend else ""
        quotes = "; ".join(f'"{_quote(q)}"' for q in c.quotes[:2])
        lines.append(f"- {c.label}: {c.share:.0%}{trend}. {quotes}")
    if m.core_phrases:
        lines.append(f"Common phrases in {m.n_positive} positive reviews: "
                     + ", ".join(p for p, _n in m.core_phrases[:8]))
    if m.liked:
        lines.append('"Loved the ..." in positive reviews: ' + ", ".join(p for p, _n in m.liked[:5]))
    return "\n".join(lines)


def evidence(tag: str, analyses: list[Analysis], market: MarketStats | None) -> tuple[str, list[str]]:
    """The text the model reads, and the names of the games in it. Pure (always English)."""
    games = rank(analyses)[:config.SUMMARY_GAMES]
    with use("en"):
        parts = [f"# Tag: {tag}"]
        if market is not None:
            parts.append("Whole tag: " + market_line(market))
        parts += [_game(a) for a in games]
    return "\n\n".join(parts), [a.game.name for a in games]


def _squash(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def _match(name: str, names: list[str]) -> str | None:
    """The analyzed game a name from the model means (exact, or a unique game containing it)."""
    q = _squash(name)
    if not q:
        return None
    exact = [n for n in names if _squash(n) == q]
    if exact:
        return exact[0]
    partial = [n for n in names if len(q) >= 5 and q in _squash(n)]
    return partial[0] if len(partial) == 1 else None


def parse(content: str, names: list[str]) -> OpportunitySummary:
    """The model's JSON -> a summary. Unknown game names are removed; a point left with no game is
    dropped, except a caveat (it may be about the whole tag)."""
    data = json.loads(content)
    out = OpportunitySummary(pitch=str(data.get("pitch") or "").strip())
    for section in SECTIONS:
        points = []
        for p in data.get(section) or []:
            if not isinstance(p, dict) or not str(p.get("text", "")).strip():
                continue
            games = []
            for g in p.get("games") or []:
                m = _match(str(g), names)
                if m and m not in games:
                    games.append(m)
            if games or section == "caveats":
                points.append(SummaryPoint(text=p["text"].strip(), games=games))
        setattr(out, section, points)
    return out


def request(text: str, lang: str, model: str) -> dict:
    return {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM.format(language=LANGUAGES[lang])},
                     {"role": "user", "content": text}],
        "format": schema(),
        "stream": False,
        "options": {"temperature": 0, "num_ctx": config.SUMMARY_CTX},
    }


def write(tag: str, analyses: list[Analysis], market: MarketStats | None, lang: str, *,
          model: str = config.LLM_MODEL, client: httpx.Client | None = None) -> OpportunitySummary:
    """Ask the local model for the summary. Raises llm.LLMUnavailable if Ollama or the model is missing."""
    text, names = evidence(tag, analyses, market)
    start = time.monotonic()
    content = llm.post_chat(request(text, lang, model), client)
    out = parse(content, names)
    out.model, out.seconds = model, round(time.monotonic() - start, 1)
    return out
