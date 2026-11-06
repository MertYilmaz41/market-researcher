"""Opportunity summary of a tag run, written by a local LLM (Ollama).

The model reads what the run already found for its top-ranked games (complaint shares, quotes,
phrases from positive reviews, recent ratings) and writes what players love, the complaints the
games share, what a better game should do, and the caveats. Scores and rankings don't change.

Every point names the games it rests on; points naming none of the analyzed games are dropped
(the model made them up), and unknown names are removed from the rest.

write_game() does the same for one game: why its players are unhappy, what to do differently, and
the complaints in its negative reviews that no keyword category matched (with quotes that must be
in those reviews).
"""

import json
import re
import time

import httpx

from . import config, risk
from .i18n import use
from .market import MarketStats, summary as market_line
from .mining import llm
from .mining.keywords import _hits, clean
from .models import Analysis, GameSummary, OpportunitySummary, OtherComplaint, Review, SummaryPoint
from .report import rank

SECTIONS = ("loved", "complaints", "build", "caveats")
LANGUAGES = {"en": "English", "tr": "Turkish"}
QUOTE_CHARS = 160
REVIEW_CHARS = 400  # per uncovered review in a game summary

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


GAME_SYSTEM = """You help an indie game designer learn from one Steam game that many people bought but
rate poorly. Part 1 of the evidence is what a keyword search found in its reviews. Part 2 is negative
reviews that the keyword search couldn't put in any complaint category.

Using only this evidence, write:
- why: one or two sentences on why players are unhappy with this game.
- fix: 3 to 5 concrete things a new game for these players should do differently. Each rests on a
  share, quote or phrase from the evidence; not generic advice such as "polish the game".
- other: up to 5 complaints from part 2 that the keyword categories (bugs, controls, interface,
  content, performance, abandoned, realism, scope) don't cover, e.g. price, monetization, cheaters,
  a missing mode. Each with quote: the exact words of one review in part 2. Empty if there are none.

Don't invent features, numbers or complaints the evidence doesn't mention. Write why, fix and the
text of other in {language}; keep each quote in the review's own words.
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


def request(text: str, lang: str, model: str, system: str = SYSTEM, fmt: dict | None = None) -> dict:
    return {
        "model": model,
        "messages": [{"role": "system", "content": system.format(language=LANGUAGES[lang])},
                     {"role": "user", "content": text}],
        "format": fmt or schema(),
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


def game_schema() -> dict:
    other = {"type": "object", "properties": {"text": {"type": "string"}, "quote": {"type": "string"}},
             "required": ["text", "quote"]}
    return {"type": "object", "required": ["why", "fix", "other"], "properties": {
        "why": {"type": "string"}, "fix": {"type": "array", "items": {"type": "string"}},
        "other": {"type": "array", "items": other}}}


def uncovered(negative: list[Review]) -> list[str]:
    """Negative reviews no complaint category matched, most helpful first, shortened."""
    rows = [r for r in negative if len(r.text.strip()) >= 20 and not _hits(clean(r.text))]
    rows.sort(key=lambda r: -r.votes_up)
    out = []
    for r in rows[:config.GAME_SUMMARY_REVIEWS]:
        text = " ".join(clean(r.text).split())
        out.append(text if len(text) <= REVIEW_CHARS else text[:REVIEW_CHARS].rsplit(" ", 1)[0] + "...")
    return out


def game_evidence(a: Analysis, negative: list[Review]) -> tuple[str, list[str]]:
    """The text the model reads about one game, and the uncovered reviews in it. Pure (always English)."""
    texts = uncovered(negative)
    with use("en"):
        part1 = _game(a)
    part2 = "\n".join(f"- {t}" for t in texts) or "(none)"
    return f"# Part 1\n{part1}\n\n# Part 2: {len(texts)} negative reviews in no category\n{part2}", texts


def parse_game(content: str, texts: list[str]) -> GameSummary:
    """The model's JSON -> a game summary. An "other" complaint whose quote isn't in one of the
    uncovered reviews is dropped (the model made it up)."""
    data = json.loads(content)
    fix = [str(x).strip() for x in data.get("fix") or [] if str(x).strip()]
    other = []
    for o in data.get("other") or []:
        if not isinstance(o, dict) or not str(o.get("text", "")).strip():
            continue
        quote = str(o.get("quote", "")).strip()
        if any(llm.grounded(quote, t) for t in texts):
            other.append(OtherComplaint(text=o["text"].strip(), quote=quote))
    return GameSummary(why=str(data.get("why") or "").strip(), fix=fix, other=other[:5], n_uncovered=len(texts))


def write_game(a: Analysis, negative: list[Review], lang: str, *, model: str = config.LLM_MODEL,
               client: httpx.Client | None = None) -> GameSummary:
    """Ask the local model about one game. Raises llm.LLMUnavailable if Ollama or the model is missing."""
    text, texts = game_evidence(a, negative)
    start = time.monotonic()
    content = llm.post_chat(request(text, lang, model, GAME_SYSTEM, game_schema()), client)
    out = parse_game(content, texts)
    out.model, out.seconds = model, round(time.monotonic() - start, 1)
    return out
