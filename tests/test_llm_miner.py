"""mining/llm.py with Ollama faked (no network, no GPU)."""

import json

import httpx
import pytest

from market_researcher.mining import evaluate, llm
from market_researcher.mining.lexicon import CATEGORIES


def fake_ollama(answer, requests=None, status=200):
    """An httpx client whose /api/chat answers with answer(request_body) (a dict -> JSON content)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if requests is not None:
            requests.append(body)
        if status != 200:
            return httpx.Response(status, json={"error": "model not found"})
        return httpx.Response(200, json={"message": {"content": json.dumps(answer(body))}})

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama")


def test_every_category_is_explained_to_the_model():
    prompt = llm.system_prompt()
    assert all(f"- {c.code}: " in prompt for c in CATEGORIES)
    complaint = llm.schema()["properties"]["reviews"]["items"]["properties"]["complaints"]["items"]
    assert complaint["properties"]["category"]["enum"] == [c.code for c in CATEGORIES]
    assert complaint["required"] == ["category", "quote"]


def test_parse_keeps_grounded_known_codes_in_review_order():
    texts = ["The controls are awful.", "Crashes every hour. Great concept though!", "Fine."]
    content = json.dumps({"reviews": [
        {"review": 2, "complaints": [{"category": "bugs", "quote": "crashes every hour"},
                                     {"category": "made_up", "quote": "Crashes"}], "idea_praise": True},
        {"review": 1, "complaints": [{"category": "controls", "quote": "controls are AWFUL!"},
                                     {"category": "performance", "quote": "low fps"}],  # not in the review
         "idea_praise": False},
        {"review": 9, "complaints": [{"category": "bugs", "quote": "Fine"}], "idea_praise": False},  # no such review
    ]})
    assert llm.parse(content, texts) == [{"controls"}, {"bugs", llm.IDEA}, set()]


def test_quotes_match_ignoring_case_and_punctuation():
    assert llm.grounded("can't  steer!!", "I CAN'T steer, at all")
    assert llm.grounded("联机体验极差", "5. 联机体验极差，国外国内")
    assert not llm.grounded("", "anything") and not llm.grounded("lag", "no problems here")


def test_classify_batches_and_numbers_reviews():
    requests = []

    def answer(body):
        n = body["messages"][1]["content"].count("Review ")
        return {"reviews": [{"review": i, "complaints": [{"category": "bugs", "quote": "text"}], "idea_praise": False}
                            for i in range(1, n + 1)]}

    found = llm.classify([f"text {i}" for i in range(10)], "qwen3:14b", client=fake_ollama(answer, requests), batch=4)
    assert found == [{"bugs"}] * 10
    assert len(requests) == 3  # 4 + 4 + 2
    assert requests[0]["think"] is False and requests[0]["options"]["temperature"] == 0
    assert "think" not in llm._request(["x"], "gemma3:12b")  # only Qwen3 and gpt-oss think
    assert llm._request(["x"], "gpt-oss:20b")["think"] == "low"


def test_verify_only_drops_keyword_candidates():
    requests = []
    texts = ["The controls feel great but it crashes.", "Boring and buggy. Great idea though.", "Nice game."]
    found = [{"controls", "bugs"}, {"content", "bugs", llm.IDEA}, {llm.IDEA}]

    def answer(body):
        return {"reviews": [
            {"review": 1, "keep": [{"category": "bugs", "quote": "it crashes"},
                                   {"category": "performance", "quote": "crashes"}]},  # not a candidate
            {"review": 2, "keep": [{"category": "content", "quote": "Boring"},
                                   {"category": "bugs", "quote": "glitchy"}]},  # quote not in the review
        ]}

    kept = llm.verify(texts, found, "gemma3:12b", client=fake_ollama(answer, requests))
    assert kept == [{"bugs"}, {"content", llm.IDEA}, {llm.IDEA}]
    assert len(requests) == 1 and "Candidates: bugs, controls" in requests[0]["messages"][1]["content"]
    assert "Nice game." not in requests[0]["messages"][1]["content"]  # nothing to check: not sent


def test_missing_model_and_stopped_ollama_say_what_to_do():
    with pytest.raises(llm.LLMUnavailable, match="ollama pull gemma3:12b"):
        llm.classify(["x"], "gemma3:12b", client=fake_ollama(None, status=404))

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    down = httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://ollama")
    with pytest.raises(llm.LLMUnavailable, match="isn't running"):
        llm.classify(["x"], client=down)


def test_llm_detections_are_scored_like_the_keyword_miner():
    rows = [{"text": "a", "labels": ["bugs"], "idea_praise": True}, {"text": "b", "labels": [], "idea_praise": False}]
    scores, total = evaluate.evaluate(rows, [{"bugs", llm.IDEA}, {"controls"}])
    assert (total.tp, total.fp, total.fn) == (1, 1, 0)
    assert scores[evaluate.IDEA].tp == 1
