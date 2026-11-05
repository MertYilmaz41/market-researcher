"""Keyword-based review miner: complaint categories, quotes, core fantasy phrases."""

import re
import time
from collections import Counter

from .. import config
from ..models import CategoryResult, MiningResult, Review
from .lexicon import CATEGORIES, IDEA_PRAISE, NEGATION

_BBCODE = re.compile(r"\[/?[a-z0-9*]+(?:=[^\]]*)?\]", re.I)
_URL = re.compile(r"https?://\S+|www\.\S+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z][a-z'-]+")
_NEGATION = re.compile(NEGATION)
_COMPILED = {c.code: re.compile(r"\b(?:" + "|".join(c.patterns) + r")\b") for c in CATEGORIES}
_IDEA = re.compile(r"\b(?:" + "|".join(IDEA_PRAISE) + r")\b")
_LIKED = re.compile(
    r"\b(?:i )?(?:love|loved|like|liked|enjoy|enjoyed|adore)\s+(?:the|how|that you can|being able to)\s+"
    r"([a-z][a-z' -]{3,40}?)(?=[.,!?;:\n]| and | but | is | are |$)"
)

STOPWORDS = set(
    """a about above after again against all also am an and any are aren't as at be because been before
    being below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't
    down during each even ever every few for from further get gets getting got had hadn't has hasn't have
    haven't having he her here hers herself him himself his how i i'd i'll i'm i've if in into is isn't it
    it's its itself just let's lot lots me more most much must my myself no nor not now of off on once only
    or other ought our ours out over own really same she should shouldn't so some still such than that
    that's the their theirs them themselves then there there's these they they're this those through to
    too under until up us very was wasn't way we we're were weren't what what's when where which while who
    whom why will with won't would wouldn't you you're your yours yourself yourselves one two also bit
    thing things lot""".split()
)
# Words that say nothing about the fantasy itself
GENERIC = set(
    """game games play played playing player players fun good great nice best better love loved like
    liked enjoy enjoyed recommend recommended buy bought worth time hours hour pretty really definitely
    amazing awesome cool overall review steam price sale money simulator simulation sim feel feels
    experience early access dev devs developer developers update updates looking forward
    current state wait""".split()
)


def clean(text: str) -> str:
    return _URL.sub(" ", _BBCODE.sub(" ", text)).lower()


def _hits(text: str) -> dict[str, re.Match]:
    """First non-negated match per category in one review."""
    found = {}
    for cat in CATEGORIES:
        for m in _COMPILED[cat.code].finditer(text):
            if cat.negatable and _NEGATION.search(text[max(0, m.start() - 30):m.start()]):
                continue
            found[cat.code] = m
            break
    return found


def _quote(match: re.Match, text: str, width: int = 220) -> str:
    """The sentence around a match; long sentences are windowed around the match."""
    start = max((s.end() for s in _SENTENCE.finditer(text, 0, match.start())), default=0)
    end_m = _SENTENCE.search(text, match.end())
    end = end_m.start() if end_m else len(text)
    if end - start > width:
        start = max(start, match.start() - width // 2)
        end = min(end, start + width)
        start = text.find(" ", start) + 1 if start > 0 else 0  # don't cut words
        return "..." + " ".join(text[start:end].split()) + "..."
    return " ".join(text[start:end].split())


def _ngrams(text: str, n: int) -> set[str]:
    words = _WORD.findall(text)
    grams = set()
    for i in range(len(words) - n + 1):
        gram = words[i : i + n]
        if gram[0] in STOPWORDS or gram[-1] in STOPWORDS:
            continue
        if all(w in STOPWORDS or w in GENERIC for w in gram):
            continue
        if gram[-1] in GENERIC or gram[0] in GENERIC:
            continue
        grams.add(" ".join(gram))
    return grams


def core_phrases(positive: list[str], top: int = 12, min_share: float = 0.03) -> list[tuple[str, int]]:
    """Most common 2-3 word phrases across positive reviews (document frequency)."""
    df: Counter[str] = Counter()
    for text in positive:
        df.update(_ngrams(text, 2) | _ngrams(text, 3))
    floor = max(2, int(min_share * len(positive)))
    ranked = [(g, c) for g, c in df.most_common() if c >= floor]
    # Drop bigrams that are just a part of an equally common trigram
    out: list[tuple[str, int]] = []
    for g, c in ranked:
        if any(g in big and c <= bc * 1.2 for big, bc in out if len(big) > len(g)):
            continue
        out.append((g, c))
        if len(out) >= top:
            break
    return out


def liked_things(positive: list[str], top: int = 8) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for text in positive:
        seen = set()
        for m in _LIKED.finditer(text):
            phrase = " ".join(m.group(1).split()[:5]).strip(" -'")
            if phrase and phrase not in seen and phrase.split()[0] not in {"game", "it", "this"}:
                seen.add(phrase)
                counts[phrase] += 1
    return counts.most_common(top)


def weight(review: Review) -> float:
    """Reviews written after only a short playtime count less (0 = playtime unknown: full weight)."""
    short = 0 < review.playtime_minutes < config.SHORT_PLAYTIME_MINUTES
    return config.SHORT_PLAYTIME_WEIGHT if short else 1.0


def mine(negative: list[Review], positive: list[Review], quotes_per_category: int = 3,
         now: float | None = None) -> MiningResult:
    neg_clean = [clean(r.text) for r in negative]
    pos_clean = [clean(r.text) for r in positive]
    since = (now or time.time()) - 365 * 24 * 3600

    counts: Counter[str] = Counter()
    weighted: Counter[str] = Counter()
    recent: Counter[str] = Counter()
    quotes: dict[str, list[tuple[int, str]]] = {c.code: [] for c in CATEGORIES}
    idea = n_recent = 0
    for review, text in zip(negative, neg_clean):
        is_recent = review.timestamp >= since
        n_recent += is_recent
        for code, m in _hits(text).items():
            counts[code] += 1
            weighted[code] += weight(review)
            recent[code] += is_recent
            quotes[code].append((review.votes_up, _quote(m, text)))
        if _IDEA.search(text):
            idea += 1

    n = len(negative) or 1
    total_weight = sum(weight(r) for r in negative) or 1
    categories = []
    for cat in CATEGORIES:
        if not counts[cat.code]:
            continue
        best = sorted(quotes[cat.code], key=lambda q: -q[0])
        uniq = list(dict.fromkeys(q for _, q in best if len(q) > 25))[:quotes_per_category]
        categories.append(CategoryResult(
            code=cat.code, label=cat.label, pillar=cat.pillar, fixable=cat.fixable,
            count=counts[cat.code], share=weighted[cat.code] / total_weight, quotes=uniq,
            recent_share=recent[cat.code] / n_recent if n_recent >= config.RECENT_MIN_NEGATIVE else None,
        ))
    categories.sort(key=lambda c: -c.share)

    total_mentions = sum(weighted[c.code] for c in categories)
    fixable_mentions = sum(weighted[c.code] for c in categories if c.fixable)
    return MiningResult(
        n_negative=len(negative),
        n_positive=len(positive),
        n_recent_negative=n_recent,
        categories=categories,
        idea_praise_share=idea / n if negative else 0.0,
        fixability=fixable_mentions / total_mentions if total_mentions else 0.0,
        core_phrases=core_phrases(pos_clean),
        liked=liked_things(pos_clean),
    )
