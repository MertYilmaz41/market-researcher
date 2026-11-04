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
uv run sr analyze 2336220 --reviews 300     # risks, mining, score for one AppID
uv run sr report --tag "Job Simulator" --max-games 15 --reviews 200   # writes reports/job-simulator.md
uv run sr ui                                # web UI (3D map) on http://localhost:8501
uv run sr cache clear
```

Tag names are SteamSpy tag names (e.g. "Job Simulator", "Colony Sim"); matching is case-insensitive.

## Architecture

`pipeline.py` holds the steps that `cli.py` commands share. `verify_games` enforces "Games Only". `analyze_game` builds an `Analysis` (game, details, flags, mining, `Opportunity`), and both `analyze` and `report` use it. Put new per-game logic in `analyze_game`, not in the CLI.

Scoring (`scoring.py`): 100 × the weighted geometric mean of demand (log of review count), dissatisfaction (how far below 70% positive) and fixability, minus fixed penalties per risk flag (`RISK_PENALTIES` in `config.py`).
- If any part is 0, the score is 0.
- Review bombs aren't penalized. Instead, `risk.rating_without_bombs` replaces the rating, so a review-bombed game that's otherwise fine scores 0.
- Flags in `EXCLUDE_FLAGS` (`not_game`) drop a game from the ranking entirely.

Web UI (`web/`): `sr ui` runs uvicorn on `web/server.py`, bound to 127.0.0.1, and opens the browser.
- **Server:** a FastAPI app that is display-only. `POST /api/tag-runs` starts `pipeline.run_tag` in a background thread; each job builds its own `HttpClient` because SQLite connections are per thread. Jobs live in an in-memory dict, and `GET /api/tag-runs/{id}` is polled for progress and the result. `GET /api/games/{appid}` runs `analyze_game` synchronously.
- **JSON:** `game_json()` adds `box`, `store_url`, `rating`, etc., so the frontend never re-implements any math.
- **Frontend:** `web/static/` is plain ES modules with no build step. `app.js` handles data, the table and the panel; `map3d.js` draws the three.js scene (x = demand, y = dissatisfaction, z = fixability, size = revenue, color = score). three.js is pinned to `three@0.170.0` in the import map in `index.html`.
- **Safety:** put review text into the DOM only via `textContent` (the `el()` helper in `app.js`), never `innerHTML`.
- **Tests:** `tests/test_web.py` uses FastAPI's `TestClient` with `pipeline.run_tag`/`analyze_game` monkeypatched, so it needs no network. The JS has no tests; check it with `node --check` and a real browser.

`report.py` renders `templates/report.md.j2` with Jinja2. Arbitrary text going into the template must pass through the `md` filter, which escapes pipes and flattens newlines.

The pipeline is `sources/*` (fetch) → `models.Game` (normalize) → `discover.filter_candidates` (steps 1–3) → `boxmethod.estimate` → output in `cli.py`.

`discover` also calls Steam appdetails for every result it shows, to enforce "Games Only" (SteamSpy has no type field). The first run of a tag is slow because of this, about 1.5s per game. `analyze` combines SteamSpy appdetails (which includes tags), Steam appdetails and the review histogram, then runs `risk.assess`. Each check in `risk.py` returns `RiskFlag`s, and its thresholds live in `config.py`. Spike detection skips the launch window. It labels a spike a review bomb when it is at least 60% negative, otherwise a streamer spike, and it reports the rating with spikes excluded.

`analyze` also mines reviews. `mining.mine(negative, positive)` returns a `MiningResult`. Complaint categories, their regex patterns and their design pillars are all data in `mining/lexicon.py`, so tune that file rather than the code.
- A category counts at most once per review, and `share` is that count divided by the number of negative reviews.
- Negation ("no bugs", "never crashed") is applied only to categories with `negatable=True`, because "not enough content" is still a complaint.
- Quotes come from the most helpful reviews (`votes_up`), windowed around the match.
- The core fantasy is two- and three-word phrases counted per review across positive reviews. Generic words are filtered by `STOPWORDS`/`GENERIC` in `mining/keywords.py`.
- `idea_praise_share` is the "great idea, bad execution" signal: negative reviews that still praise the idea or its potential.
- `fixability` is the share of complaint mentions in fixable categories. Milestone 4 scoring will use it.
- Known false positive: in driving games, "I crashed" is counted as a bug. Check changes to the lexicon against real reviews from `sr analyze`.

- **All network access goes through `http.HttpClient.get_json`.** It does per-host throttling (`HOST_INTERVAL`), tenacity retries on 429/5xx (other 4xx fail fast; empty responses are not cached), and caching in SQLite (`cache.Cache`, `~/.cache/steam-researcher/steam_researcher.sqlite`, TTLs in `config.py`). New data sources should be added as modules in `sources/` that take an `HttpClient`. Redirects are not followed; they raise instead, because Steam signals an unavailable endpoint by redirecting to its homepage.
- **Separate parsing from fetching.** For example, `steamspy.parse_tag_response` is pure, so tests feed it inline fixture dicts and never hit the network.
- **Tunable thresholds live in `config.py`:** review and rating filters, Box Method multipliers (30/45/100), TTLs and the User-Agent.
- **`Game.rating` is % positive (0–100).** `Game.base_price` is the undiscounted USD price, and the Box Method uses it.

## Data sources and constraints

- **SteamDB:** has no public API and forbids scraping, so don't add a SteamDB scraper.
- **SteamSpy** (`steamspy.com/api.php?request=tag`): games by tag, with positive and negative counts, price/initialprice/discount and owners. Limit is about 1 request/sec. Its tag lists may be incomplete.
- **Steam store endpoints:**
  - Work from this machine: `api/appdetails?appids=` (type, price, categories) and `appreviewhistogram/{appid}` (monthly up/down rollups, used to detect streamer spikes).
  - Retired: `store.steampowered.com/appreviews` (review texts) has redirected to the homepage since about Oct 2026. Use its replacement, `api.steampowered.com/IUserReviewsService/GetAppReviews/v1/`. It needs no key, and parameters go in `input_json`. Gotchas: `review_type` is numeric (1 = positive, 2 = negative; strings are silently ignored), and `day_range` must be 0 for all-time results (the default is 30 days, and `filter:"all"` is capped at 365). Don't spoof browser User-Agents.
- **Review mining is keyword-only** (the user's choice: no LLM). An LLM miner may be added later behind the same interface.

## Gotchas

- The Windows console uses code page cp1254. Rich output must stay **ASCII-only** (`>=`, `-`, `x`, not `≥`, `–`, `×`), or printing raises `UnicodeEncodeError`.
