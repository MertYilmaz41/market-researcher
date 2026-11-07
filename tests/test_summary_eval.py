"""The checks that compare summary models (summary_eval.py): pure, no Ollama."""

import json

from market_researcher import summary, summary_eval
from market_researcher.mining import llm
from market_researcher.models import CategoryResult, MiningResult

from test_m4 import analysis


def _game(name, appid, cats=(), loved=True):
    a = analysis(50, name, appid=appid)
    a.mining = MiningResult(
        n_negative=40, n_positive=40, idea_praise_share=0, fixability=1,
        categories=[CategoryResult(code=c, label=c, pillar="", fixable=True, count=10, share=s) for c, s in cats],
        core_phrases=[("career mode", 5)] if loved else [], liked=[])
    return a


GAMES = {"Bus Sim": _game("Bus Sim", 1, [("bugs", 0.4), ("controls", 0.2)]),
         "Rail Sim": _game("Rail Sim", 2, [("content", 0.3)]),
         "Empty Sim": _game("Empty Sim", 3, loved=False)}


def _summary(**sections):
    raw = {"pitch": "Oyuncular iyi bir simülasyon istiyor.", **{s: [] for s in summary.SECTIONS}, **sections}
    content = json.dumps(raw)
    return raw, summary.parse(content, list(GAMES))


def test_categories_are_read_from_turkish_and_english_words():
    assert summary_eval.categories_in("Oyunu bozan hatalar ve çökmeler") == {"bugs"}
    assert summary_eval.categories_in("Clunky controls and a confusing UI") == {"controls", "ui_ux"}
    assert summary_eval.categories_in("Kariyer modu seviliyor") == set()


def test_a_complaint_counts_only_where_the_evidence_has_it():
    point = lambda text, games: {"text": text, "games": games}  # noqa: E731
    raw, parsed = _summary(complaints=[point("Hatalar oyunu bozuyor", ["Bus Sim", "Rail Sim"]),
                                       point("Kontroller hantal", ["Bus Sim"]),
                                       point("Fiyat yüksek", ["Rail Sim"])],
                           loved=[point("Kariyer modu", ["Empty Sim"])])
    c = summary_eval.check(raw, parsed, GAMES)
    assert c.supported == 2  # bugs and controls in Bus Sim
    assert len(c.unsupported) == 2  # bugs in Rail Sim; "loved" for a game with no positive phrases
    assert c.unclassified == 1  # the price point names no category


def test_format_problems_and_removed_names():
    raw, parsed = _summary(pitch='[{"text": "x"}]',
                           complaints=[{"text": "Hatalar", "games": ["Made Up Game"]},
                                       {"text": "Hatalar", "games": ["Bus Sim", "Ghost"]}])
    c = summary_eval.check(raw, parsed, GAMES)
    assert "pitch is JSON, not text" in c.format_errors
    assert "loved: 0 points" in c.format_errors
    assert c.removed_names == ["Made Up Game", "Ghost"] and c.dropped_points == 1


def test_summaries_turn_thinking_off_like_the_labeling():
    assert summary.request("x", "tr", "qwen3.5:9b")["think"] is False
    assert "think" not in summary.request("x", "tr", "gemma3:12b")
    assert summary.request("x", "tr", "gemma4:12b")["think"] is False
    assert llm.think_setting("gpt-oss:20b") == "low"


def test_only_the_complaints_the_model_read_count():
    many = _game("Many Sim", 4, [("bugs", 0.4), ("controls", 0.3), ("content", 0.2), ("ui_ux", 0.1), ("performance", 0.08)])
    raw = {"pitch": "x", **{s: [] for s in summary.SECTIONS},
           "complaints": [{"text": "Performans sorunları", "games": ["Many Sim"]}]}
    c = summary_eval.check(raw, summary.parse(json.dumps(raw), ["Many Sim"]), {"Many Sim": many})
    assert c.supported == 0 and len(c.unsupported) == 1  # 5th category: not in the evidence


def test_translation_errors_are_not_bugs():
    assert summary_eval.categories_in("Çeviri hataları oyunu zorlaştırıyor") == set()


def test_realism_counts_only_as_a_lack_of_it():
    assert summary_eval.categories_in("Integrate a campaign mode with realistic lore") == set()
    assert summary_eval.categories_in("Physics feel unrealistic") == {"realism"}
    assert summary_eval.categories_in("Fizikler gerçekçilikten uzak") == {"realism"}
