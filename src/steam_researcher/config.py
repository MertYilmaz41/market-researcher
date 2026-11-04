"""Defaults for the Underserved Audience method."""

from pathlib import Path

# Demand filter (step 2)
MIN_REVIEWS = 100
IDEAL_REVIEWS = 500

# Satisfaction filter (step 3): % positive
MIN_RATING = 5.0
MAX_RATING = 70.0

# Box Method review -> sales multipliers
BOX_LOW = 30
BOX_MID = 45
BOX_HIGH = 100

# Cache
CACHE_DIR = Path.home() / ".cache" / "steam-researcher"
CACHE_DB = CACHE_DIR / "steam_researcher.sqlite"
TTL_TAG_LIST = 24 * 3600
TTL_HISTOGRAM = 24 * 3600
TTL_APPDETAILS = 7 * 24 * 3600
TTL_REVIEWS = 24 * 3600

# Risk heuristics
SPIKE_LAUNCH_PERIODS = 2  # ignore the first N histogram periods (launch is always busy)
SPIKE_MEDIAN_FACTOR = 5.0  # period >= 5x the median period...
SPIKE_MIN_SHARE = 0.10  # ...and holds >= 10% of all reviews
SPIKE_MIN_REVIEWS = 50  # ...and has at least this many reviews
SPIKE_BOMB_NEGATIVE_SHARE = 0.6  # spike with >= 60% negative = review bomb
DEEP_DISCOUNT_PERCENT = 75
CHEAP_PRICE_USD = 1.0
NETCODE_CATEGORY_IDS = {
    20: "MMO",
    27: "Cross-Platform Multiplayer",
    36: "Online PvP",
    38: "Online Co-op",
}
NICHE_TAGS = {"VR", "Hentai", "Sexual Content", "NSFW", "Nudity", "Visual Novel", "Otome"}
SCOPE_MIN_SHARE = 0.10  # AAA comparisons in >= 10% of negative reviews
HARD_TAGS = {"Physics", "Open World", "MMORPG", "Massively Multiplayer"}

# Opportunity score: weighted geometric mean of [0,1] parts, x100, minus risk penalties
SCORE_WEIGHTS = {"demand": 0.40, "dissatisfaction": 0.35, "fixability": 0.25}
DEMAND_LOG_MIN = 1.5  # log10(reviews) mapped to 0 (~32 reviews)
DEMAND_LOG_MAX = 4.0  # ...and to 1 (10,000 reviews)
DEFAULT_FIXABILITY = 0.5  # when reviews couldn't be mined
RISK_PENALTIES = {  # points subtracted per flag; review bombs are handled via adjusted rating
    "streamer_spike": 10,
    "deep_discount": 10,
    "cheap_price": 10,
    "netcode": 15,
    "niche": 10,
    "scope_unrealistic": 10,
    "hard_tech": 5,
}
EXCLUDE_FLAGS = {"not_game"}

USER_AGENT = "steam-researcher/0.1 (hobby market research CLI)"
