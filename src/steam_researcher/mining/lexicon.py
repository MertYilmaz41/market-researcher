"""Keyword lexicon for complaint categories.

Each pattern is a regex fragment matched with word boundaries on lowercased text.
`negatable` categories ignore matches preceded by a negation ("no bugs", "never crashed").
Pillars follow CodeMonkey's "Turning Complaints into Design Pillars".
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    pillar: str
    fixable: bool  # can a small indie team fix this?
    negatable: bool
    patterns: tuple[str, ...]


CATEGORIES: tuple[Category, ...] = (
    Category(
        "controls", "Bad controls / clunky feel",
        "Satisfying, tactile interactions", True, False,
        (r"controls?", r"clunky", r"janky", r"jank", r"unresponsive", r"stiff", r"awkward",
         r"floaty", r"sluggish", r"input lag", r"keybind(?:ing)?s?", r"rebind",
         r"camera (?:is|was) (?:bad|awful|terrible|annoying)", r"hard to control", r"steering (?:is|was|feels)",
         r"physics (?:is|are|was|were) (?:bad|terrible|awful|broken|weird|janky)"),
    ),
    Category(
        "bugs", "Game-breaking bugs",
        "Flawless execution and polish", True, True,
        (r"bugs?", r"buggy", r"glitch(?:es|y)?", r"crash(?:es|ed|ing)?", r"broken", r"freez(?:e|es|ing)",
         r"soft ?lock(?:ed)?", r"stuck", r"save (?:file )?(?:corrupt\w*|lost|deleted)", r"lost (?:my )?progress",
         r"game[- ]breaking", r"unplayable", r"doesn'?t work", r"not working"),
    ),
    Category(
        "ui_ux", "Confusing UI / UX",
        "Seamless, intuitive UX as a selling point", True, False,
        (r"ui", r"user interface", r"interface", r"menus?", r"hud", r"confusing", r"unintuitive",
         r"not intuitive", r"(?:no|bad|poor|useless|terrible) tutorial", r"lack of (?:a )?tutorial",
         r"tutorial (?:is|was) (?:bad|useless|lacking|confusing|terrible)", r"no explanation",
         r"doesn'?t explain", r"hard to (?:understand|figure)", r"no idea (?:what|how)"),
    ),
    Category(
        "content", "Too little content / shallow progression",
        "Deep, early progression systems", True, False,
        (r"repetitive", r"boring", r"grind(?:y|ing)?", r"shallow", r"no content", r"lack of content",
         r"not enough (?:content|to do|variety)", r"nothing to do", r"(?:only|just) (?:a few|one|two) (?:levels?|maps?|missions?|jobs?)",
         r"no progression", r"progression", r"same thing", r"gets old", r"(?:short|done) (?:in|after) \d+ (?:hours?|minutes?|mins?)",
         r"overpriced", r"not worth", r"waste of money", r"too short"),
    ),
    Category(
        "performance", "Poor performance / optimization",
        "Smooth performance on modest hardware", True, True,
        (r"fps", r"frame ?rate", r"stutter(?:s|ing)?", r"lag(?:gy|s)?", r"optimi[sz](?:ed|ation)",
         r"unoptimi[sz]ed", r"(?:poor|bad|terrible|awful) performance", r"performance (?:issues?|problems?|is (?:bad|terrible|awful))", r"loading (?:times?|screens?)", r"runs (?:like|poorly|terribly)"),
    ),
    Category(
        "abandoned", "Abandoned by developers / no updates",
        "Ship complete, then keep updating and talking to players", True, False,
        (r"abandon(?:ed|ware)?", r"no updates?", r"(?:dev|devs|developers?) (?:left|gave up|disappeared|stopped)",
         r"dead game", r"stopped updating", r"never (?:finished|updated)", r"still in early access",
         r"early access (?:forever|scam)", r"cash ?grab", r"unfinished"),
    ),
    Category(
        "realism", "Not a real simulation / unrealistic",
        "Authentic simulation depth in the core activity", True, False,
        (r"unrealistic", r"not realistic", r"not (?:a|really a) sim(?:ulator|ulation)?", r"nowhere near a sim\w*",
         r"arcade(?:y)?", r"not accurate", r"inaccurate"),
    ),
    Category(
        "scope_unrealistic", "Players expect AAA-scale scope",
        "Out of indie scope: don't chase it, position the game honestly", False, False,
        (r"gta", r"grand theft auto", r"red dead", r"cyberpunk", r"skyrim", r"star citizen",
         r"aaa", r"triple[- ]a", r"(?:should|could) be (?:like|as big as)"),
    ),
)

NEGATION = r"\b(?:no|not|never|without|zero|isn'?t|wasn'?t|aren'?t|didn'?t|haven'?t|hasn'?t)\b(?:\W+\w+){0,2}\W+$"

# Players praising the idea while panning the game: the "great idea, bad execution" signal.
IDEA_PRAISE = (
    r"(?:great|good|nice|cool|fun|interesting|amazing|awesome) (?:idea|concept|premise)",
    r"(?:has|had|so much|lot of|lots of) potential", r"potential",
    r"wanted to (?:like|love|enjoy)", r"want(?:ed)? to recommend", r"(?:love|like)d? the (?:idea|concept)",
    r"could (?:have been|be) (?:great|good|amazing|fun)",
)
