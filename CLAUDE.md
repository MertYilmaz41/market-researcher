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

A Python CLI (`mr`) and local web UI that automate CodeMonkey's "Underserved Audience" method: find Steam games with proven demand (many reviews) but poor satisfaction (5–70% positive) in a clear genre tag, estimate their revenue, mine their complaints, and rank them. The method is in `Underserved-Auidience.md` and the requirements (Turkish) in `requirements-summary.txt`; both are local-only and gitignored. Open source (MIT); formerly "Steam Researcher" (`sr`, `SR_*`), renamed because "Steam" is Valve's trademark.

Measurements and experiments behind the decisions below (miner accuracy, LLM trials, backtest and Box Method results) are in `docs/measurements.md`. Update it when you re-measure.

## Commands

```
uv sync                                    # install deps into .venv
uv run pytest -q                           # all tests
uv run pytest tests/test_core.py::test_parse_and_filter   # single test
uv run mr discover --tag "Job Simulator" --min-reviews 100 --rating 5-70 --top 30
uv run mr discover -t Crafting -t Survival  # several tags: only games that have all of them
uv run mr analyze 2336220 --reviews 300     # risks, mining, score for one AppID (--summary: local LLM, needs Ollama)
uv run mr report --tag "Job Simulator" --max-games 15 --reviews 200   # writes reports/job-simulator.md (--summary)
uv run mr markets --top 30                  # rank every tag by well-served games (~7 min first time)
uv run mr runs                              # saved runs
uv run mr ui                                # web UI on http://localhost:8501
uv run market-researcher                    # same as mr; with no command it opens the web UI (what the installers run)
uv run mr --lang tr report --tag "Job Simulator"   # Turkish output (or MR_LANG=tr)
uv run mr cache clear | prune               # prune deletes expired entries and shrinks the file (nothing else ever does)
uv run python -m market_researcher.mining.evaluate [--games]   # miner accuracy against labeled reviews
uv run python -m market_researcher.summary_eval --models gemma3:12b gemma4:12b   # compare summary models (--lang en, --recheck)
uv run python -m market_researcher.backtest --all   # does the unmet share predict later success? (~13 h first time)
uv run python -m market_researcher.boxcheck         # reviews x45 vs disclosed sales (reports/box-check.md)
MR_LIVE=1 uv run pytest tests/test_live.py -v       # do Steam/SteamSpy still answer as we parse? (~20 s; CI weekly)
uv run --with playwright pytest tests/test_ui.py    # browser smoke test, if .venv lacks Playwright
```

Tag names are SteamSpy tag names (e.g. "Job Simulator", "Colony Sim"); matching is case-insensitive. Up to `config.MAX_TAGS` (5) tags per search.

## Architecture

The pipeline is `sources/*` (fetch) → `models.Game` (normalize) → `discover.filter_candidates` → `boxmethod.estimate` → output. `pipeline.py` holds the steps the CLI commands and the web share: `verify_games` enforces "Games Only" (Steam appdetails per result, since SteamSpy has no type field; ~1.5 s per game the first time), and `analyze_game` builds an `Analysis` (game, details, flags, mining, `Opportunity`). Put new per-game logic in `analyze_game`, not in the CLI or the server.

**Multiple tags:** `pipeline.tag_games` keeps only games that have all tags (one SteamSpy request per tag, or Steam's store search for tags SteamSpy can't search). An unknown tag raises `pipeline.UnknownTag`. Titles, notices and report file names use one label, `pipeline.tag_label` ("Crafting + Survival").

**Parallel analysis:** `run_tag` analyzes games in a thread pool (`config.ANALYZE_WORKERS`); each starts as soon as it passes the store-type check. `run_tag` records per-game failures in `TagResult.failed` and keeps going. A failed review fetch sets `review_error` instead of dropping the game; a failed positive-review fetch keeps the negative sample.

### Scoring (`scoring.py`)

100 × the weighted geometric mean of demand (log of review count) and dissatisfaction (how far below 70% positive), minus fixed penalties per risk flag (`RISK_PENALTIES` in `config.py`).
- If any part is 0, the score is 0. Flags in `EXCLUDE_FLAGS` (`not_game`) drop a game from the ranking.
- Review bombs aren't penalized; `risk.rating_without_bombs` replaces the rating, so a review-bombed game that's otherwise fine scores 0.
- Fixability is shown but not counted: it is ~100% for almost every game. Color steps are 56/35 (`palette.scoreLevel`), `notices.WEAK_SCORE` is 12.
- `config.SCORE_VERSION` is in `runs.compare_key`: bump it when the formula changes, so old runs aren't compared with new ones.
- The words beside the score (`scoring.verdict`, e.g. "Many buyers, most unhappy") describe the evidence, never a judgement or forecast: the score was never shown to predict success. `scoring.why` is one sentence from the same bands.
- `scoring.explain(analysis)` fills the score card (each part, its weight and basis, `scoring.combine`, each penalty with its `config.RISK_LABELS` name, the part that zeroed it). Change wording there, not in JS.

### Risk checks (`risk.py`)

Each check returns `RiskFlag`s; thresholds live in `config.py`. `risk.checks` lists every check, passed or flagged, for the History tab.
- Spike detection skips the launch window. A spike at least 60% negative is a review bomb, otherwise a "Review spike" (code `streamer_spike`; the old flag message stays in `i18n_tr` for saved runs). It reports the rating with spikes excluded.
- `recent_activity` counts reviews in the last 12 months ("Last 12 mo"); a game 2+ years old with under 5% of its reviews there gets `fading_demand`. `recent_rating` is the % positive of those months. Both count back from `Analysis.analyzed_at`, so a saved run shows its own day's figures.
- `check_recovered` flags `recovered` (-20) with 50+ recent reviews rated 15+ points above all time, or 70%+. Not lower than 50: with 30 the noise was too large (Bus-Simulator 2012, no updates since 2013, was flagged).

### Review mining (`mining/`)

Keyword-only. LLMs and embedding classifiers were measured and not adopted (`docs/measurements.md`); `mining/llm.py` only holds the Ollama calls the summaries use.
- `mining.mine(negative, positive)` returns a `MiningResult`. Categories, their regex patterns and design pillars are data in `mining/lexicon.py`: tune that file, not the code.
- A category counts at most once per review; `share` = that count / negative reviews. Reviews under `SHORT_PLAYTIME_MINUTES` (2 h) count half in `share` and `fixability` (not skipped: most are real crash-on-launch reports); `count` stays raw.
- Negation ("no bugs", "never crashed", "hardly/barely/scarcely any/ever") applies only to categories with `negatable=True` ("not enough content" is still a complaint). Bare "barely"/"seldom" are not negations ("barely playable"). **Gotcha:** negation also discards "no optimization"; such phrases need their own pattern starting at the negation word (`(?:no|not) optimi[sz]\w*`).
- "crashed into" (driving games) is not a bug.
- Quotes come from the most helpful reviews (`votes_up`), windowed around the match.
- "What players love" (formerly core fantasy) is 2–3-word phrases counted per review across positive reviews; generic words are filtered by `STOPWORDS`/`GENERIC` in `mining/keywords.py`.
- `idea_praise_share`: negative reviews that still praise the idea, its potential or the game as a whole ("great idea, bad execution").
- `fixability`: share of complaint mentions in fixable categories. `scope_unrealistic` and `price` are not fixable; `content` and `abandoned` are (the user's decision).
- `price` ("Not worth the price / pay-to-win") and `cheaters` exist since Nov 2026. "cash grab" stays in `abandoned`.
- Sample: `pipeline.review_sample` mines half the most helpful reviews and half the newest, deduped. `recent_share`/`trend` need `RECENT_MIN_NEGATIVE` sampled negative reviews from the last 12 months.
- **Adding a pattern:** keep it only if 80%+ of its hits across all fixture files are real complaints of that kind (read them). Tune on `labeled_reviews.jsonl` and the Claude set; never on `labeled_reviews_holdout*.jsonl`. Re-run `mining.evaluate` after every lexicon change; `tests/test_miner_accuracy.py` keeps floors just under the current scores.
- **Label sets** (`tests/fixtures/`): `LABELING.md` (Turkish) is the guide for every set; the user's answers in blind checks set its rules. `claude_labeled_reviews.jsonl` is for tuning only, never for measuring; `tests/test_label_fixtures.py` keeps it apart from the human sets. Only schema 2 rows (`"schema": 2`) label `price` and `cheaters`; `evaluate` scores those categories only there. Rows marked `unsure` are skipped. New samples: `scripts/sample_reviews.py <appid>...`; labeling: `scripts/label_server.py <input.jsonl> --out <answers.jsonl> [--sample N] [--exclude done.jsonl]` (blind); agreement: `scripts/label_agreement.py <first> <reference>`.

### Market view and track record

- `market.py` (pure): `market_stats(games, ...)` describes a tag from the search's game list: games, games with demand, underserved, well served (`config.WELL_SERVED_RATING`, 85%+) and the unmet share (underserved / (underserved + well served)). Stored in `TagResult.market`. Also the price range of paid games with demand (median and middle half of undiscounted list prices, and the well-served median; each needs `MIN_PRICED` = 3 games, else None), appended by `market.summary()` (`price_text`), never written by the model.
- `pipeline.run_markets` computes it for every tag SteamSpy can search (`mr markets`, the web's Markets view), skipping slow store-search tags. Ranked by `market_rank` (well-served games, then games with demand; broad tags last), not by the unmet share, which the backtest found predicts nothing.
- **Track record:** `pipeline.track_record` counts, with `backtest.outcomes`, the games released 48–24 months ago and the hits among them (500+ reviews at 80%+ in their first 24 months), from one review histogram per game with 10+ reviews (cached 30 days, `backtest.HIST_TTL`). Over `config.TRACK_MAX_GAMES` (800) such games: `too_broad`; under `market.MIN_TRACK_ENTRANTS` (10): "too few to tell". The web measures it after showing a run (`POST /api/tag-runs/{id}/track`, in the background, job pinned, saved as `TagResult.track`); a running search cancels it (they share Steam's store host). `mr report` doesn't measure it (up to ~20 min).

### LLM summaries (`summary.py`)

Ollama at `config.LLM_URL`, model `config.LLM_MODEL` (gemma4:12b, chosen for both languages by `summary_eval.py`). HTTP to Ollama goes through `mining/llm.post_chat`, not `HttpClient` (local, uncached, unthrottled). Ollama missing: `notices.llm_unavailable`. `llm.think_setting` turns thinking off for every model that has it (gpt-oss only down to "low"): with it on, summaries took ~3x longer.
- **Opportunity summary:** reads the top `SUMMARY_GAMES` ranked games (`evidence()`, always English) and writes `pitch`, `loved`, `complaints`, `build`, `caveats` in the interface language. Each point names its games; `parse()` drops names not in the evidence and points left with none (except caveats). Written only on request, saved in `TagResult.summaries[lang]` via `RunStore.update_result` (keeps the run's time).
- **Game summary** (`write_game`): `game_evidence()` is `_game()` plus up to `GAME_SUMMARY_REVIEWS` negative reviews no category matched (`uncovered()`); writes `why`, `fix`, `other`. An `other` point whose quote isn't in those reviews is dropped. Saved in `TagResult.game_summaries[appid][lang]`; reviews are re-fetched with `pipeline.review_sample` (answered by the cache).

### Saved runs and shortlist (`runs.py`)

- Every finished web job and `mr report` run is saved to `config.RUNS_DB` (`~/.local/share/market-researcher/runs.sqlite`, apart from the cache so `mr cache clear` keeps it), as JSON via pydantic `TypeAdapter`. A tag run is compared with the last earlier run with the same tags (any order), filters and reviews per game: `score_change`/`new`, shown as ▲/▼/new.
- Shortlist: the `shortlist` table in the same DB (`RunStore.star`/`unstar`/`set_note`/`shortlist`). `PUT /api/shortlist/{appid}` with `run_id` stars a game with a snapshot from that run (`server._snapshot`); starring again refreshes the snapshot but keeps the note and time. With `note` it sets the note; with neither it stars a game analyzed by AppID (`server._single`, latest `SINGLE_KEEP` analyses). Also `GET`, `DELETE`, `GET /api/shortlist.csv`.

### Web server (`web/server.py`)

FastAPI, display-only, bound to 127.0.0.1 by `mr ui` (uvicorn). The frontend never re-implements math: `game_json()` adds `box`, `store_url`, `rating`, `score_explained`, `verdict`, `why`, `checks` etc.
- One shared `HttpClient` (`server._http()`) for all jobs and lookups: each client has its own per-host rate limit, so separate clients would hit Steam twice as fast. Tests point `server._http_client` at a temp cache.
- Jobs: `POST /api/tag-runs` starts `pipeline.run_tag` in a background thread (in the language of the request, via `contextvars.copy_context`); `GET /api/tag-runs/{id}` is polled. The in-memory dict keeps running jobs plus the `JOBS_KEEP` (10) most recently used finished ones; `_job()` reloads older ones from saved runs. A job whose summary or track record is being written is pinned (`_pinned_job`) so two copies never save over each other. `GET /api/games/{appid}` runs `analyze_game` synchronously.
- Status: `step`, `eta` (`server.eta()` extrapolates the current step's pace; None until one item is done and 3 s have passed), `games` (each game's stage from `run_tag(..., on_game)`: `store`, `details`, `reviews` with pages read, `done`), and `slow` (`notices.slow_reviews`, once per job, when a game waits `SLOW_REVIEW_SECONDS` for a review page).
- Cancel: `POST /api/{tag,market}-runs/{id}/cancel` marks the job cancelled at once; its `on_step` raises `pipeline.Cancelled` at the next step (`run_tag` calls it at least every second and drops games not started yet). Cancelled runs aren't saved; fetched data stays cached.
- Cache endpoints: `GET /api/cache` (`Cache.stats()`, `warn` over `config.CACHE_WARN_BYTES`), `POST /api/cache/prune`, `POST /api/cache/clear`. Both answer 409 (`notices.cache_busy`) while any job runs, since VACUUM holds the shared cache's lock. Nothing is deleted automatically.
- Tag list: `GET /api/tags` → `steam_store.tag_names` (Steam's `IStoreService/GetTagList`, ~450 tags, cached 7 days). Unknown tags are detected in `steamspy.games_by_tag` (SteamSpy answers them with the same fallback list as an empty tag); `notices.unknown_tag` suggests close matches.
- **Page caching:** `server.versioned_index()` serves `index.html` with `?v=<hash of the static files>` on `app.js`, `style.css` and, through the import map, every local module; `/` and `/static/*` also get `Cache-Control: no-cache`. Without this a browser kept an old cached `app.js` next to a newer `index.html` and the search hung on "Searching...". Keep local script imports as absolute `/static/<file>.js` paths so the import map can version them.

### Frontend (`web/static/`)

Plain ES modules, no build step, nothing loaded from outside the machine. `app.js` handles data, the views and the drawer; `map2d.js` draws the SVG map; `palette.js` reads colors for JS; `i18n.js` holds the page's Turkish catalog.
- **Layout** (the user's "1b" design, no sidebar): a top bar (brand link to `/`, Games | Markets | Shortlist nav, the search box `#tag-form`, help `#help-toggle`, cache button `#settings-toggle`, separate language `#lang` and theme `#theme` switches; the user wants them apart, not in a menu), the main area with the current view, and the details drawer (`#drawer` / `#panel`) as a second grid column while a game is open. At 1000px or less the drawer is a full-screen sheet. A finished search opens its top game only on screens over 1000px.
- **Search box:** a checklist dropdown of tags (typing only filters; ticked tags show as chips; falls back to comma-separated text if `/api/tags` fails). An AppID or store link in it (`parseAppid`) offers "Open game N". With nothing typed it lists past searches (`loadRuns`). Filters and tags are remembered in localStorage (`filters`); nothing is pre-picked on a first visit; `PRESETS` only fill the fields.
- **Games view:** title, market sentence (`renderMarketLine`, descriptive, never a forecast), track line (`#track-line`), filters button (`#filters-toggle`, popover inputs belong to `#tag-form` via `form=`), AI chip (`#ai-chip`). The ranking has 5 columns (#, game with a ⚠ −N risk badge from `score_explained.penalties`, score pill, biggest complaint, revenue); the first `SHOWN` (8) rows show. List | Map is remembered as `gamesMode`; the hidden map has zero size, so bubbles are drawn only while it's shown. While a search runs, `#search-status` shows "Step N of 3" and `#live` lists each game (`renderLive`).
- **Drawer tabs:** Overview, Complaints, Summary, History (`TABS` in `app.js` names their indexes). Tag chips call `searchOneTag`.
- **Map** (`map2d.js`): x = demand, y = dissatisfaction, size = revenue, color = score; hover card `mapCard` in `app.js`; `axes` from `tag_result_json` so ticks read in reviews and % positive; F2P games get the smallest bubble and stay out of the size scale.
- **Colors** come from `style.css :root` only (dark), with `:root[data-theme="light"]` overriding the same tokens. Use `--accent-ink` (not `--accent`) for violet text and `--shadow` for shadows. An inline script in `index.html` sets `data-theme` before the first paint; `setTheme` redraws the map, panel and History chart, which hold colors outside CSS.
- **Fonts:** Inter, Space Grotesk and JetBrains Mono are bundled in `fonts/` (variable woff2, latin + latin-ext for the Turkish letters, Fontsource 5.3.0, SIL OFL with the licenses beside them), declared at the top of `style.css`.
- **Logo:** sources in `logo/`. The top bar inlines `mark-small.svg` with the `--logo-bg`/`--logo-fg` tokens; `web/static/` holds copies of `favicon.ico`, `mark.svg` (as `favicon.svg`) and `mark-192.png`. Copy them again if the logo changes.
- **Terms and help:** project words get an ⓘ (`info(key)`; static ones are `<button class="info" data-term>` beside a `<span data-i18n>`). All texts live in `terms()` and `riskTerms()` in `app.js`: change wording there. One delegated, capturing click listener toggles `#term-tip`. The help `<dialog id="help">` is static `data-i18n` text: update its accuracy numbers when the miner is re-measured.
- **Notices:** toasts (`toast`/`notify`), and a search's warnings also stay in `#result-notices`. The shortlist state (`state.shortlist`) redraws every `.star[data-appid]` via `refreshStars`.
- **Keyboard:** anything that opens on click goes through `clickable(node, fn)` (Tab stop, Enter/Space); sort headers get `aria-sort` via `markSorted`. `openDrawer(focus)` moves focus to × (or "← Ranking"), `closeDrawer` returns it; the search's own pick of the top game passes `focus = false`. Panel tabs are ARIA tabs. `prefers-reduced-motion` turns off animation and smooth scrolling.
- **Safety:** put review text into the DOM only via `textContent` (the `el()` helper), never `innerHTML`.
- **README screenshot:** `docs/screenshot.png` (a real Colony Sim search, dark theme, 1440x900 at 2x, Playwright). Retake it when the layout changes, and check the quote in the drawer makes sense.

### Interface language (English or Turkish)

Review mining and Steam data stay English.
- **Python:** write `_("Only {n} game(s) passed.", n=n)` (`i18n.py`) and add the Turkish to `i18n_tr.TR` with the same `{placeholders}`. The language is a `ContextVar`: `use("tr")` for a block, `mr --lang tr` / `MR_LANG` for the CLI, the `X-Lang` header or `?lang=` per web request.
- **Numbers:** the same format specs come out Turkish (`{n:,}` → 1.460, `{x:.0%}` → %73, `{x:.1f}` → 0,5). Where English writes `{x:.0f}%`, Turkish writes `%{x:.0f}`. For bare numbers use `num()` / `fmt()`.
- **Stored text:** `N_("...")` marks text translated where it's shown (`RISK_LABELS`, `FIELD_LABELS`). Risk flags store `template` and `params` (`flag.text()`); old runs only have English `message`. Complaint labels, pillars and trends stay English in the data and are translated on output (`trend_kind`).
- **Report:** `report.md.j2` uses `{{ _("...") }}`; the English output must stay as it was. The CSV stays English.
- **Web page:** `i18n.js` has one `"English": "Türkçe",` entry per line; `t("...")` must be called with a literal. Static text in `index.html` is marked `data-i18n`, attributes `data-i18n-attr="title,..."`.
- `tests/test_i18n.py` fails if any `_()`/`N_()`/`t()` literal or `data-i18n` text lacks a translation with the same placeholders. The user is a native Turkish speaker and reviews the wording.

### Messages, CLI and reports

- User-facing messages come from `notices.py` as `Notice(level, title, message, hint)`, shared by the CLI (colored) and the web (toasts). Add new cases there, not ad hoc in the UI; only instant field validation lives in JS. `friendly_error(exc)` turns exceptions into plain language. CLI commands are wrapped in `_guarded` (no traceback unless `MR_DEBUG=1`).
- `report.py` renders `templates/report.md.j2` with Jinja2. Arbitrary text going into the template must pass through the `md` filter (escapes pipes, flattens newlines).

### HTTP and cache

- **All network access goes through `http.HttpClient.get_json`:** per-host throttling (`HOST_INTERVAL`, `URL_INTERVAL`), tenacity retries on 429/5xx (other 4xx fail fast; empty responses aren't cached), and the SQLite cache. One request in flight per host; different hosts run in parallel; `HttpClient` and `Cache` are thread-safe. Redirects raise instead of being followed, because Steam signals an unavailable endpoint by redirecting to its homepage. Steam's review API can be very slow, so it has a shorter timeout (`HOST_TIMEOUT`).
- `cache.Cache`: `~/.cache/market-researcher/market_researcher.sqlite`, table `responses`, zlib-compressed JSON, WAL mode, TTLs in `config.py`. An older plain table `cache` in the same file is never read (an older installed copy sharing the file would fail on compressed rows) and is dropped by prune/clear. Expired rows stay until prune or clear; both VACUUM.
- New data sources go in `sources/` as modules that take an `HttpClient`. Keep parsing separate from fetching (e.g. `steamspy.parse_tag_response` is pure, so tests feed it inline dicts).
- `notices.first_run_seconds_per_game` estimates a run's time from the review requests per game (~9 s at 200 reviews) and warns over `SLOW_RUN_SECONDS`.
- Tunable thresholds live in `config.py`: filters, Box Method multipliers (30/45/100), TTLs, User-Agent. Steam appdetails is cached 1 day (`TTL_STORE_DETAILS`, so `deep_discount` sees current sales); SteamSpy details 7 days.

### Game data

- `Game.rating` is % positive (0–100). `Game.base_price` is the undiscounted USD price; the Box Method uses it.
- **Official review numbers:** search results use SteamSpy's counts; analyzed games get Steam's own via `pipeline.official_reviews` from `steam_store.review_summary` (GetAppReviews' `query_summary` with `languages: ["all"]`, which matches the store page's "All Reviews" and excludes confirmed review-bomb periods; without `languages` it is English-only). Fallback: histogram totals, then SteamSpy. The histogram also wins when the summary is under half its total (GetAppReviews can be wildly low). `Game.rating_source` and `steamspy_rating` record the choice (`report.rating_source_text`); SteamSpy can be far off.
- A second call with `filter_offtopic_activity: 0` counts review-bomb periods too; the difference is `Game.offtopic_reviews`, which `Game.reviews` (demand, Box Method) includes but `Game.rating` doesn't.

### Tests

- `tests/conftest.py` points `config.CACHE_DB` and `config.RUNS_DB` at temp files for every test (`Cache()` and `RunStore()` read them at call time), so no test touches the user's data, which a long backtest may be using.
- `tests/test_web.py` uses FastAPI's `TestClient` with `pipeline.run_tag`/`analyze_game` monkeypatched (no network); an autouse fixture points `server._runs` at a temp DB. `tests/test_ui.py` drives the real app with Playwright (pipeline faked) and skips without Playwright or a browser; `test_ui_keyboard`, `test_ui_logo_goes_home` etc. live there. Check JS syntax with `node --check`.
- `tests/test_live.py` checks every outside endpoint once against Stardew Valley and Colony Sim/Incremental; skipped unless `MR_LIVE=1`, uses a throwaway cache. `.github/workflows/live.yml` runs it Mondays 06:00 UTC, so a failure emails the owner. GitHub turns off scheduled workflows after 60 days without commits; re-enable it in the Actions tab.
- CI (`.github/workflows/test.yml`) runs everything on every push, and builds the wheel and runs both commands from it (catches files missing from the package).

## Backtest (`backtest.py`)

Checks the market claim: did tags with a high unmet share at a past date T later reward new games?
- Each game's review histogram gives its reviews and % positive at any month and its release month (first month with a review; Steam reviews start Oct 2010). `game_at` rebuilds the game as it was at T, so `market.market_stats` runs unchanged. Entrants are released in the 24 months after T. Hit: >= 500 reviews at >= 80% in the first 24 months; sold: >= 500 reviews. Cutoffs 2019-01 to 2022-01; `RECENT_CUTOFFS` 2023-01 and 2024-01 with 12-month windows.
- Success rates fall year by year, so every statistic is computed within each T, then averaged (`per_cutoff`).
- `verdict` writes "holds" only if all four pass: rho > 0, its interval above 0 (resampling tags), rho > 0 with market size held fixed, top fifth's hit rate >= 1.25x the bottom's. Fixed before the results were seen; don't loosen them. `candidate()` holds the adoption rule for other measures (`CANDIDATES`).
- **Tuning on it:** use only the 2019-01 and 2020-01 cutoffs; adopt a change only if it also wins on 2021-01 and 2022-01. Never tune on the recent cutoffs.
- Histograms are cached 30 days (`HIST_TTL`); `--all --dry-run` counts the fetches. Biases (survivorship, today's tags, review bombs in the histogram, games with < 10 reviews left out) are listed in the report.
- **Result:** the unmet share does not predict hits (it predicts sales somewhat). Earlier entrants' hit rate, well-served games and market size do: the app uses all three (Markets ranking, track record). So the app presents the unmet share as a filter for exploring, never a forecast; the help dialog and the `unmet_share` ⓘ say so.

## Box Method check (`boxcheck.py`)

`tests/fixtures/sales_disclosures.jsonl` holds developer- or publisher-reported unit sales with sources and the date each refers to (`as_of`). Add rows as disclosures turn up: units, not revenue; the date known to the month; `steam_only: false` when other stores are counted. The rules for changing the multiplier (B/C/D/E, split by `(appid // 10) % 2`, adopted only with 10%+ lower median error both ways and no fewer within 2x; the small-games rule E needs 8+ new small games) are fixed in `boxcheck.py`. None has been adopted: x45 stays. Gross is units x undiscounted price, not income.

## Installing and releasing

- `install.ps1` (Windows) and `install.sh` (macOS/Linux) install uv if missing, then `uv tool install --force --refresh --python 3.13 <source>` (default: the main branch's GitHub zip, so no git is needed; the repo must be public); `install.ps1` adds a desktop shortcut to `market-researcher.exe`. Test them without touching the real system: `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` at a temp folder (the scripts then skip `uv tool update-shell`), `MR_SOURCE=<built wheel>`, `MR_NO_SHORTCUT=1`.
- `market-researcher` (`cli.start`) is `mr` that opens the web UI when no command is given (also with only global options such as `--lang tr`).
- `.github/workflows/release.yml`: pushing a `v*` tag that matches `version` in `pyproject.toml` publishes to PyPI through a trusted publisher (workflow `release.yml`, environment `pypi`).

## Data sources and constraints

- **SteamDB:** no public API and forbids scraping; don't add a SteamDB scraper.
- **SteamSpy** (`steamspy.com/api.php?request=tag`): games by tag with positive/negative counts, price/initialprice/discount, owners. ~1 request/sec. Tag lists may be incomplete; tag names are older than Steam's catalog. Renamed tags (Roguelite is "Rogue-lite") are mapped in `config.STEAMSPY_TAG_NAMES`; tags it can't search (names with `&` or `'`, and missing tags such as Incremental) are in `config.STEAMSPY_UNSEARCHABLE_TAGS`. Both lists came from querying every Steam tag; redo that if Steam adds tags.
- **Steam store:** `api/appdetails?appids=` (type, price, categories) and `appreviewhistogram/{appid}` (monthly up/down rollups).
- **Steam store search** (`sources/steam_search.py`, only for `STEAMSPY_UNSEARCHABLE_TAGS`): `search/results/?tags=<tagid>&infinite=1`, JSON whose `results_html` rows carry the appid, title, "N% of the M user reviews" and `data-price-final` (cents). It can't sort by review count, so a tag is read page by page (100 rows). It answers 429 after ~30 pages at 1.5 s, so `URL_INTERVAL` paces it at 3 s/page and a 429 retries with 10–60 s waits; Incremental (~9,300 games) takes ~5 min the first time. It parses HTML: `test_parse_search_page` pins the format.
- **Review texts:** `store.steampowered.com/appreviews` redirects to the homepage since about Oct 2026; use `api.steampowered.com/IUserReviewsService/GetAppReviews/v1/` (no key, parameters in `input_json`). Gotchas: `review_type` is numeric (1 = positive, 2 = negative; strings are silently ignored), so is `filter` (0 = most helpful, 1 = newest; "recent" is ignored), and `day_range` must be 0 for all-time results (the default is 30 days; `filter:"all"` is capped at 365).
- Don't spoof browser User-Agents.

## Gotchas

- The Windows console uses code page cp1254. Rich output must keep **ASCII symbols** (`>=`, `-`, `x`, not `≥`, `–`, `×`), or printing raises `UnicodeEncodeError`. Turkish letters (ç ğ ı ö ş ü İ, also â) are in cp1254 and print fine. The web catalog can use any symbol (`≥`, `→`).
