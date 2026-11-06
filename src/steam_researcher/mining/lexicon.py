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
        (r"(?<!damage )(?<!good )(?<!great )(?<!tight )(?<!awesome )(?<!your )controls?(?! over| of | feel (?:great|good|tight))", r"control scheme", r"clunky", r"janky", r"jank", r"unresponsive", r"stiff", r"awkward",
         r"floaty", r"sluggish", r"input lag", r"keybind(?:ing)?s?", r"rebind",
         r"camera (?:is|was) (?:bad|awful|terrible|annoying)", r"invert(?:ed)? (?:camera|mouse|y)", r"hard to control",
         r"st(?:ee|ea)ring", r"sensitivity", r"wonky", r"handles like", r"feels? (?:\w+ )?(?:notchy|weird|off|floaty|heavy)",
         r"camera (?:\w+ ){0,2}(?:jumps|gets locked|is locked|is awful|sucks)", r"(?:bad|poor|terrible|awful|horrible) driving",
         r"driving (?:mechanics?|mechanism|model) (?:is|was|are|were) (?:\w+ )?(?:bad|poor|terrible|awful|horrible)",
         r"physics (?:is|are|was|were) (?:\w+ ){0,2}(?:bad|terrible|awful|broken|weird|janky|wonky|worst|horrible)",
         r"(?:bad|poor|terrible|awful|horrible|weird|broken|janky|wonky|no) (?:\w+ )?physics",
         r"bounc(?:es|ing|y)", r"back ?flips?", r"flipp(?:ed|ing)", r"on (?:its|it'?s|the|their) roof"),
    ),
    Category(
        "bugs", "Game-breaking bugs",
        "Flawless execution and polish", True, True,
        (r"bugs?", r"bugged", r"buggy", r"glitch(?:es|ed|y)?", r"crash(?:es|ed|ing)?(?! into)", r"broken(?! promises?)",
         r"freez(?:e|es|ing)|froze", r"soft ?(?:lock|block)(?:ed)?", r"clip(?:s|ping)? through",
         r"(?:get|gets|got|getting) stuck(?! in (?:the )?mud)", r"stuck (?:in|on|at|inside) (?:the |a |an )?(?:walls?|floor|doors?|terrain|ground|loading|menus?|tutorial|place|objects?)",
         r"(?:does not|doesn'?t|won'?t|wont|will not) (?:even )?(?:run|launch|start|open)",
         r"got (?:the game|it) to (?:work|run|launch|start|open)", r"save (?:file )?(?:corrupt\w*|lost|deleted)", r"lost (?:my )?progress",
         r"game[- ]breaking", r"unplayable", r"(?:doesn'?t|don'?t) (?:always )?work", r"not working"),
    ),
    Category(
        "ui_ux", "Confusing UI / UX",
        "Seamless, intuitive UX as a selling point", True, False,
        (r"ui", r"user interface", r"interface", r"(?<!main )menus?", r"hud", r"confusing", r"unintuitive",
         r"not intuitive", r"(?:no|bad|poor|useless|terrible) tutorial", r"lack of (?:a )?tutorial",
         r"tutorials? (?:is|was|are|were) (?:\w+ )?(?:bad|useless|lacking|confusing|terrible|unusable|awful|boring|broken)",
         r"tutorials? (?:does not|doesn'?t|did not|didn'?t) (?:\w+ )?(?:help|explain|do|work|teach)", r"no explanation",
         r"doesn'?t explain", r"hard to (?:understand|figure)", r"no idea (?:what|how)", r"figure out (?:what|how)",
         r"(?:does not|doesn'?t|did not|didn'?t) (?:tell|show) (?:you|me)", r"(?:is|are|was|were) not clear", r"unclear",
         r"(?:bad|poor|horrid|terrible|awful|broken|machine|half[- ]baked|missing) translat\w*|poorly translated|translation (?:is|was) (?:\w+ )?(?:bad|poor|terrible|awful|broken|half[- ]baked)",
         r"(?:badly|horribly|poorly) explained|not (?:\w+ )?explained|explained (?:badly|poorly)",
         r"(?:can'?t|cannot|unable to) (?:even )?(?:read|see) (?:the )?(?:text|codes|it|anything)", r"(?:change|set) the language|language (?:settings|options)"),
    ),
    Category(
        "content", "Too little content / shallow progression",
        "Deep, early progression systems", True, False,
        (r"repetitive", r"boring", r"boredom", r"tedious", r"grind(?:y|ing)?", r"shallow", r"(?:no|zero) content",
         r"lack(?:s|ing)? (?:of )?(?:content|features|depth|variety)", r"bare[- ]?bones", r"sparse", r"busy ?work",
         r"copy[ /-]?past(?:e|ed)", r"over and over", r"waiting around", r"(?:lot of|lots of|just|besides|only) waiting",
         r"wait(?:ing)? (?:for )?\d+ ?(?:mins?|minutes|hours?)", r"not (?:a lot|much|anything) to do", r"nothing in (?:it|them)",
         r"(?:feels?|felt|is|was|looks?) (?:so |very |pretty |really )?(?:empty|barren|lifeless|soulless|souless)",
         r"(?:bad|poor|horrible|terrible|awful|lazy) (?:level|map) design", r"(?:bad|horrible|terrible|boring|ugly) (?:maps|tracks|levels)",
         r"(?:painfully|agonizingly|exhaustingly|excruciatingly|incredibly) slow", r"slow and boring",
         r"(?:promised|missing) features", r"features (?:\w+ ){0,2}(?:are missing|were missing|don'?t exist|do not exist|never exist)",
         r"not enough (?:content|to do|variety)", r"nothing to do", r"(?:only|just) (?:a few|one|two) (?:levels?|maps?|missions?|jobs?)",
         r"(?:no|lack of|shallow|bad|poor|slow|grindy) progression",
         r"progression (?:is|feels|was) (?:\w+ )?(?:slow|bad|shallow|boring|grindy|lacking)", r"same thing", r"gets old", r"(?:short|done) (?:in|after) \d+ (?:hours?|minutes?|mins?)",
         r"overpriced", r"too short", r"rinse(?:,| and| &)? repeat", r"monoton\w*", r"repet+[ie]tive|repett?ative|repetition",
         r"tedium", r"dumbed down|watered down", r"hardly anything|almost nothing|barely anything",
         r"step backwards?|downgrade",
         r"(?:beat|finished|completed|done with) (?:\w+ ){0,2}in (?:about |under |like |less than )?(?:\d+|an?) (?:mins?|minutes|hours?|hrs?)",
         r"\d+(?:-\d+)? ?(?:hrs?|hours?) (?:\w+ )?(?:to complete|to completion|to beat)",
         r"(?:no|zero|little|barely any|without any) (?:\w+ )?(?:gameplay|replay ?(?:value|ability)|replayability|goals?|objectives?|challenge|reason to)"),
    ),
    Category(
        "performance", "Poor performance / optimization",
        "Smooth performance on modest hardware", True, True,
        (r"fps", r"frame ?rate", r"stutter(?:s|ing)?", r"lag(?:gy|s)?", r"(?:no|not|poorly|badly|zero|lack of) optimi[sz]\w*", r"optimi[sz](?:ed|ation)",
         r"unoptimi[sz]ed", r"(?:poor|bad|terrible|awful|atrocious|horrible|abysmal) performance",
         r"performance (?:issues?|problems?|crisis|is (?:bad|terrible|awful))", r"frames? (?:are|were|is|was) (?:\w+ )?(?:poor|bad|low|terrible)", r"loading (?:times?|screens?)", r"runs (?:\w+ )?(?:horribl\w*|horrific\w*|awful\w*|bad\w*|poorly|terribl\w*|like)", r"choppy", r"not smooth",
         r"(?:slow|long) loading|takes? (?:\w+ ){0,2}to load|wait(?:ing)? for (?:\w+ )?to load"),
    ),
    Category(
        "abandoned", "Abandoned by developers / no updates",
        "Ship complete, then keep updating and talking to players", True, False,
        (r"abb?andon\w*", r"no (?:more )?(?:\w+ ){0,2}updates?", r"not (?:being |having been |been )?updat(?:ed|ing)",
         r"remov(?:e|ed|ing) (?:\w+ ){0,2}(?:multiplayer|co-?op|online)", r"(?:took|taken) (?:\w+ )?(?:multiplayer|co-?op|online) out",
         r"(?:multiplayer|co-?op|online) (?:\w+ )?(?:removed|discontinued)", r"(?:no|not) (?:\w+ )?(?:mul\w*player|co-?op) anymore", r"(?:multiplayer|co-?op) (?:\w+ ){0,4}gone",
         r"nothing like (?:the |what )?(?:\w+ )?(?:trailer|advertised|promised|shown)",
         r"lack of (?:\w+ )?(?:developers?|devs?) (?:\w+ )?(?:support|communication|response)", r"lack of communication",
         r"(?:devs?|developers?) (?:don'?t|do not|doesn'?t|never) (?:\w+ )?(?:care|listen|respond)",
         r"(?:devs?|developers?) (?:\w+ ){0,2}(?:toxic|arrogant|banned)", r"(?:development|dev) (?:\w+ )?(?:ceased|halted|ended|stopped)",
         r"stopped development", r"without (?:ever )?finishing", r"(?:game|it) went offline",
         r"(?:sunset(?:ted|ting)?|shuttered|terminat(?:e|ed|ing)) (?:a |the |this |it\b|its )", r"(?:will|'ll|gonna|going to) be (?:\w+ )?(?:shut ?down|sunset\w*)", r"(?:devs?|developers?|studio|company) (?:\w+ ){0,2}(?:moved on|went bankrupt|shut down|closed)",
         r"servers? (?:\w+ ){0,2}(?:shut down|shutdown|offline|closed|turned off)", r"left (?:it )?to (?:rot|ruin|die)", r"delisted", r"removed from (?:the )?(?:steam|store)",
         r"(?:hasn'?t|haven'?t|has not|hadn'?t) (?:had |received |gotten |got |been )?(?:an? |any )?updat(?:e|es|ed)",
         r"(?:dev|devs|developers?|team) (?:\w+ )?(?:left|gave up|disappeared|stopped|bailed|quit|dropped)",
         r"(?:devs?|developers?|team) (?:are|is|went|have gone|has gone) (?:\w+ )?(?:silent|quiet)",
         r"dead game", r"(?:game|development) is dead", r"(?:dropped|abandoned) (?:the|this) game", r"stopped updating",
         r"never (?:finished|updated)", r"(?:not|never going to be|didn'?t|bother(?:ed)? to) finish(?:ed)?", r"finished half",
         r"half[- ](?:baked|finished)", r"incomplete", r"(?:ended|ending|stopped|dropped) (?:\w+ )?support",
         r"cancel(?:l?ed)? (?:the |this )?(?:game|development|project)", r"still in early access",
         r"(?:took|take|taking) (?:the |our |your |their |initial )*(?:money|profits?|cash) and (?:ran|run)", r"snatch and (?:run|grab)",
         r"early access (?:forever|scam)", r"(?:cash|money) ?grab", r"unfinished"),
    ),
    Category(
        "realism", "Not a real simulation / unrealistic",
        "Authentic simulation depth in the core activity", True, False,
        (r"unrealistic\w*", r"not realistic", r"not (?:a|an|really a) (?:\w+ )?sim(?:ulator|ulation)?", r"nowhere near a sim\w*",
         r"arcade-?y", r"(?:too|more|feels?|very|pure(?:ly)?) arcade", r"not accurate", r"inaccurate",
         r"lacks? (?:of )?realism", r"(?:a |an )?(?:real|actual|proper|true|realistic) (?:\w+ )?sim(?:ulator|ulation)?s?", r"lack of realism", r"no (?:physics |real )?simulation",
         r"realism (?:is|isn'?t|was|wasn'?t) (?:\w+ )?(?:there|lacking|missing|bad|poor|non-?existent)"),
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
    r"potential(?! (?:buyers?|customers?|players?))", r"(?:so much|a lot of|lots of|has|had|shows?) promise",
    r"want(?:ed)? to (?:like|love|enjoy)", r"want(?:ed)? to recommend", r"(?:love|like)d? the (?:\w+ ){0,2}(?:idea|concept)",
    r"(?:idea|concept|premise) (?:is|was) (?:\w+ )?(?:great|good|cool|nice|interesting|amazing|awesome|fun|there)",
    r"could (?:have|'?ve) (?:been|turned into|become) (?:something |a |an )?(?:really |very )?(?:great|good|nice|cool|fun|amazing|awesome)",
    r"could be (?:a |an )?(?:really |very )?(?:great|good|nice|amazing|fun)", r"what it(?:'s| is) trying to do",
    r"(?:great|good|solid) foundation", r"going for it", r"all the ingredients", r"good game (?:waiting|in there|somewhere)",
    # Praise of the game as a whole counts too (LABELING.md): "the game is fun, but...", "I loved this game"
    r"(?:game|it|gameplay) (?:is|was|'s|can be|seems?|looks?) (?:really |very |pretty |super |actually |so |quite |a lot of "
    r"|lots of |so much |genuinely |honestly )?(?:fun|great|good|solid|amazing|awesome|addictive|enjoyable|neat)",
    r"(?:i|we) (?:really |truly |absolutely |actually |do |genuinely )?(?:love|loved|like|liked|enjoy|enjoyed|adore|adored) "
    r"(?:this|the|playing (?:this|the)) game",
    r"(?:was|used to be) (?:so much |a lot of |lots of |really |very )?fun", r"(?:had|having) (?:a |so much |lots of |a lot of |some )?(?:blast|fun)",
    r"(?<!not a )(?<!not )(?:great|fun|solid|amazing|awesome) (?:game|gameplay)",
)
