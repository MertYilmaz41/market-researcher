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


# ---- the web page: static/i18n.js holds the catalog for t("...") in the JS and data-i18n in index.html
STATIC = PACKAGE / "web" / "static"
JS_STRING = r'"((?:[^"\\]|\\.)*)"'


def js_catalog() -> dict[str, str]:
    import json
    import re

    body = (STATIC / "i18n.js").read_text(encoding="utf-8").split("const TR = {", 1)[1].split("\n};", 1)[0]
    pairs = re.findall(rf"^\s*{JS_STRING}:\s*{JS_STRING},?\s*$", body, re.M)
    return {json.loads(f'"{k}"'): json.loads(f'"{v}"') for k, v in pairs}


def page_texts() -> set[str]:
    """t("...") literals in the page's scripts, plus index.html's data-i18n text and attributes."""
    import json
    import re
    from html.parser import HTMLParser

    texts = set()
    for path in STATIC.glob("*.js"):
        texts |= {json.loads(f'"{m}"') for m in re.findall(rf"\bt\({JS_STRING}", path.read_text(encoding="utf-8"))}

    class Page(HTMLParser):
        def __init__(self):
            super().__init__()
            self.open: list[list] = []  # [tag, collected text or None]

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            for name in filter(None, (a.get("data-i18n-attr") or "").split(",")):
                texts.add(a[name])
            if tag not in ("input", "br", "meta", "link"):
                self.open.append([tag, [] if "data-i18n" in a else None])

        def handle_data(self, data):
            for _tag, buf in self.open:
                if buf is not None:
                    buf.append(data)

        def handle_endtag(self, tag):
            if tag in ("input", "br", "meta", "link"):
                return
            _tag, buf = self.open.pop()
            if buf is not None:
                texts.add(" ".join("".join(buf).split()))

    Page().feed((STATIC / "index.html").read_text(encoding="utf-8"))
    return texts


def test_every_page_text_is_translated():
    catalog = js_catalog()
    missing = sorted(t for t in page_texts() if t not in catalog)
    assert not missing, "add to TR in web/static/i18n.js:\n" + "\n".join(missing)


@pytest.mark.parametrize("english", sorted(page_texts()))
def test_page_translation_keeps_placeholders(english):
    catalog = js_catalog()
    if english in catalog:
        assert fields(catalog[english]) == fields(english)
