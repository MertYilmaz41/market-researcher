"""Calls to a local LLM (Ollama) for the opportunity and game summaries (summary.py).

Complaint detection with an LLM was measured here too (classify, verify, fill) and never adopted; that
code was removed in Nov 2026. Its results are in CLAUDE.md ("Review mining is keyword-only").
"""

import re

import httpx

from .. import config


class LLMUnavailable(RuntimeError):
    """Ollama isn't running (missing_model is None), or the model isn't downloaded."""

    def __init__(self, message: str, missing_model: str | None = None):
        super().__init__(message)
        self.missing_model = missing_model


def think_setting(model: str) -> bool | str | None:
    """Ollama's `think` for a model, or None to leave it out (a model without thinking rejects it).
    Thinking makes Qwen3 several times slower and doesn't help the summaries."""
    if model.startswith(("qwen3", "gemma4")):  # qwen3, qwen3.5 and gemma4 can think; gemma3 can't
        return False
    if model.startswith("gpt-oss"):
        return "low"  # gpt-oss can't turn thinking off, only down
    return None


def _squash(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def grounded(quote: str, review: str) -> bool:
    """Does the model's quote really appear in the review? (Ignores case and punctuation.)"""
    q = _squash(quote)
    return bool(q) and q in _squash(review)


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
