from pydantic import BaseModel, computed_field

from . import config


class Game(BaseModel):
    appid: int
    name: str
    developer: str = ""
    publisher: str = ""
    positive: int
    negative: int
    price_cents: int = 0
    initial_price_cents: int = 0
    discount: int = 0
    owners: str = ""
    ccu: int = 0
    tags: dict[str, int] = {}  # only filled by SteamSpy appdetails
    # Where positive/negative come from: "steamspy" (search results), or for analyzed games "steam"
    # (Steam's own All Reviews number) or "histogram" (Steam's monthly review counts, a fallback).
    rating_source: str = "steamspy"
    steamspy_rating: float | None = None  # SteamSpy's % positive, kept when replaced by Steam's
    # Reviews from off-topic (review-bomb) periods Steam leaves out of its rating: they count toward
    # demand and the Box Method (the reviewers bought the game), not toward % positive.
    offtopic_reviews: int = 0

    @computed_field
    @property
    def reviews(self) -> int:
        return self.positive + self.negative + self.offtopic_reviews

    @computed_field
    @property
    def rating(self) -> float:
        """Percent positive (0-100)."""
        rated = self.positive + self.negative
        return 100.0 * self.positive / rated if rated else 0.0

    @property
    def base_price(self) -> float:
        """Undiscounted price in USD (falls back to current price)."""
        return (self.initial_price_cents or self.price_cents) / 100

    @property
    def store_url(self) -> str:
        return f"https://store.steampowered.com/app/{self.appid}/"


class AppDetails(BaseModel):
    """Steam store appdetails (subset)."""

    appid: int
    type: str  # "game", "dlc", "demo", "music", ...
    name: str
    is_free: bool = False
    price_initial_cents: int = 0
    price_final_cents: int = 0
    discount_percent: int = 0
    category_ids: list[int] = []
    categories: list[str] = []
    release_date: str = ""
    coming_soon: bool = False


class HistPoint(BaseModel):
    """One period (usually a month) of the review histogram."""

    date: int  # unix timestamp, start of period
    up: int
    down: int

    @property
    def total(self) -> int:
        return self.up + self.down


class Review(BaseModel):
    recommendation_id: str
    text: str
    voted_up: bool
    votes_up: int = 0
    playtime_minutes: int = 0
    timestamp: int = 0


class RiskFlag(BaseModel):
    code: str  # e.g. "review_bomb", "streamer_spike", "deep_discount", "netcode", "niche"
    severity: str  # "info" | "warn" | "high"
    message: str  # in English
    # The English template and its values, so the message can be shown in any language later
    # (flags are stored in saved runs). Runs saved before Nov 2026 have neither: text() uses message.
    template: str = ""
    params: dict = {}

    @classmethod
    def make(cls, code: str, severity: str, template: str, **params) -> "RiskFlag":
        return cls(code=code, severity=severity, message=template.format(**params), template=template, params=params)

    def text(self) -> str:
        """The message in the current interface language."""
        from .i18n import _

        return _(self.template, **self.params) if self.template else self.message


class CategoryResult(BaseModel):
    code: str
    label: str
    pillar: str
    fixable: bool
    count: int  # negative reviews mentioning this category
    share: float  # playtime-weighted share of negative reviews analyzed
    quotes: list[str] = []
    recent_share: float | None = None  # share of the sample's negative reviews from the last 12 months

    @computed_field
    @property
    def trend(self) -> str:
        """Is this complaint still made lately? Empty when too few recent reviews to tell."""
        if self.recent_share is None:
            return ""
        if self.recent_share >= 0.75 * self.share:
            return "still common lately"
        if self.recent_share <= 0.4 * self.share:
            return "rarely mentioned lately"
        return "less common lately"


class MiningResult(BaseModel):
    n_negative: int
    n_positive: int
    n_recent_negative: int = 0  # negative reviews in the sample from the last 12 months
    categories: list[CategoryResult]  # most mentioned first
    idea_praise_share: float  # negative reviews that still praise the idea/potential
    fixability: float  # share of complaint mentions a small team can fix
    core_phrases: list[tuple[str, int]]  # common phrases in positive reviews
    liked: list[tuple[str, int]]  # "loved the X" captures from positive reviews


class Opportunity(BaseModel):
    score: float  # 0-100
    demand: float  # 0-1
    dissatisfaction: float  # 0-1
    fixability: float  # 0-1
    effective_rating: float  # % positive used for scoring (review bombs removed)
    penalty: float
    penalized: list[str] = []  # flag codes that cost points


class Analysis(BaseModel):
    game: Game
    details: AppDetails | None
    histogram: list[HistPoint] = []
    flags: list[RiskFlag]
    mining: MiningResult | None
    review_error: str | None = None
    opportunity: Opportunity

    @property
    def has_histogram(self) -> bool:
        return bool(self.histogram)

    @property
    def excluded(self) -> bool:
        return any(f.code in config.EXCLUDE_FLAGS for f in self.flags)


class SummaryPoint(BaseModel):
    text: str
    games: list[str]  # names of the analyzed games the point rests on


class OpportunitySummary(BaseModel):
    """What a local LLM made of a tag run (summary.py): written text, no numbers change."""

    pitch: str = ""  # the opportunity in one sentence
    loved: list[SummaryPoint] = []  # what players like in these games
    complaints: list[SummaryPoint] = []  # shared complaints
    build: list[SummaryPoint] = []  # what a better game should do
    caveats: list[SummaryPoint] = []  # risks and limits
    model: str = ""
    seconds: float = 0.0


class OtherComplaint(BaseModel):
    text: str  # what these players complain about, in the interface language
    quote: str  # a review's own words (checked to be in one of the reviews the model read)


class GameSummary(BaseModel):
    """One game read by a local LLM (summary.write_game): written text, no numbers change."""

    why: str = ""  # why players are unhappy, one or two sentences
    fix: list[str] = []  # what a new game for these players should do differently
    other: list[OtherComplaint] = []  # complaints the keyword categories don't cover
    n_uncovered: int = 0  # negative reviews the model read because no category matched them
    model: str = ""
    seconds: float = 0.0


class BoxEstimate(BaseModel):
    units_low: int
    units_mid: int
    units_high: int
    gross_low: float
    gross_mid: float
    gross_high: float
