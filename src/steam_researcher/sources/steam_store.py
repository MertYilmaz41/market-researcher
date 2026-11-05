"""Steam store endpoints: appdetails, review histogram, review texts, tag catalog."""

import json

from .. import config
from ..http import HttpClient
from ..models import AppDetails, HistPoint, Review

STORE = "https://store.steampowered.com"


def parse_app_details(appid: int, data: dict) -> AppDetails | None:
    entry = data.get(str(appid)) or {}
    if not entry.get("success"):
        return None  # delisted, region-locked or unknown appid
    d = entry["data"]
    price = d.get("price_overview") or {}
    cats = d.get("categories") or []
    release = d.get("release_date") or {}
    return AppDetails(
        appid=appid,
        type=d.get("type", ""),
        name=d.get("name", ""),
        is_free=bool(d.get("is_free")),
        price_initial_cents=price.get("initial", 0),
        price_final_cents=price.get("final", 0),
        discount_percent=price.get("discount_percent", 0),
        category_ids=[c["id"] for c in cats],
        categories=[c["description"] for c in cats],
        release_date=release.get("date", ""),
        coming_soon=bool(release.get("coming_soon")),
    )


def app_details(http: HttpClient, appid: int) -> AppDetails | None:
    data = http.get_json(
        f"{STORE}/api/appdetails",
        {"appids": appid, "cc": "us", "l": "english"},
        ttl=config.TTL_APPDETAILS,
    )
    return parse_app_details(appid, data or {})


def parse_histogram(data: dict) -> list[HistPoint]:
    rollups = (data.get("results") or {}).get("rollups") or []
    return [
        HistPoint(date=r["date"], up=r["recommendations_up"], down=r["recommendations_down"])
        for r in rollups
    ]


def review_histogram(http: HttpClient, appid: int) -> list[HistPoint]:
    data = http.get_json(
        f"{STORE}/appreviewhistogram/{appid}",
        {"l": "english", "review_score_preference": 0},
        ttl=config.TTL_HISTOGRAM,
    )
    return parse_histogram(data or {})


REVIEWS_API = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
# store.steampowered.com/appreviews was retired in Oct 2026 (redirects to the homepage).
# Its replacement takes protobuf-style params in `input_json`; review_type is numeric.
REVIEW_TYPES = {"all": 0, "positive": 1, "negative": 2}


def parse_reviews(data: dict) -> list[Review]:
    return [
        Review(
            recommendation_id=str(r.get("recommendationid", "")),
            text=r.get("review", ""),
            voted_up=bool(r.get("voted_up")),
            votes_up=r.get("votes_up", 0),
            playtime_minutes=(r.get("author") or {}).get("playtime_forever", 0),
            timestamp=r.get("timestamp_created", 0),
        )
        for r in data.get("reviews") or []
    ]


def reviews(
    http: HttpClient,
    appid: int,
    review_type: str = "negative",  # "negative" | "positive" | "all"
    limit: int = 300,
    language: str = "english",
    order: str = "all",  # "all" = most helpful first, "recent" = newest first
) -> list[Review]:
    """Page through review texts (all time) until `limit` is reached."""
    out: list[Review] = []
    cursor = "*"
    while len(out) < limit:
        query = {
            "appid": appid,
            "filter": order,
            "day_range": 0,  # 0 = all time; the default is only the last 30 days
            "review_type": REVIEW_TYPES[review_type],
            "language": language,
            "purchase_type": "all",
            "num_per_page": min(100, limit - len(out)),
            "cursor": cursor,
        }
        data = http.get_json(
            REVIEWS_API, {"input_json": json.dumps(query, sort_keys=True)}, ttl=config.TTL_REVIEWS
        )
        resp = (data or {}).get("response") or {}
        page = parse_reviews(resp)
        out.extend(page)
        next_cursor = resp.get("cursor")
        if not page or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return out[:limit]


TAGS_API = "https://api.steampowered.com/IStoreService/GetTagList/v1/"


def parse_tag_ids(data: dict) -> dict[str, int]:
    """Steam tag name -> tag id."""
    tags = ((data or {}).get("response") or {}).get("tags") or []
    return {t["name"].strip(): t["tagid"] for t in tags if (t.get("name") or "").strip() and t.get("tagid")}


def parse_tag_list(data: dict) -> list[str]:
    tags = ((data or {}).get("response") or {}).get("tags") or []
    names = {t["name"].strip() for t in tags if (t.get("name") or "").strip()}
    return sorted(names, key=str.casefold)


def _tag_catalog(http: HttpClient) -> dict:
    return http.get_json(TAGS_API, {"language": "english"}, ttl=config.TTL_TAG_NAMES)


def tag_names(http: HttpClient) -> list[str]:
    """All Steam user tags (about 450), A-Z. pipeline.tag_games finds their games on SteamSpy, or via
    Steam's store search for the tags SteamSpy can't search."""
    return parse_tag_list(_tag_catalog(http))


def tag_ids(http: HttpClient) -> dict[str, int]:
    return parse_tag_ids(_tag_catalog(http))
