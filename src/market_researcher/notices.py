"""User-facing messages, shared by the CLI and the web UI.

Every situation where a user might wonder "what happened / what do I do now" gets a Notice here,
so both front ends say the same thing. Add new cases here, not ad hoc in the UI. Text goes through
i18n._ (add the Turkish to i18n_tr.TR; tests/test_i18n.py checks it).
"""

import difflib
import re
from typing import Literal

import httpx
from pydantic import BaseModel

from . import config
from .http import HOST_INTERVAL, RetryableStatus
from .i18n import _
from .models import Analysis

Level = Literal["success", "info", "warning", "error"]

TAG_EXAMPLES = "Job Simulator, Colony Sim, Management, Base Building, Life Sim, Farming Sim"
SLOW_RUN_SECONDS = 180  # warn before a first run longer than this (a default 15-game run is ~2-3 min)
BROAD_TAG_GAMES = 1000
FEW_CANDIDATES = 3
WEAK_SCORE = 20


class Notice(BaseModel):
    level: Level
    title: str
    message: str
    hint: str = ""


# ---------- before a run ----------

def first_run_seconds_per_game(reviews: int) -> float:
    """Uncached cost of one game, set by Steam's review API (one request at a time, HOST_INTERVAL apart):
    2 for the review summary, plus pages of 100 for the helpful and the newest halves of both samples
    (pipeline.review_sample). The other hosts run alongside it."""
    half = -(-(reviews - reviews // 2) // 100) + -(-(reviews // 2) // 100)
    return (2 + 2 * half) * HOST_INTERVAL["api.steampowered.com"]


def for_filters(min_reviews: int, lo: float, hi: float, max_games: int, reviews: int) -> list[Notice]:
    out = []
    if min_reviews < config.MIN_REVIEWS:
        out.append(Notice(
            level="warning", title=_("Demand not proven"),
            message=_("Games with fewer than {n} reviews don't prove that players want the idea.", n=config.MIN_REVIEWS),
            hint=_("The method recommends at least {n} reviews, ideally {ideal}+.",
                   n=config.MIN_REVIEWS, ideal=config.IDEAL_REVIEWS),
        ))
    if hi > config.MAX_RATING:
        out.append(Notice(
            level="info", title=_("Above 70% isn't underserved"),
            message=_("Games above {max:g}% positive satisfied their players, so they score 0.", max=config.MAX_RATING),
            hint=_("Keep '% positive to' at {max:g} or lower to focus on disappointed audiences.", max=config.MAX_RATING),
        ))
    if lo < config.MIN_RATING:
        out.append(Notice(
            level="info", title=_("Very low ratings included"),
            message=_("Ratings under {min:g}% are often troll-bombed or broken listings.", min=config.MIN_RATING),
            hint=_("The method starts at {min:g}%.", min=config.MIN_RATING),
        ))
    seconds = max_games * first_run_seconds_per_game(reviews)
    if seconds > SLOW_RUN_SECONDS:
        out.append(Notice(
            level="info", title=_("This may take a while"),
            message=_("The first run of a tag with these settings can take about {min} min "
                      "because Steam and SteamSpy limit request speed.", min=round(seconds / 60)),
            hint=_("Later runs of the same tag load from the cache in seconds."),
        ))
    return out


# ---------- after a tag run ----------

def for_tag_result(tag: str, min_reviews: int, lo: float, hi: float, max_games: int, result) -> list[Notice]:
    """`result` is a pipeline.TagResult (not imported to avoid a cycle)."""
    from .report import rank

    out = []
    n_cand = len(result.candidates)
    ranked = rank(result.analyses)

    if result.n_tag_games == 0:  # only possible with several tags: no game has all of them
        return [Notice(
            level="warning", title=_("No game has all these tags"),
            message=_("No game on SteamSpy is tagged {tag}.", tag=tag),
            hint=_("Remove a tag or pick a broader one."),
        )]

    if result.n_tag_games > BROAD_TAG_GAMES:
        out.append(Notice(
            level="info", title=_("Very broad tag"),
            message=_("'{tag}' has {n:,} games. The method works best on specific genres "
                      "with a clear player fantasy.", tag=tag, n=result.n_tag_games),
            hint=_("Try a narrower tag, e.g. {examples}.", examples=TAG_EXAMPLES),
        ))

    m = result.market
    if m and m.n_underserved + m.n_well_served >= 5 and m.gap < config.LOW_GAP:
        out.append(Notice(
            level="info", title=_("Audience already well served"),
            message=_("Only {under:,} of the {rated:,} rated games with demand are underserved; "
                      "{well:,} are {good}%+ positive.", under=m.n_underserved,
                      rated=m.n_underserved + m.n_well_served, well=m.n_well_served, good=config.WELL_SERVED_RATING),
            hint=_("Players here already have good games. Compare tags in the Markets view (mr markets)."),
        ))

    if n_cand == 0:
        if result.n_enough_reviews == 0:
            out.append(Notice(
                level="warning", title=_("No games with enough reviews"),
                message=_("None of the {n:,} games tagged '{tag}' has {min:,}+ reviews.",
                          n=result.n_tag_games, tag=tag, min=min_reviews),
                hint=_("Lower 'Minimum reviews' in Filters, or try a more popular tag."),
            ))
        else:
            out.append(Notice(
                level="warning", title=_("No games in the rating range"),
                message=_("{n:,} games have {min:,}+ reviews, but none is {lo:g}-{hi:g}% positive. "
                          "Players seem happy with this genre.", n=result.n_enough_reviews, min=min_reviews, lo=lo, hi=hi),
                hint=_("Widen the '% positive' range in Filters, or try another tag."),
            ))
        return out

    if not ranked:
        out.append(Notice(
            level="warning", title=_("Nothing left to rank"),
            message=_("Every candidate turned out to be DLC, a soundtrack or failed to load."),
            hint=_("Try another tag or wider filters."),
        ))
    elif n_cand < FEW_CANDIDATES:
        out.append(Notice(
            level="info", title=_("Few candidates"),
            message=_("Only {n} game(s) passed the filters.", n=n_cand),
            hint=_("Try a related tag or a wider '% positive' range for more to compare."),
        ))

    if n_cand > max_games:
        out.append(Notice(
            level="info", title=_("Not every candidate analyzed"),
            message=_("Analyzed the top {n} of {total} candidates (by review count).", n=max_games, total=n_cand),
            hint=_("Raise 'Games to analyze' in Filters to include more."),
        ))

    if result.failed:
        names = ", ".join(name for name, _reason in result.failed[:5])
        more = _(" and {n} more", n=len(result.failed) - 5) if len(result.failed) > 5 else ""
        out.append(Notice(
            level="warning", title=_("{n} game(s) couldn't be analyzed", n=len(result.failed)),
            message=_("Skipped: {names}{more}. Reason: {reason}", names=names, more=more, reason=result.failed[0][1]),
            hint=_("Run again later; games that loaded are cached."),
        ))

    outside = [a for a in ranked if a.game.rating_source != "steamspy" and not lo <= a.game.rating <= hi]
    if outside:
        names = ", ".join(_("{name} ({rating:.0f}%)", name=a.game.name, rating=a.game.rating) for a in outside[:5])
        out.append(Notice(
            level="info", title=_("Steam rates some games differently"),
            message=_("SteamSpy put {n} game(s) in {lo:g}-{hi:g}% positive, but Steam's own numbers "
                      "don't: {names}. They stay in the ranking, scored on Steam's numbers.",
                      n=len(outside), lo=lo, hi=hi, names=names),
        ))

    no_reviews = [a for a in ranked if a.review_error]
    if no_reviews:
        out.append(Notice(
            level="warning", title=_("Review texts unavailable"),
            message=_("Couldn't load review texts for {n} game(s), so their complaints weren't "
                      "mined and fixability was assumed to be 50%.", n=len(no_reviews)),
            hint=_("Run again later to fill them in."),
        ))

    if ranked:
        best = ranked[0]
        if best.opportunity.score <= 0:
            out.append(Notice(
                level="warning", title=_("No real opportunity found"),
                message=_("Every analyzed game is above 70% positive once review bombs are removed, "
                          "so none shows a disappointed audience."),
                hint=_("Try another tag, e.g. {examples}.", examples=TAG_EXAMPLES),
            ))
        else:
            if best.opportunity.score < WEAK_SCORE:
                out.append(Notice(
                    level="info", title=_("Only weak opportunities"),
                    message=_("The best score is {score:.0f}/100.", score=best.opportunity.score),
                    hint=_("Compare with another tag before committing to this genre."),
                ))
            out.append(Notice(
                level="success", title=_("Analysis complete"),
                message=_("Ranked {n} game(s). Top opportunity: {name} (score {score:.0f}).",
                          n=len(ranked), name=best.game.name, score=best.opportunity.score),
                hint=_("Click a game on the map or in the table for details."),
            ))
    return out


# ---------- single game ----------

def for_game(a: Analysis) -> list[Notice]:
    out = []
    g, o = a.game, a.opportunity
    codes = {f.code for f in a.flags}
    if "not_game" in codes:
        kind = a.details.type if a.details else "non-game"
        out.append(Notice(
            level="error", title=_("Not a game"),
            message=_("AppID {appid} is a {kind}, not a game, so this analysis doesn't apply.", appid=g.appid, kind=kind),
            hint=_("Use the base game's AppID from its Steam store page."),
        ))
    if "unlisted" in codes:
        out.append(Notice(
            level="info", title=_("No store page"),
            message=_("This game is delisted or region-locked, so price and category data are missing."),
            hint=_("Its audience may be orphaned; check the game manually."),
        ))
    if g.reviews < config.MIN_REVIEWS:
        out.append(Notice(
            level="warning", title=_("Demand not proven"),
            message=_("Only {n:,} reviews; the method needs {min}+ to show real demand.",
                      n=g.reviews, min=config.MIN_REVIEWS),
            hint=_("Treat the score as unreliable."),
        ))
    if o.effective_rating > config.MAX_RATING:
        bombed = round(o.effective_rating) != round(g.rating)
        detail = (_("{rating:.0f}% positive overall, but {adjusted:.0f}% once review bombs are removed",
                    rating=g.rating, adjusted=o.effective_rating)
                  if bombed else _("{rating:.0f}% positive", rating=g.rating))
        out.append(Notice(
            level="info", title=_("Players are satisfied"),
            message=_("This game is {detail}, so it isn't an underserved audience (score 0).", detail=detail),
            hint=_("Look for games under 70% positive."),
        ))
    if not g.base_price:
        out.append(Notice(
            level="info", title=_("Free game"),
            message=_("It's free to play, so the Box Method revenue estimate doesn't apply."),
        ))
    if a.review_error:
        out.append(Notice(
            level="warning", title=_("Review texts unavailable"),
            message=_("Complaints couldn't be mined; fixability was assumed to be 50%."),
            hint=_("Try again later."),
        ))
    elif a.mining and a.mining.n_negative == 0:
        out.append(Notice(
            level="info", title=_("No negative reviews to mine"),
            message=_("There are no English negative reviews, so there are no complaints to learn from."),
        ))
    return out


# ---------- errors ----------

def _host(exc: BaseException) -> str:
    try:
        return exc.request.url.host  # httpx errors carry the request
    except (AttributeError, RuntimeError):
        m = re.search(r"https?://([^/\s'\"]+)", str(exc))
        return m.group(1) if m else _("the data service")


def friendly_error(exc: BaseException) -> Notice:
    host = _host(exc)
    if isinstance(exc, httpx.TimeoutException):
        return Notice(level="error", title=_("{host} timed out", host=host),
                      message=_("{host} didn't answer in time.", host=host),
                      hint=_("Check your internet connection and try again."))
    if isinstance(exc, httpx.TransportError):
        return Notice(level="error", title=_("Can't reach {host}", host=host),
                      message=_("The connection to {host} failed.", host=host),
                      hint=_("Check your internet connection and try again."))
    if isinstance(exc, RetryableStatus):
        return Notice(level="error", title=_("{host} is busy", host=host),
                      message=_("{host} is rate-limiting or temporarily down ({error}).", host=host, error=exc),
                      hint=_("Wait a minute and try again. Data already downloaded is kept in the cache."))
    if isinstance(exc, httpx.HTTPStatusError):
        return Notice(level="error", title=_("{host} refused the request", host=host),
                      message=_("{host} answered HTTP {status}.", host=host, status=exc.response.status_code),
                      hint=_("Try again later. If it keeps happening, the service may have changed."))
    if isinstance(exc, RuntimeError) and ("redirected" in str(exc) or "did not return JSON" in str(exc)):
        return Notice(level="error", title=_("Unexpected answer from {host}", host=host),
                      message=_("{host} returned something other than the expected data. "
                                "The service may have changed.", host=host),
                      hint=_("Try again later. If it persists, the data source needs an update."))
    return Notice(level="error", title=_("Unexpected error"),
                  message=f"{type(exc).__name__}: {exc}",
                  hint=_("Try again. If it keeps happening, run the CLI with MR_DEBUG=1 for details."))


def slow_reviews() -> Notice:
    """A search is waiting on Steam's review service (one page has taken SLOW_REVIEW_SECONDS or more)."""
    return Notice(level="warning", title=_("Steam's review service is slow"),
                  message=_("Some pages take 40 s or more. The search keeps going; a game whose reviews fail "
                            "still gets ranked."),
                  hint="")


def llm_unavailable(missing_model: str | None) -> Notice:
    """The opportunity summary needs Ollama (a local LLM) running with the model downloaded."""
    if missing_model:
        return Notice(level="warning", title=_("The model {model} isn't downloaded", model=missing_model),
                      message=_("The opportunity summary is written by {model}, a local model run by Ollama.",
                                model=missing_model),
                      hint=_("Download it once in a terminal: ollama pull {model}", model=missing_model))
    return Notice(level="warning", title=_("Ollama isn't running"),
                  message=_("The opportunity summary is written by a local model, and Ollama runs it."),
                  hint=_("Start the Ollama app (or install it from ollama.com), then try again."))


def unknown_tag(tag: str, known: list[str] | tuple = ()) -> Notice:
    fold = tag.strip().casefold()
    # A real Steam tag that SteamSpy can't search (known: Steam's catalog, which may gain new tags).
    # Spelling suggestions would mislead here (Incremental -> Instrumental Music), so none are given.
    if fold in {k.casefold() for k in [*known, *config.STEAMSPY_UNSEARCHABLE_TAGS]}:
        return Notice(level="error", title=_("Tag can't be searched"),
                      message=_("'{tag}' is a Steam tag, but SteamSpy (the data source) can't search it.", tag=tag),
                      hint=_("Pick a related tag instead, e.g. {examples}.", examples=TAG_EXAMPLES))
    by_fold = {k.casefold(): k for k in known}
    close = difflib.get_close_matches(fold, list(by_fold), n=3, cutoff=0.6)
    names = [by_fold[c] for c in close]
    joined = _(" or ").join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
    hint = (_("Did you mean {names}?", names=joined) if close
            else _("Check the spelling. Examples: {examples}.", examples=TAG_EXAMPLES))
    return Notice(level="error", title=_("Tag not found"),
                  message=_("SteamSpy has no games tagged '{tag}'.", tag=tag), hint=hint)


def known_tags(http) -> list[str]:
    """Steam's tag catalog for suggestions; [] if it can't be fetched (suggestions are optional)."""
    from .sources import steam_store

    try:
        return steam_store.tag_names(http)
    except Exception:
        return []
