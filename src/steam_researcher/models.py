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

    @computed_field
    @property
    def reviews(self) -> int:
        return self.positive + self.negative

    @computed_field
    @property
    def rating(self) -> float:
        """Percent positive (0-100)."""
        return 100.0 * self.positive / self.reviews if self.reviews else 0.0

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
    message: str


class CategoryResult(BaseModel):
    code: str
    label: str
    pillar: str
    fixable: bool
    count: int  # negative reviews mentioning this category
    share: float  # count / negative reviews analyzed
    quotes: list[str] = []


class MiningResult(BaseModel):
    n_negative: int
    n_positive: int
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


class BoxEstimate(BaseModel):
    units_low: int
    units_mid: int
    units_high: int
    gross_low: float
    gross_mid: float
    gross_high: float
