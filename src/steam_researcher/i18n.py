"""Interface language: English (default) or Turkish.

Text is written in English in the code and looked up in `i18n_tr.TR` (English template -> Turkish
template) when the language is Turkish; a missing translation shows the English text.

    _("Only {n} game(s) passed the filters.", n=3)

Numbers are formatted by the template's format spec. In Turkish, `{x:,}` gives "1.460", `{x:.1f}`
gives "0,5" and `{x:.0%}` gives "%73", so both catalogs can use the same placeholders.

The language is per context (a web request, a background job, a CLI run): set it with `use("tr")`.
`N_("...")` marks text that is translated later, where it is shown (stored risk flags, labels).
"""

import contextlib
import string
from contextvars import ContextVar

LANGS = ("en", "tr")
LANG: ContextVar[str] = ContextVar("lang", default="en")
_SWAP = str.maketrans(",.", ".,")


class _TurkishNumbers(string.Formatter):
    def format_field(self, value, spec: str) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if spec.endswith("%"):
                return "%" + super().format_field(value * 100, spec[:-1] + "f").translate(_SWAP)
            if "," in spec or "." in spec:
                return super().format_field(value, spec).translate(_SWAP)
        return super().format_field(value, spec)


_TR_FORMAT = _TurkishNumbers()


def lang() -> str:
    return LANG.get()


def _(text: str, **params) -> str:
    """`text` in the current language, with `params` filled in."""
    if LANG.get() == "tr":
        from .i18n_tr import TR

        text = TR.get(text, text)
        return _TR_FORMAT.format(text, **params) if params else text
    return text.format(**params) if params else text  # no params: text may hold braces (game names)


def N_(text: str) -> str:
    """Marks text for translation without translating it now."""
    return text


def num(n: float) -> str:
    """A count with thousands separators: 1,460 in English, 1.460 in Turkish."""
    return f"{n:,}".translate(_SWAP) if LANG.get() == "tr" else f"{n:,}"


@contextlib.contextmanager
def use(language: str):
    """Run a block in `language` ("en" or "tr"; anything else means English)."""
    token = LANG.set(language if language in LANGS else "en")
    try:
        yield
    finally:
        LANG.reset(token)
