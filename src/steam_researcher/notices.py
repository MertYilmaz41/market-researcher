"""User-facing messages, shared by the CLI and the web UI.

Every situation where a user might wonder "what happened / what do I do now" gets a Notice here,
so both front ends say the same thing. Add new cases here, not ad hoc in the UI.
"""

import difflib
import re
from typing import Literal

import httpx
from pydantic import BaseModel

from . import config
from .http import RetryableStatus
from .models import Analysis

Level = Literal["success", "info", "warning", "error"]

TAG_EXAMPLES = "Job Simulator, Colony Sim, Management, Base Building, Life Sim, Farming Sim"
SECONDS_PER_GAME = 3.0  # rough first-run cost at 200 reviews per game (rate limits)
BROAD_TAG_GAMES = 1000
FEW_CANDIDATES = 3
WEAK_SCORE = 20


class Notice(BaseModel):
    level: Level
    title: str
    message: str
    hint: str = ""


# ---------- before a run ----------

def for_filters(min_reviews: int, lo: float, hi: float, max_games: int, reviews: int) -> list[Notice]:
    out = []
    if min_reviews < config.MIN_REVIEWS:
        out.append(Notice(
            level="warning", title="Demand not proven",
            message=f"Games with fewer than {config.MIN_REVIEWS} reviews don't prove that players want the idea.",
            hint=f"The method recommends at least {config.MIN_REVIEWS} reviews, ideally {config.IDEAL_REVIEWS}+.",
        ))
    if hi > config.MAX_RATING:
        out.append(Notice(
            level="info", title="Above 70% isn't underserved",
            message=f"Games above {config.MAX_RATING:g}% positive satisfied their players, so they score 0.",
            hint=f"Keep '% positive to' at {config.MAX_RATING:g} or lower to focus on disappointed audiences.",
        ))
    if lo < config.MIN_RATING:
        out.append(Notice(
            level="info", title="Very low ratings included",
            message=f"Ratings under {config.MIN_RATING:g}% are often troll-bombed or broken listings.",
            hint=f"The method starts at {config.MIN_RATING:g}%.",
        ))
    seconds = max_games * SECONDS_PER_GAME * max(1.0, reviews / 200)
    if seconds > 60:
        out.append(Notice(
            level="info", title="This may take a while",
            message=f"The first run of a tag with these settings can take about {round(seconds / 60)} min "
                    "because Steam and SteamSpy limit request speed.",
            hint="Later runs of the same tag load from the cache in seconds.",
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
            level="warning", title="No game has all these tags",
            message=f"No game on SteamSpy is tagged {tag}.",
            hint="Remove a tag or pick a broader one.",
        )]

    if result.n_tag_games > BROAD_TAG_GAMES:
        out.append(Notice(
            level="info", title="Very broad tag",
            message=f"'{tag}' has {result.n_tag_games:,} games. The method works best on specific genres "
                    "with a clear player fantasy.",
            hint=f"Try a narrower tag, e.g. {TAG_EXAMPLES}.",
        ))

    m = result.market
    if m and m.n_underserved + m.n_well_served >= 5 and m.gap < config.LOW_GAP:
        out.append(Notice(
            level="info", title="Audience already well served",
            message=f"Only {m.n_underserved:,} of the {m.n_underserved + m.n_well_served:,} rated games with demand "
                    f"are underserved; {m.n_well_served:,} are {config.WELL_SERVED_RATING}%+ positive.",
            hint="Players here already have good games. Compare tags in the Markets view (sr markets).",
        ))

    if n_cand == 0:
        if result.n_enough_reviews == 0:
            out.append(Notice(
                level="warning", title="No games with enough reviews",
                message=f"None of the {result.n_tag_games:,} games tagged '{tag}' has {min_reviews:,}+ reviews.",
                hint="Lower 'Minimum reviews' in Filters, or try a more popular tag.",
            ))
        else:
            out.append(Notice(
                level="warning", title="No games in the rating range",
                message=f"{result.n_enough_reviews:,} games have {min_reviews:,}+ reviews, but none is "
                        f"{lo:g}-{hi:g}% positive. Players seem happy with this genre.",
                hint="Widen the '% positive' range in Filters, or try another tag.",
            ))
        return out

    if not ranked:
        out.append(Notice(
            level="warning", title="Nothing left to rank",
            message="Every candidate turned out to be DLC, a soundtrack or failed to load.",
            hint="Try another tag or wider filters.",
        ))
    elif n_cand < FEW_CANDIDATES:
        out.append(Notice(
            level="info", title="Few candidates",
            message=f"Only {n_cand} game(s) passed the filters.",
            hint="Try a related tag or a wider '% positive' range for more to compare.",
        ))

    if n_cand > max_games:
        out.append(Notice(
            level="info", title="Not every candidate analyzed",
            message=f"Analyzed the top {max_games} of {n_cand} candidates (by review count).",
            hint="Raise 'Games to analyze' in Filters to include more.",
        ))

    if result.failed:
        names = ", ".join(name for name, _ in result.failed[:5])
        more = f" and {len(result.failed) - 5} more" if len(result.failed) > 5 else ""
        out.append(Notice(
            level="warning", title=f"{len(result.failed)} game(s) couldn't be analyzed",
            message=f"Skipped: {names}{more}. Reason: {result.failed[0][1]}",
            hint="Run again later; games that loaded are cached.",
        ))

    outside = [a for a in ranked if a.game.rating_source != "steamspy" and not lo <= a.game.rating <= hi]
    if outside:
        names = ", ".join(f"{a.game.name} ({a.game.rating:.0f}%)" for a in outside[:5])
        out.append(Notice(
            level="info", title="Steam rates some games differently",
            message=f"SteamSpy put {len(outside)} game(s) in {lo:g}-{hi:g}% positive, but Steam's own numbers "
                    f"don't: {names}. They stay in the ranking, scored on Steam's numbers.",
        ))

    no_reviews = [a for a in ranked if a.review_error]
    if no_reviews:
        out.append(Notice(
            level="warning", title="Review texts unavailable",
            message=f"Couldn't load review texts for {len(no_reviews)} game(s), so their complaints weren't "
                    "mined and fixability was assumed to be 50%.",
            hint="Run again later to fill them in.",
        ))

    if ranked:
        best = ranked[0]
        if best.opportunity.score <= 0:
            out.append(Notice(
                level="warning", title="No real opportunity found",
                message="Every analyzed game is above 70% positive once review bombs are removed, "
                        "so none shows a disappointed audience.",
                hint=f"Try another tag, e.g. {TAG_EXAMPLES}.",
            ))
        else:
            if best.opportunity.score < WEAK_SCORE:
                out.append(Notice(
                    level="info", title="Only weak opportunities",
                    message=f"The best score is {best.opportunity.score:.0f}/100.",
                    hint="Compare with another tag before committing to this genre.",
                ))
            out.append(Notice(
                level="success", title="Analysis complete",
                message=f"Ranked {len(ranked)} game(s). Top opportunity: {best.game.name} "
                        f"(score {best.opportunity.score:.0f}).",
                hint="Click a game on the map or in the table for details.",
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
            level="error", title="Not a game",
            message=f"AppID {g.appid} is a {kind}, not a game, so this analysis doesn't apply.",
            hint="Use the base game's AppID from its Steam store page.",
        ))
    if "unlisted" in codes:
        out.append(Notice(
            level="info", title="No store page",
            message="This game is delisted or region-locked, so price and category data are missing.",
            hint="Its audience may be orphaned; check the game manually.",
        ))
    if g.reviews < config.MIN_REVIEWS:
        out.append(Notice(
            level="warning", title="Demand not proven",
            message=f"Only {g.reviews:,} reviews; the method needs {config.MIN_REVIEWS}+ to show real demand.",
            hint="Treat the score as unreliable.",
        ))
    if o.effective_rating > config.MAX_RATING:
        bombed = round(o.effective_rating) != round(g.rating)
        detail = (f"{g.rating:.0f}% positive overall, but {o.effective_rating:.0f}% once review bombs are removed"
                  if bombed else f"{g.rating:.0f}% positive")
        out.append(Notice(
            level="info", title="Players are satisfied",
            message=f"This game is {detail}, so it isn't an underserved audience (score 0).",
            hint="Look for games under 70% positive.",
        ))
    if not g.base_price:
        out.append(Notice(
            level="info", title="Free game",
            message="It's free to play, so the Box Method revenue estimate doesn't apply.",
        ))
    if a.review_error:
        out.append(Notice(
            level="warning", title="Review texts unavailable",
            message="Complaints couldn't be mined; fixability was assumed to be 50%.",
            hint="Try again later.",
        ))
    elif a.mining and a.mining.n_negative == 0:
        out.append(Notice(
            level="info", title="No negative reviews to mine",
            message="There are no English negative reviews, so there are no complaints to learn from.",
        ))
    return out


# ---------- errors ----------

def _host(exc: BaseException) -> str:
    try:
        return exc.request.url.host  # httpx errors carry the request
    except (AttributeError, RuntimeError):
        m = re.search(r"https?://([^/\s'\"]+)", str(exc))
        return m.group(1) if m else "the data service"


def friendly_error(exc: BaseException) -> Notice:
    host = _host(exc)
    if isinstance(exc, httpx.TimeoutException):
        return Notice(level="error", title=f"{host} timed out",
                      message=f"{host} didn't answer in time.",
                      hint="Check your internet connection and try again.")
    if isinstance(exc, httpx.TransportError):
        return Notice(level="error", title=f"Can't reach {host}",
                      message=f"The connection to {host} failed.",
                      hint="Check your internet connection and try again.")
    if isinstance(exc, RetryableStatus):
        return Notice(level="error", title=f"{host} is busy",
                      message=f"{host} is rate-limiting or temporarily down ({exc}).",
                      hint="Wait a minute and try again. Data already downloaded is kept in the cache.")
    if isinstance(exc, httpx.HTTPStatusError):
        return Notice(level="error", title=f"{host} refused the request",
                      message=f"{host} answered HTTP {exc.response.status_code}.",
                      hint="Try again later. If it keeps happening, the service may have changed.")
    if isinstance(exc, RuntimeError) and ("redirected" in str(exc) or "did not return JSON" in str(exc)):
        return Notice(level="error", title=f"Unexpected answer from {host}",
                      message=f"{host} returned something other than the expected data. The service may have changed.",
                      hint="Try again later. If it persists, the data source needs an update.")
    return Notice(level="error", title="Unexpected error",
                  message=f"{type(exc).__name__}: {exc}",
                  hint="Try again. If it keeps happening, run the CLI with SR_DEBUG=1 for details.")


def unknown_tag(tag: str, known: list[str] | tuple = ()) -> Notice:
    fold = tag.strip().casefold()
    # A real Steam tag that SteamSpy can't search (known: Steam's catalog, which may gain new tags).
    # Spelling suggestions would mislead here (Incremental -> Instrumental Music), so none are given.
    if fold in {k.casefold() for k in [*known, *config.STEAMSPY_UNSEARCHABLE_TAGS]}:
        return Notice(level="error", title="Tag can't be searched",
                      message=f"'{tag}' is a Steam tag, but SteamSpy (the data source) can't search it.",
                      hint=f"Pick a related tag instead, e.g. {TAG_EXAMPLES}.")
    by_fold = {k.casefold(): k for k in known}
    close = difflib.get_close_matches(fold, list(by_fold), n=3, cutoff=0.6)
    names = [by_fold[c] for c in close]
    hint = (f"Did you mean {' or '.join([', '.join(names[:-1]), names[-1]] if len(names) > 1 else names)}?" if close
            else f"Check the spelling. Examples: {TAG_EXAMPLES}.")
    return Notice(level="error", title="Tag not found", message=f"SteamSpy has no games tagged '{tag}'.", hint=hint)


def known_tags(http) -> list[str]:
    """Steam's tag catalog for suggestions; [] if it can't be fetched (suggestions are optional)."""
    from .sources import steam_store

    try:
        return steam_store.tag_names(http)
    except Exception:
        return []
