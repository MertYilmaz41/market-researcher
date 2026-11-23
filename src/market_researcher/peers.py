"""A game's similar games and how many of them became hits: what the score counts since #12.

Similar games ("peers") share at least 2 of the game's first 3 store tags. The score is their hit rate among
those released 48-24 months ago. In the game-level backtest (game_backtest.py, docs/measurements.md) it predicted
how new games in the niche did (check rho +0.75, top fifth 13.6% hits vs bottom 5.6%); demand, satisfaction and
dissatisfaction added nothing to it.

Like pipeline.earlier_hits it uses store dates and today's reviews instead of review histories: across 30 tags
it had a median Spearman of +0.94 with the backtest's histogram version (#12). It needs every rated game on the
store (pipeline.read_peers): a tag search's own games gave only +0.62.
"""

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations

from . import backtest
from .backtest import HORIZON, OUTCOME, SUCCESS_RATING, SUCCESS_REVIEWS, Outcomes
from .models import Game, Peers

NICHE_TAGS = 3  # a game's first tags that define its niche...
NICHE_SHARED = 2  # ...of which a similar game must share at least this many


class NicheIndex:
    """Sums of (games, hits, sold) per tag pair and tag triple, so a niche's totals cost O(1) per game."""

    def __init__(self) -> None:
        self.pairs: dict[tuple, list[int]] = {}
        self.triples: dict[tuple, list[int]] = {}

    def add(self, tags: Iterable, hit: bool = False, sold: bool = False) -> None:
        tags = sorted(set(tags))
        for key in combinations(tags, 2):
            c = self.pairs.setdefault(key, [0, 0, 0])
            c[0] += 1; c[1] += hit; c[2] += sold  # noqa: E702
        for key in combinations(tags, 3):
            c = self.triples.setdefault(key, [0, 0, 0])
            c[0] += 1; c[1] += hit; c[2] += sold  # noqa: E702

    def niche(self, tags: Sequence) -> Outcomes:
        """Games sharing at least 2 of `tags` (2 or 3 tags): each pair counted, minus 2x those with all three."""
        tags = sorted(set(tags))
        if len(tags) < 2:
            return Outcomes()
        total = [0, 0, 0]
        for key in combinations(tags, 2):
            total = [a + b for a, b in zip(total, self.pairs.get(key, (0, 0, 0)))]
        if len(tags) == 3:
            total = [a - 2 * b for a, b in zip(total, self.triples.get(tuple(tags), (0, 0, 0)))]
        return Outcomes(entrants=total[0], hits=total[1], sold=total[2])


@dataclass
class PeerIndex:
    start: int  # backtest month: similar games released in [start, start + HORIZON) count
    index: NicheIndex
    tags: dict[int, tuple[int, ...]]  # appid -> its first tag ids, for every rated game
    names: dict[int, str]  # tag id -> name
    built: float  # when it was built (time.time())

    def of(self, appid: int) -> Peers:
        """The game's peers; no tags (and 0 peers) when the game isn't in the store's list (under 10 reviews)."""
        tags = self.tags.get(appid, ())[:NICHE_TAGS]
        o = self.index.niche(tags)
        return Peers(tags=[self.names.get(t, str(t)) for t in tags], entrants=o.entrants, hits=o.hits,
                     start=self.start)


def build(games: Iterable[Game], names: dict[int, str], now: float | None = None) -> PeerIndex:
    """From every rated game (steam_search.games_by_tags(http, [])): a game is a hit with 500+ reviews at 80%+
    today, as in pipeline.earlier_hits."""
    now = time.time() if now is None else now
    start = backtest.month(int(now)) - HORIZON - OUTCOME
    index, tags = NicheIndex(), {}
    for g in games:
        tags[g.appid] = tuple(g.tag_ids)
        d = g.release_date
        if d and start <= d.year * 12 + d.month - 1 < start + HORIZON:
            index.add(g.tag_ids, g.reviews >= SUCCESS_REVIEWS and g.rating >= SUCCESS_RATING)
    return PeerIndex(start=start, index=index, tags=tags, names=names, built=now)
