"""mining/llm.py (the Ollama calls the summaries use) with Ollama faked: no network, no GPU."""

import json

import httpx
import pytest

from market_researcher.mining import evaluate, llm


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


def test_post_chat_returns_the_answer():
    requests = []
    body = {"model": "gemma4:12b", "messages": []}
    assert json.loads(llm.post_chat(body, fake_ollama(lambda b: {"ok": True}, requests))) == {"ok": True}
    assert requests == [body]


def test_quotes_must_be_in_the_review():
    assert llm.grounded("can't  steer!!", "I CAN'T steer, at all")
    assert llm.grounded("联机体验极差", "5. 联机体验极差，国外国内")
    assert not llm.grounded("", "anything") and not llm.grounded("lag", "no problems here")


def test_thinking_is_off_or_low():
    assert llm.think_setting("qwen3:14b") is False and llm.think_setting("gemma4:12b") is False
    assert llm.think_setting("gpt-oss:20b") == "low" and llm.think_setting("gemma3:12b") is None


def test_missing_model_and_stopped_ollama_say_what_to_do():
    with pytest.raises(llm.LLMUnavailable, match="ollama pull gemma3:12b"):
        llm.post_chat({"model": "gemma3:12b"}, fake_ollama(None, status=404))

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    down = httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://ollama")
    with pytest.raises(llm.LLMUnavailable, match="isn't running"):
        llm.post_chat({"model": "gemma4:12b"}, down)


def test_detections_are_scored_against_the_labels():
    rows = [{"text": "a", "labels": ["bugs"], "idea_praise": True}, {"text": "b", "labels": [], "idea_praise": False}]
    scores, total = evaluate.evaluate(rows, [{"bugs", evaluate.IDEA}, {"controls"}])
    assert (total.tp, total.fp, total.fn) == (1, 1, 0)
    assert scores[evaluate.IDEA].tp == 1
