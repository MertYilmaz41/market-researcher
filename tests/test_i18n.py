"""Turkish interface: every English text has a Turkish translation with the same placeholders."""

import ast
import string
from pathlib import Path

import pytest

from steam_researcher import config, i18n
from steam_researcher.i18n import _, num, use
from steam_researcher.i18n_tr import TR
from steam_researcher.mining.lexicon import CATEGORIES
from steam_researcher.models import CategoryResult, RiskFlag

PACKAGE = Path(i18n.__file__).parent


def python_texts() -> set[str]:
    """Every literal passed to _() or N_() in the package, plus text translated from data."""
    texts = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                texts.add(node.args[0].value)
    texts |= set(config.RISK_LABELS.values())
    texts |= {c.label for c in CATEGORIES} | {c.pillar for c in CATEGORIES}
    texts |= {"still common lately", "less common lately", "rarely mentioned lately"}  # CategoryResult.trend
    return texts


def fields(template: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(template) if name is not None}


def test_every_python_text_is_translated():
    missing = sorted(t for t in python_texts() if t not in TR)
    assert not missing, "add to i18n_tr.TR:\n" + "\n".join(missing)


@pytest.mark.parametrize("english", sorted(python_texts() & TR.keys()))
def test_translation_keeps_placeholders(english):
    assert fields(TR[english]) == fields(english)


def test_trend_texts_match_the_model():
    trends = {CategoryResult(code="x", label="x", pillar="x", fixable=True, count=1, share=s, recent_share=r).trend
              for s, r in [(0.5, 0.5), (0.5, 0.25), (0.5, 0.1)]}
    assert trends == {"still common lately", "less common lately", "rarely mentioned lately"}


def test_english_by_default_turkish_on_request():
    assert _("Analysis complete") == "Analysis complete"
    with use("tr"):
        assert _("Analysis complete") == TR["Analysis complete"]
    with use("xx"):  # unknown language: English
        assert _("Analysis complete") == "Analysis complete"


def test_turkish_number_format():
    with use("tr"):
        assert num(1460) == "1.460"
        assert i18n._TR_FORMAT.format("{n:,} {s:.0%} {r:.1f} {p:.1%}", n=11224, s=0.73, r=4.5, p=0.012) \
            == "11.224 %73 4,5 %1,2"
    assert num(1460) == "1,460"


def test_risk_flag_text_follows_language_and_old_runs_still_show():
    flag = RiskFlag.make("deep_discount", "warn", "Currently {discount}% off. Review counts may be inflated by deep sales.",
                         discount=80)
    assert flag.message == flag.text() == "Currently 80% off. Review counts may be inflated by deep sales."
    with use("tr"):
        assert flag.text() != flag.message and "80" in flag.text()
    old = RiskFlag(code="deep_discount", severity="warn", message="saved before templates")
    with use("tr"):
        assert old.text() == "saved before templates"
