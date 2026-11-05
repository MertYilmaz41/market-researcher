# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## What this is

A Python CLI (`sr`) that automates CodeMonkey's "Underserved Audience" method: find Steam games with proven demand (many reviews) but poor satisfaction (5–70% positive) in a clear genre tag, estimate their revenue, mine their complaints, and rank them as opportunities. The method is described in `Underserved-Auidience.md`, and the requirements (in Turkish) are in `requirements-summary.txt`. Both files are local-only and gitignored, so they may be missing in a fresh clone. The full roadmap (milestones 1–5) is in `C:\Users\Mert\.claude\plans\first-read-underserved-auidience-md-and-polished-grove.md`.

## Commands

```
uv sync                                    # install deps into .venv
uv run pytest -q                           # all tests
uv run pytest tests/test_core.py::test_parse_and_filter   # single test
uv run sr discover --tag "Job Simulator" --min-reviews 100 --rating 5-70 --top 30
uv run sr discover --tag "Job Simulator" --no-cache
uv run sr discover -t Crafting -t Survival  # several tags: only games that have all of them
uv run sr analyze 2336220 --reviews 300     # risks, mining, score for one AppID
uv run sr report --tag "Job Simulator" --max-games 15 --reviews 200   # writes reports/job-simulator.md
uv run sr markets --top 30                  # rank every tag by underserved games (~7 min first time)
uv run sr runs                              # saved runs (from sr report and the web UI)
uv run sr ui                                # web UI (3D map) on http://localhost:8501
uv run sr cache clear
uv run --with playwright pytest tests/test_ui.py   # browser smoke test, if .venv lacks Playwright
```

Tag names are SteamSpy tag names (e.g. "Job Simulator", "Colony Sim"); matching is case-insensitive. Up to `config.MAX_TAGS` (5) tags per search.

## Architecture

`pipeline.py` holds the steps that `cli.py` commands share. `verify_games` enforces "Games Only". `analyze_game` builds an `Analysis` (game, details, flags, mining, `Opportunity`), and both `analyze` and `report` use it. Put new per-game logic in `analyze_game`, not in the CLI.

Scoring (`scoring.py`): 100 × the weighted geometric mean of demand (log of review count), dissatisfaction (how far below 70% positive) and fixability, minus fixed penalties per risk flag (`RISK_PENALTIES` in `config.py`).
- If any part is 0, the score is 0.
- Review bombs aren't penalized. Instead, `risk.rating_without_bombs` replaces the rating, so a review-bombed game that's otherwise fine scores 0.
- Flags in `EXCLUDE_FLAGS` (`not_game`) drop a game from the ranking entirely.

Web UI (`web/`): `sr ui` runs uvicorn on `web/server.py`, bound to 127.0.0.1, and opens the browser.
- **Server:** a FastAPI app that is display-only. `POST /api/tag-runs` starts `pipeline.run_tag` in a background thread; each job builds its own `HttpClient` because SQLite connections are per thread. Jobs live in an in-memory dict, and `GET /api/tag-runs/{id}` is polled for progress and the result. `GET /api/games/{appid}` runs `analyze_game` synchronously.
- **JSON:** `game_json()` adds `box`, `store_url`, `rating`, etc., so the frontend never re-implements any math.
- **Frontend:** `web/static/` is plain ES modules with no build step. `app.js` handles data, the table and the panel. The map has a 2D | 3D switch (remembered in localStorage). `map2d.js` is an SVG scatter (x = demand, y = dissatisfaction, size = revenue, color = score) that needs no CDN; `map3d.js` draws the three.js scene (plus z = fixability). Both get the same games and selection through the `map` wrapper in `app.js`, and if three.js or WebGL is missing, only 2D is offered. Colors come from `style.css :root` only, and `palette.js` reads them for the JS (score scale, map, charts). three.js is pinned to `three@0.170.0` in the import map in `index.html`.
- **Multiple tags:** a search takes a list of tags and keeps only games that have all of them (`pipeline.tag_games`: one SteamSpy request per tag, or Steam's store search for tags SteamSpy can't search). An unknown tag raises `pipeline.UnknownTag`. Titles, notices and report file names get one string, the label `pipeline.tag_label` ("Crafting + Survival"), so they need no changes.
- **Tag picker:** the tag field in `app.js` is a checklist dropdown. You tick tags with the mouse; the text box only filters the list. Ticked tags show as chips with an ×. The list is filled from `GET /api/tags`. That calls `steam_store.tag_names`, which uses Steam's `IStoreService/GetTagList` (about 450 tags, cached 7 days). If the list fails to load, the field falls back to comma-separated free text. Unknown tags are detected in `steamspy.games_by_tag`: SteamSpy answers them with the same fallback list as an empty tag. `notices.unknown_tag` then suggests close matches.
- **Score card:** hovering or focusing a score (table pill, panel ring, "How is this score calculated?") opens `#score-tip`, filled from `game_json()["score_explained"]` = `scoring.explain(analysis)`: each part with its weight and a plain-language basis, the combined value (`scoring.combine`, shared with `score()`), each penalty with its `config.RISK_LABELS` name and the flag's message, and the part that zeroed the score. Change wording there, not in JS.
- **Safety:** put review text into the DOM only via `textContent` (the `el()` helper in `app.js`), never `innerHTML`.
- **Market view** (`market.py`, pure): `market_stats(games, ...)` describes a whole tag from the game list a search already has: games, games with demand, underserved (in the % range), well served (`config.WELL_SERVED_RATING`, 85%+) and the gap (underserved / (underserved + well served)). `run_tag` stores it in `TagResult.market`; the web shows it as the Market strip above the ranking. `pipeline.run_markets` computes it for every tag SteamSpy can search (one request per tag, ~7 min first time, then cached) for `sr markets` and the web's Games | Markets switch; the slow Steam-store-search tags are skipped.
- **Saved runs** (`runs.py`): every finished web job and `sr report` run is saved to `config.RUNS_DB` (`~/.local/share/steam-researcher/runs.sqlite`, apart from the cache so `sr cache clear` keeps it). The result is stored as JSON via pydantic `TypeAdapter` and rebuilt on load, so `_job()` serves saved runs after a restart (report, CSV, "Past runs" in the UI). A tag run is compared with the last earlier run with the same tags (any order) and filters: `score_change`/`new` per game, shown as ▲/▼/new.
- **Tests:** `tests/test_web.py` uses FastAPI's `TestClient` with `pipeline.run_tag`/`analyze_game` monkeypatched, so it needs no network; an autouse fixture points `server._runs` at a temp DB. `tests/test_ui.py` drives the real app in a browser with Playwright (pipeline faked) and skips when Playwright or a browser is missing. Check JS syntax with `node --check`. CI (`.github/workflows/test.yml`) runs both on every push.

User-facing messages (validation, info, warnings, friendly errors) come from `notices.py` as `Notice(level, title, message, hint)`. The CLI and the web share them: the CLI prints them in color, and the web shows them as toasts (`toast`/`notify` in `app.js`). Add new cases in `notices.py`, not ad hoc in the UI; only instant field validation lives in JS. `friendly_error(exc)` turns exceptions into plain language. CLI commands are wrapped in `_guarded`, so no traceback is shown unless `SR_DEBUG=1`. `run_tag` records per-game failures in `TagResult.failed` and keeps going.

`report.py` renders `templates/report.md.j2` with Jinja2. Arbitrary text going into the template must pass through the `md` filter, which escapes pipes and flattens newlines.

The pipeline is `sources/*` (fetch) → `models.Game` (normalize) → `discover.filter_candidates` (steps 1–3) → `boxmethod.estimate` → output in `cli.py`.

`discover` also calls Steam appdetails for every result it shows, to enforce "Games Only" (SteamSpy has no type field). The first run of a tag is slow because of this, about 1.5s per game. `analyze` combines SteamSpy appdetails (which includes tags), Steam appdetails and the review histogram, then runs `risk.assess`. Each check in `risk.py` returns `RiskFlag`s, and its thresholds live in `config.py`. Spike detection skips the launch window. It labels a spike a review bomb when it is at least 60% negative, otherwise a streamer spike, and it reports the rating with spikes excluded. `risk.recent_activity` counts reviews in the last 12 months from the histogram (shown as "Last 12 mo"); a game 2+ years old with under 5% of its reviews in that window gets `fading_demand` (a score penalty).

`analyze` also mines reviews. `mining.mine(negative, positive)` returns a `MiningResult`. Complaint categories, their regex patterns and their design pillars are all data in `mining/lexicon.py`, so tune that file rather than the code.
- A category counts at most once per review, and `share` is that count divided by the number of negative reviews.
- Negation ("no bugs", "never crashed") is applied only to categories with `negatable=True`, because "not enough content" is still a complaint.
- Quotes come from the most helpful reviews (`votes_up`), windowed around the match.
- The core fantasy is two- and three-word phrases counted per review across positive reviews. Generic words are filtered by `STOPWORDS`/`GENERIC` in `mining/keywords.py`.
- `idea_praise_share` is the "great idea, bad execution" signal: negative reviews that still praise the idea or its potential.
- `fixability` is the share of complaint mentions in fixable categories. Milestone 4 scoring will use it.
- Known false positive: in driving games, "I crashed" is counted as a bug. Check changes to the lexicon against real reviews from `sr analyze`.

- **Parallel analysis:** `run_tag` analyzes games in a thread pool (`config.ANALYZE_WORKERS`), and each game starts as soon as it passes the store-type check. `HttpClient` and `Cache` are thread-safe: one request is in flight per host, so different hosts work in parallel. Steam's review API is sometimes very slow (20–90+ s per page, measured Nov 2026), so it has a shorter timeout (`HOST_TIMEOUT`). A failed review fetch sets `review_error` instead of dropping the game.
- **All network access goes through `http.HttpClient.get_json`.** It does per-host throttling (`HOST_INTERVAL`), tenacity retries on 429/5xx (other 4xx fail fast; empty responses are not cached), and caching in SQLite (`cache.Cache`, `~/.cache/steam-researcher/steam_researcher.sqlite`, TTLs in `config.py`). New data sources should be added as modules in `sources/` that take an `HttpClient`. Redirects are not followed; they raise instead, because Steam signals an unavailable endpoint by redirecting to its homepage.
- **Separate parsing from fetching.** For example, `steamspy.parse_tag_response` is pure, so tests feed it inline fixture dicts and never hit the network.
- **Tunable thresholds live in `config.py`:** review and rating filters, Box Method multipliers (30/45/100), TTLs and the User-Agent.
- **`Game.rating` is % positive (0–100).** `Game.base_price` is the undiscounted USD price, and the Box Method uses it.

## Data sources and constraints

- **SteamDB:** has no public API and forbids scraping, so don't add a SteamDB scraper.
- **SteamSpy** (`steamspy.com/api.php?request=tag`): games by tag, with positive and negative counts, price/initialprice/discount and owners. Limit is about 1 request/sec. Its tag lists may be incomplete. Its tag names are older than Steam's catalog, which the picker shows. Renamed tags (Roguelite is "Rogue-lite" on SteamSpy) are mapped in `config.STEAMSPY_TAG_NAMES`. Tags it can't search (any name with `&` or `'`, and missing tags such as Incremental) are listed in `config.STEAMSPY_UNSEARCHABLE_TAGS`; their games come from Steam's store search instead (below). Both lists came from querying every Steam tag in Nov 2026; redo that if Steam adds tags.
- **Steam store endpoints:**
  - Work from this machine: `api/appdetails?appids=` (type, price, categories) and `appreviewhistogram/{appid}` (monthly up/down rollups, used to detect streamer spikes).
  - Store search, `search/results/?tags=<tagid>&infinite=1` (`sources/steam_search.py`, used only for `STEAMSPY_UNSEARCHABLE_TAGS`): JSON whose `results_html` rows carry the appid, title, "N% of the M user reviews" and `data-price-final` (cents). It can't sort by review count (`Reviews_DESC` sorts by % positive), so a tag is read page by page, 100 rows each. It is stricter than the rest of the store: HTTP 429 after ~30 pages at 1.5 s, so `http.URL_INTERVAL` paces it at 3 s/page, and a 429 retries with 10-60 s waits. Incremental (~9,300 games) takes ~5 min the first time, then comes from the cache. The parser reads HTML, so a Steam layout change breaks it; `test_parse_search_page` pins the format.
  - Retired: `store.steampowered.com/appreviews` (review texts) has redirected to the homepage since about Oct 2026. Use its replacement, `api.steampowered.com/IUserReviewsService/GetAppReviews/v1/`. It needs no key, and parameters go in `input_json`. Gotchas: `review_type` is numeric (1 = positive, 2 = negative; strings are silently ignored), and `day_range` must be 0 for all-time results (the default is 30 days, and `filter:"all"` is capped at 365). Don't spoof browser User-Agents.
- **Review mining is keyword-only** (the user's choice: no LLM). An LLM miner may be added later behind the same interface.

## Gotchas

- The Windows console uses code page cp1254. Rich output must stay **ASCII-only** (`>=`, `-`, `x`, not `≥`, `–`, `×`), or printing raises `UnicodeEncodeError`.
