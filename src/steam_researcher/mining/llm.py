"""Complaint detection with a local LLM (Ollama), an alternative to the keyword lexicon.

    ollama pull qwen3:14b
    uv run python -m steam_researcher.mining.evaluate --miner llm --model qwen3:14b

classify() returns the same codes as the keyword miner (mining/lexicon.py categories, plus
"idea_praise"), so evaluate.py scores both against the same hand-labeled reviews. Reviews are sent
in small batches; Ollama's structured output (a JSON schema) keeps the answer parseable.
verify() is the other way round: the keywords find candidates, and the model may only drop them
(evaluate --miner verify).
"""

import json
import re

import httpx

from .. import config
from .lexicon import CATEGORIES

IDEA = "idea_praise"
MAX_CHARS = 1500  # long reviews say their complaints early; keeps a batch inside the context window

# What each category means, written for the model. Matches how tests/fixtures/labeled_reviews*.jsonl
# were labeled (e.g. a game still unfinished years after release is "abandoned", not "content").
DEFINITIONS = {
    "controls": "controls, camera, steering, movement or physics feel clunky, unresponsive, awkward or hard to handle",
    "bugs": "bugs, glitches, crashes, freezes, getting stuck, broken features, lost saves, or the game won't start",
    "ui_ux": "only the interface itself: confusing menus or screens, missing or poor tutorial, the game doesn't "
             "explain what to do. Boring or tedious gameplay is content, not ui_ux",
    "content": "too little to do, too short, repetitive or tedious gameplay, shallow progression, missing features",
    "performance": "only technical speed on the player's computer: low frame rate, stutter, long loading, poor "
                   "optimization. Not online connection problems",
    "abandoned": "developers stopped updating or supporting it, unfinished for years, broken promises or roadmap, "
                 "devs ignore players, cash grab",
    "realism": "not a real or authentic simulation of its activity, unrealistic or arcade-like mechanics or details",
    "scope_unrealistic": "expects AAA scale an indie can't deliver, e.g. compares it to GTA or wants a huge open world",
}

SYSTEM = """You label negative Steam game reviews for a game designer.
For each review, list the complaint categories the reviewer clearly states about this game. Most
reviews have one or two; many have none. Be strict: when in doubt, leave a category out.
For every category, copy the exact words from the review that state the complaint (a short phrase,
in the review's own language). If you can't point to such words, don't use the category.

Not complaints (no category): the developer's opinions or controversies (but a developer that stopped
updating or supporting the game is abandoned); the price;
refund stories; what other games do better; things the reviewer liked; "no bugs at all".
Reviews can be in any language.

Categories:
{categories}

Also set idea_praise to true when the reviewer, while recommending against the game, praises its
idea, concept or potential ("great concept but...", "I wanted to love it", "so much potential").

Answer with JSON only."""

VERIFY_SYSTEM = """You check complaint labels on negative Steam game reviews for a game designer.
A keyword search flagged each review with candidate categories. For each candidate, decide whether
the reviewer really complains about that in this game. Keep it only if so, and copy the exact words
from the review that state the complaint. Drop a candidate when its words are used otherwise: praise
("the controls feel great"), another game, a negation ("no bugs at all"), or a passing mention.
Never add a category that isn't a candidate.

Categories:
{categories}

Answer with JSON only."""


class LLMUnavailable(RuntimeError):
    """Ollama isn't running (missing_model is None), or the model isn't downloaded."""

    def __init__(self, message: str, missing_model: str | None = None):
        super().__init__(message)
        self.missing_model = missing_model


def system_prompt() -> str:
    return SYSTEM.format(categories="\n".join(f"- {c.code}: {DEFINITIONS[c.code]}" for c in CATEGORIES))


def schema() -> dict:
    return {
        "type": "object",
        "properties": {"reviews": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "review": {"type": "integer"},
                "complaints": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"category": {"type": "string", "enum": [c.code for c in CATEGORIES]},
                                   "quote": {"type": "string"}},
                    "required": ["category", "quote"],
                }},
                "idea_praise": {"type": "boolean"},
            },
            "required": ["review", "complaints", "idea_praise"],
        }}},
        "required": ["reviews"],
    }


def _request(texts: list[str], model: str) -> dict:
    numbered = "\n\n".join(f"Review {i}:\n{t[:MAX_CHARS]}" for i, t in enumerate(texts, 1))
    return _body(model, system_prompt(), f"Label these {len(texts)} reviews.\n\n{numbered}", schema())


def think_setting(model: str) -> bool | str | None:
    """Ollama's `think` for a model, or None to leave it out (a model without thinking rejects it).
    Thinking makes Qwen3 several times slower and helps neither labeling nor summaries."""
    if model.startswith(("qwen3", "gemma4")):  # qwen3, qwen3.5 and gemma4 can think; gemma3 can't
        return False
    if model.startswith("gpt-oss"):
        return "low"  # gpt-oss can't turn thinking off, only down
    return None


def _body(model: str, system: str, user: str, fmt: dict) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": fmt,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192},
    }
    if (think := think_setting(model)) is not None:
        body["think"] = think
    return body


def _squash(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def grounded(quote: str, review: str) -> bool:
    """Does the model's quote really appear in the review? (Ignores case and punctuation.)"""
    q = _squash(quote)
    return bool(q) and q in _squash(review)


def parse(content: str, texts: list[str]) -> list[set[str]]:
    """The model's JSON answer -> one set of codes per review. Unknown codes and indexes are dropped,
    and so is a complaint whose quote isn't in the review (the model made it up)."""
    known = {c.code for c in CATEGORIES}
    out: list[set[str]] = [set() for _ in texts]
    for item in json.loads(content).get("reviews", []):
        i = item.get("review")
        if not isinstance(i, int) or not 1 <= i <= len(texts):
            continue
        for c in item.get("complaints", []):
            if isinstance(c, dict) and c.get("category") in known and grounded(c.get("quote", ""), texts[i - 1]):
                out[i - 1].add(c["category"])
        if item.get("idea_praise") is True:
            out[i - 1].add(IDEA)
    return out


def post_chat(body: dict, client: httpx.Client | None = None) -> str:
    """Send one /api/chat request to Ollama; returns the answer's content (JSON text)."""
    client = client or httpx.Client(base_url=config.LLM_URL, timeout=600)
    try:
        res = client.post("/api/chat", json=body)
    except httpx.ConnectError:
        raise LLMUnavailable(f"Ollama isn't running at {config.LLM_URL}. Start the Ollama app.") from None
    if res.status_code == 404:
        model = body["model"]
        raise LLMUnavailable(f"The model {model} isn't downloaded. Run: ollama pull {model}", model)
    res.raise_for_status()
    return res.json()["message"]["content"]


def classify(texts: list[str], model: str = config.LLM_MODEL, *, client: httpx.Client | None = None,
             batch: int = config.LLM_BATCH) -> list[set[str]]:
    """Complaint codes (plus IDEA) found in each review, in order."""
    client = client or httpx.Client(base_url=config.LLM_URL, timeout=600)
    found: list[set[str]] = []
    for start in range(0, len(texts), batch):
        chunk = texts[start:start + batch]
        content = post_chat(_request(chunk, model), client)
        found += parse(content, [t[:MAX_CHARS] for t in chunk])
    return found


def verify_schema() -> dict:
    return {
        "type": "object",
        "properties": {"reviews": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "review": {"type": "integer"},
                "keep": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"category": {"type": "string", "enum": [c.code for c in CATEGORIES]},
                                   "quote": {"type": "string"}},
                    "required": ["category", "quote"],
                }},
            },
            "required": ["review", "keep"],
        }}},
        "required": ["reviews"],
    }


def _verify_request(texts: list[str], candidates: list[set[str]], model: str) -> dict:
    system = VERIFY_SYSTEM.format(categories="\n".join(f"- {c.code}: {DEFINITIONS[c.code]}" for c in CATEGORIES))
    numbered = "\n\n".join(f"Review {i}:\nCandidates: {', '.join(sorted(c))}\n{t[:MAX_CHARS]}"
                           for i, (t, c) in enumerate(zip(texts, candidates), 1))
    return _body(model, system, f"Check the candidates of these {len(texts)} reviews.\n\n{numbered}", verify_schema())


def parse_verified(content: str, texts: list[str], candidates: list[set[str]]) -> list[set[str]]:
    """The model's JSON answer -> the candidates it kept, per review. A code that wasn't a candidate,
    or whose quote isn't in the review, is not kept."""
    out: list[set[str]] = [set() for _ in texts]
    for item in json.loads(content).get("reviews", []):
        i = item.get("review")
        if not isinstance(i, int) or not 1 <= i <= len(texts):
            continue
        for c in item.get("keep", []):
            if isinstance(c, dict) and c.get("category") in candidates[i - 1] and grounded(c.get("quote", ""), texts[i - 1]):
                out[i - 1].add(c["category"])
    return out


def verify(texts: list[str], found: list[set[str]], model: str = config.LLM_MODEL, *,
           client: httpx.Client | None = None, batch: int = config.LLM_BATCH) -> list[set[str]]:
    """The keyword detections with the ones the model rejects dropped. IDEA is passed through as is;
    reviews without a complaint candidate aren't sent."""
    client = client or httpx.Client(base_url=config.LLM_URL, timeout=600)
    out = [{IDEA} & f for f in found]
    todo = [i for i, f in enumerate(found) if f - {IDEA}]
    for start in range(0, len(todo), batch):
        idx = todo[start:start + batch]
        chunk = [texts[i][:MAX_CHARS] for i in idx]
        cands = [found[i] - {IDEA} for i in idx]
        content = post_chat(_verify_request(chunk, cands, model), client)
        for i, kept in zip(idx, parse_verified(content, chunk, cands)):
            out[i] |= kept
    return out


def vram_share(model: str, client: httpx.Client | None = None) -> float | None:
    """How much of the loaded model sits in GPU memory (1.0 = all of it), from Ollama's /api/ps."""
    client = client or httpx.Client(base_url=config.LLM_URL, timeout=10)
    try:
        for m in client.get("/api/ps").json().get("models", []):
            if m.get("name") == model or m.get("model") == model:
                return m["size_vram"] / m["size"] if m.get("size") else None
    except httpx.HTTPError:
        return None
    return None
