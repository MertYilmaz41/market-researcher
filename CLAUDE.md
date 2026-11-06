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
uv run sr analyze 2336220 --summary          # plus what a local LLM reads in it (needs Ollama)
uv run sr report --tag "Job Simulator" --max-games 15 --reviews 200   # writes reports/job-simulator.md
uv run sr report --tag "Job Simulator" --summary   # plus an opportunity summary by a local LLM (needs Ollama)
uv run python -m steam_researcher.mining.evaluate --miner llm --model gemma3:12b   # LLM complaint detection vs the labels
uv run sr markets --top 30                  # rank every tag by underserved games (~7 min first time)
uv run sr runs                              # saved runs (from sr report and the web UI)
uv run sr ui                                # web UI (3D map) on http://localhost:8501
uv run sr --lang tr report --tag "Job Simulator"   # Turkish output and report (or SR_LANG=tr); the web UI has an EN | TR switch
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
- **Frontend:** `web/static/` is plain ES modules with no build step. `app.js` handles data, the table and the panel.
  - **Layout:** a slim top bar (brand, help, EN | TR); then a left sidebar (tags, the Filters section, "Find opportunities", the one-game AppID form, and the Games | Markets | Shortlist nav, `#table-view`); the main card with the current view; and a details drawer (`#drawer` holding `#panel`) as a third grid column only while a game is open. `renderPanel` opens the drawer; × or Esc closes it (`closeDrawer` also clears the selection). At 1000px or less everything stacks and the drawer is a full-screen sheet.
  - The Filters section collapses (`#filters-toggle`, remembered as `filtersOpen`; open by default on wide screens). The Games view shows the ranking as a table or as the map (`#games-mode` Table | Map, remembered as `gamesMode`); the hidden map has zero size, so its bubbles are drawn only while it's shown.
  - The map has a 2D | 3D switch (remembered in localStorage). `map2d.js` is an SVG scatter (x = demand, y = dissatisfaction, size = revenue, color = score) that needs no CDN; `map3d.js` draws the three.js scene (plus z = fixability). Both get the same games and selection through the `map` wrapper in `app.js`, and if three.js or WebGL is missing, only 2D is offered. Colors come from `style.css :root` only, and `palette.js` reads them for the JS (score scale, map, charts). three.js is pinned to `three@0.170.0` in the import map in `index.html`.
- **Multiple tags:** a search takes a list of tags and keeps only games that have all of them (`pipeline.tag_games`: one SteamSpy request per tag, or Steam's store search for tags SteamSpy can't search). An unknown tag raises `pipeline.UnknownTag`. Titles, notices and report file names get one string, the label `pipeline.tag_label` ("Crafting + Survival"), so they need no changes.
- **Tag picker:** the tag field in `app.js` is a checklist dropdown. You tick tags with the mouse; the text box only filters the list. Ticked tags show as chips with an ×. The list is filled from `GET /api/tags`. That calls `steam_store.tag_names`, which uses Steam's `IStoreService/GetTagList` (about 450 tags, cached 7 days). If the list fails to load, the field falls back to comma-separated free text. Unknown tags are detected in `steamspy.games_by_tag`: SteamSpy answers them with the same fallback list as an empty tag. `notices.unknown_tag` then suggests close matches.
- **Score card:** hovering or focusing a score (table pill, panel ring, "How is this score calculated?") opens `#score-tip`, filled from `game_json()["score_explained"]` = `scoring.explain(analysis)`: each part with its weight and a plain-language basis, the combined value (`scoring.combine`, shared with `score()`), each penalty with its `config.RISK_LABELS` name and the flag's message, and the part that zeroed the score. Change wording there, not in JS.
- **Time left:** the job status has `eta` (seconds): `server.eta()` extrapolates the pace of the current step (a step starts when `total` changes or `done` drops). None until one item is done and 3 s have passed, so cached runs show none. The banner shows it next to the count (`progressCount` in `app.js`).
- **Cancel:** `POST /api/{tag,market}-runs/{id}/cancel` marks the job "cancelled" at once (the UI is free); the job's `on_step` then raises `pipeline.Cancelled` at the pipeline's next step. `run_tag` calls `on_step` at least every second while games are analyzed, and on cancel drops the games not started yet (`pool.shutdown(cancel_futures=True)`); the few already running finish in the background. Cancelled runs aren't saved. Anything fetched stays cached.
- **Caching of the page:** `server.versioned_index()` serves `index.html` with `?v=<hash of the static files>` on `app.js` and `style.css`, and versions module imports (`/static/palette.js` etc.) through the import map; `/` and `/static/*` are also sent with `Cache-Control: no-cache`. Without this a browser kept an old cached `app.js` next to a newer `index.html` after an update (no-cache alone didn't help, because the old copy was cached before the header existed), and the search button hung on "Searching..." with an empty banner. Keep local script imports as absolute `/static/<file>.js` paths so the import map can version them.
- **Safety:** put review text into the DOM only via `textContent` (the `el()` helper in `app.js`), never `innerHTML`.
- **Market view** (`market.py`, pure): `market_stats(games, ...)` describes a whole tag from the game list a search already has: games, games with demand, underserved (in the % range), well served (`config.WELL_SERVED_RATING`, 85%+) and the gap (underserved / (underserved + well served)). `run_tag` stores it in `TagResult.market`; the web shows it as the Market strip above the ranking. `pipeline.run_markets` computes it for every tag SteamSpy can search (one request per tag, ~7 min first time, then cached) for `sr markets` and the web's Games | Markets switch; the slow Steam-store-search tags are skipped.
- **Opportunity summary** (`summary.py`): a local LLM (Ollama at `config.LLM_URL`, model `config.LLM_MODEL` = gemma3:12b) reads the top `SUMMARY_GAMES` ranked games of a run (`evidence()`: complaint shares and quotes, phrases from positive reviews, recent rating, risk messages; always English) and writes `pitch`, `loved`, `complaints`, `build` and `caveats` in the interface language. Each point names its games; `parse()` drops names that aren't in the evidence and points left with none (except caveats). Written only on request (web "Write summary", `sr report --summary`; ~60-90 s), saved in `TagResult.summaries[lang]` via `RunStore.update_result` (keeps the run's time, so comparisons still work), and shown in the report above the ranking. Ollama missing: `notices.llm_unavailable`. HTTP to Ollama goes through `mining/llm.post_chat`, not `HttpClient` (local, uncached, no throttling). Measured Nov 2026: gemma3:12b was steady and grounded but partly generic; qwen3:30b-a3b was sharper but once returned empty sections and made factual slips.
- **Game summary** (`summary.write_game`): the same model reads one game: `game_evidence()` is `_game()` plus up to `GAME_SUMMARY_REVIEWS` negative reviews that no complaint category matched (`uncovered()`, most helpful first), and it writes `why`, `fix` and `other` (complaints no category covers, e.g. price, cheaters). An `other` point whose quote isn't in one of those reviews is dropped. Written on request (web panel tab "Summary", `POST /api/tag-runs/{id}/games/{appid}/summary`; `sr analyze APPID --summary` prints it without saving), saved in `TagResult.game_summaries[appid][lang]`, and shown in the report under the game. The reviews are fetched again with `pipeline.review_sample`, which the HTTP cache answers.
- **Saved runs** (`runs.py`): every finished web job and `sr report` run is saved to `config.RUNS_DB` (`~/.local/share/steam-researcher/runs.sqlite`, apart from the cache so `sr cache clear` keeps it). The result is stored as JSON via pydantic `TypeAdapter` and rebuilt on load, so `_job()` serves saved runs after a restart (report, CSV, "Past runs" in the UI). A tag run is compared with the last earlier run with the same tags (any order) and filters: `score_change`/`new` per game, shown as ▲/▼/new.
- **Shortlist:** the `shortlist` table in the same runs DB (`RunStore.star`/`unstar`/`set_note`/`shortlist`). `PUT /api/shortlist/{appid}` with `run_id` stars a game: the server takes a snapshot of it from that run (`server._snapshot`: score, rating, reviews, top complaint in English, the search label); starring again refreshes the snapshot but keeps the note and time. With `note` it sets the note. `GET /api/shortlist`, `DELETE`, `GET /api/shortlist.csv` (`report.shortlist_csv`). The page keeps `state.shortlist` and redraws every `.star[data-appid]` button after each call (`refreshStars`); the Shortlist view is the third table view.
- **Remembered filters:** `app.js` saves the filter fields and ticked tags in localStorage (`filters`) on every change and restores them at load (unknown tags are dropped once the tag list loads). The preset buttons (`PRESETS`) only fill the fields.
- **Quick filter:** the name box and "Hide games with risk penalties" (`opportunity.penalty > 0`) above the ranking filter the table and the map through `visibleGames()`. The Risks column shows the same set (`penaltyText`: `score_explained.penalties` with their points), so the two always agree; ranks stay those of the full ranking. Tag chips in the panel call `searchOneTag` (a new search for that one tag).
- **Terms:** project words are explained by an ⓘ (`info(key)` in `app.js`; static ones are `<button class="info" data-term>` in `index.html`, beside a `<span data-i18n>` so the language switch doesn't wipe them) and listed in the help dialog (`#help-terms`, `#help-risks`). All texts live in `terms()` and `riskTerms()` in `app.js`: change wording there. One delegated, capturing click listener toggles `#term-tip`, so an ⓘ in a header never sorts it. Renamed in Nov 2026 for clarity: Core fantasy -> What players love, Gap -> Unmet share, Est. gross -> Est. revenue, severity high/warn/info -> Serious/Caution/Note, "adj." -> "without review bombs", Reviews mined -> Reviews read (also in the CLI and the report).
- **Help:** `<dialog id="help">` in `index.html`, opened by the green "How it works" button in the top bar; its text is static `data-i18n`. Update its accuracy numbers when the miner is re-measured.
- **Tests:** `tests/test_web.py` uses FastAPI's `TestClient` with `pipeline.run_tag`/`analyze_game` monkeypatched, so it needs no network; an autouse fixture points `server._runs` at a temp DB. `tests/test_ui.py` drives the real app in a browser with Playwright (pipeline faked) and skips when Playwright or a browser is missing. Check JS syntax with `node --check`. CI (`.github/workflows/test.yml`) runs both on every push.

**Interface language** (English or Turkish; review mining and Steam data stay English):
- **Python:** write text in English as `_("Only {n} game(s) passed.", n=n)` (`i18n.py`) and add the Turkish to `i18n_tr.TR`, with the same `{placeholders}`. The language is a `ContextVar`: `use("tr")` for a block, `sr --lang tr` / `SR_LANG` for the CLI, and the `X-Lang` header or `?lang=` per web request. Web jobs run in the language of the request that started them (`contextvars.copy_context`).
- **Numbers** come out the Turkish way from the same format specs: `{n:,}` gives 1.460, `{x:.0%}` gives %73, `{x:.1f}` gives 0,5. Where the English writes `{x:.0f}%`, the Turkish template writes `%{x:.0f}`. For numbers without text use `num()` / `fmt()`.
- **Stored text:** `N_("...")` marks text translated later, where it's shown (`RISK_LABELS`, `FIELD_LABELS`). Risk flags store `template` and `params`, and `flag.text()` translates them; runs saved before that only have the English `message`. Complaint labels, pillars and trends stay English in the data, and `game_json`, the CLI and the report translate them (`trend_kind` tells the page which trend it is).
- **Report:** `report.md.j2` uses `{{ _("...") }}`. The English output must stay as it was. The CSV stays English (machine-readable codes and labels).
- **Web page:** `web/static/i18n.js` holds its own `TR` catalog, one `"English": "Türkçe",` entry per line. `t("...")` must be called with a literal. Static text in `index.html` is marked `data-i18n`, attributes `data-i18n-attr="title,..."`. The EN | TR switch redraws in place and re-fetches the current result and game.
- **Tests:** `tests/test_i18n.py` finds every `_()`/`N_()` literal (Python and the template), every `t()` literal and every `data-i18n` text. Each must have a translation with the same placeholders, so a new English text without Turkish fails the tests. The user is a native Turkish speaker and reviews the wording.

User-facing messages (validation, info, warnings, friendly errors) come from `notices.py` as `Notice(level, title, message, hint)`. The CLI and the web share them: the CLI prints them in color, and the web shows them as toasts (`toast`/`notify` in `app.js`). Add new cases in `notices.py`, not ad hoc in the UI; only instant field validation lives in JS. `friendly_error(exc)` turns exceptions into plain language. CLI commands are wrapped in `_guarded`, so no traceback is shown unless `SR_DEBUG=1`. `run_tag` records per-game failures in `TagResult.failed` and keeps going.

`report.py` renders `templates/report.md.j2` with Jinja2. Arbitrary text going into the template must pass through the `md` filter, which escapes pipes and flattens newlines.

The pipeline is `sources/*` (fetch) → `models.Game` (normalize) → `discover.filter_candidates` (steps 1–3) → `boxmethod.estimate` → output in `cli.py`.

`discover` also calls Steam appdetails for every result it shows, to enforce "Games Only" (SteamSpy has no type field). The first run of a tag is slow because of this, about 1.5s per game. `analyze` combines SteamSpy appdetails (which includes tags), Steam appdetails and the review histogram, then runs `risk.assess`. Each check in `risk.py` returns `RiskFlag`s, and its thresholds live in `config.py`. Spike detection skips the launch window. It labels a spike a review bomb when it is at least 60% negative, otherwise a streamer spike, and it reports the rating with spikes excluded. `risk.recent_activity` counts reviews in the last 12 months from the histogram (shown as "Last 12 mo"); a game 2+ years old with under 5% of its reviews in that window gets `fading_demand` (a score penalty). `risk.recent_rating` is the % positive of those 12 months (also shown in "Last 12 mo"). `check_recovered` flags `recovered` ("Already improved", -20) when there are 50+ recent reviews and they rate 15+ points above all time, or 70%+: the problems may already be fixed. With 30 reviews the noise was too large: Bus-Simulator 2012 (no updates since 2013) was flagged.

`analyze` also mines reviews. `mining.mine(negative, positive)` returns a `MiningResult`. Complaint categories, their regex patterns and their design pillars are all data in `mining/lexicon.py`, so tune that file rather than the code.
- A category counts at most once per review, and `share` is that count divided by the number of negative reviews.
- Negation ("no bugs", "never crashed") is applied only to categories with `negatable=True`, because "not enough content" is still a complaint.
- Quotes come from the most helpful reviews (`votes_up`), windowed around the match.
- The core fantasy is two- and three-word phrases counted per review across positive reviews. Generic words are filtered by `STOPWORDS`/`GENERIC` in `mining/keywords.py`.
- `idea_praise_share` is the "great idea, bad execution" signal: negative reviews that still praise the idea or its potential.
- `fixability` is the share of complaint mentions in fixable categories. Milestone 4 scoring will use it.
- **Measured accuracy:** `uv run python -m steam_researcher.mining.evaluate` scores the miner against hand-labeled real reviews.
  - `tests/fixtures/labeled_reviews.jsonl` (153 reviews from 9 games) is the set to tune on.
  - `labeled_reviews_holdout.jsonl` (47 reviews from 6 other games) is never tuned on: it shows whether a change generalizes.
  - `labeled_reviews_holdout2.jsonl` (6 more games, labeled by the user through `scripts/label_server.py`) is a second never-tuned set. Only 75 of its 156 reviews are answered (the rest stay in `labeled_reviews_holdout2.unlabeled.jsonl`); rows marked `unsure` are skipped by `evaluate.load`.
  - Nov 2026, complaint precision/recall: tuning 90%/86%, held-out 83%/62%, holdout2 78%/63% (held-out was 86%/53% before tuning; 12 "content" labels in the first two sets were corrected after a blind check by the user).
  - Then tuned on the Claude-labeled set (40 of its 50 games; the other 10 as a check): tuning 90%/86%, held-out 85%/62%, holdout2 77%/65%, both held-out sets pooled 80%/64% (was 80%/63%); the 10 check games 81%/54% (was 81%/50%). Most new patterns raised recall on the Claude games but barely moved the human sets, so the human labelers phrase misses differently. Patterns that cost held-out precision were dropped by counting hits only (texts not read): "false advertising", "nothing new", "they promised". Idea praise now also matches praise of the whole game ("the game is fun", "I loved this game"), as LABELING.md asks: holdout2 recall 31% -> 50%. `scope_unrealistic` was left alone: the Claude set has no example of it.
  - `tests/test_miner_accuracy.py` keeps floors just under these scores. Re-run it after every lexicon change.
  - New samples come from `scripts/sample_reviews.py <appid>...`; their `labels` are filled in by hand.
- **Labeling rules:** `tests/fixtures/LABELING.md` (Turkish) is the guide for every label set; the user's answers in blind checks set the rules (e.g. `idea_praise` counts praise of the game as a whole, shut-down servers count as `abandoned`, a broken control is `bugs`, not `controls`).
- **Claude-labeled training set:** `tests/fixtures/claude_labeled_reviews.jsonl` (1,077 reviews, 50 games, `"labeler": "claude"`) is for training and tuning only, never for measuring. A blind check of 40 of them by the user (`claude_check2.user.jsonl`) agreed on 86% of complaint labels (micro-F1; gate 80%); Claude never missed one of the user's labels but added ~10 extra. `tests/test_label_fixtures.py` keeps it apart from the human sets (no shared game or review).
- **Label tools:** `scripts/label_server.py <input.jsonl> --out <answers.jsonl> [--sample N] [--exclude done.jsonl]` is a click-to-label page (input labels hidden, so checks are blind); `scripts/label_agreement.py <first> <reference>` prints per-category agreement.
- **Sample:**
  - `pipeline.review_sample` mines half the most helpful reviews and half the newest, deduped.
  - Reviews written under `SHORT_PLAYTIME_MINUTES` (2 h) count half in `share` and `fixability`. They aren't skipped, because most are real crash-on-launch reports. `count` stays raw.
  - `CategoryResult.recent_share`/`trend` ("still common lately" / "rarely mentioned lately") need at least `RECENT_MIN_NEGATIVE` sampled negative reviews from the last 12 months.
- **Negation gotcha:** the negation check also discards "no optimization", which is a real complaint. Such phrases need their own pattern that starts at the negation word ("(?:no|not) optimi[sz]\w*").
- "crashed into" (driving games) is not counted as a bug.

- **Parallel analysis:** `run_tag` analyzes games in a thread pool (`config.ANALYZE_WORKERS`), and each game starts as soon as it passes the store-type check. `HttpClient` and `Cache` are thread-safe: one request is in flight per host, so different hosts work in parallel. Steam's review API is sometimes very slow (20–90+ s per page, measured Nov 2026), so it has a shorter timeout (`HOST_TIMEOUT`). A failed review fetch sets `review_error` instead of dropping the game.
- **All network access goes through `http.HttpClient.get_json`.** It does per-host throttling (`HOST_INTERVAL`), tenacity retries on 429/5xx (other 4xx fail fast; empty responses are not cached), and caching in SQLite (`cache.Cache`, `~/.cache/steam-researcher/steam_researcher.sqlite`, TTLs in `config.py`). New data sources should be added as modules in `sources/` that take an `HttpClient`. Redirects are not followed; they raise instead, because Steam signals an unavailable endpoint by redirecting to its homepage.
- **Separate parsing from fetching.** For example, `steamspy.parse_tag_response` is pure, so tests feed it inline fixture dicts and never hit the network.
- **Tunable thresholds live in `config.py`:** review and rating filters, Box Method multipliers (30/45/100), TTLs and the User-Agent.
- **`Game.rating` is % positive (0–100).** `Game.base_price` is the undiscounted USD price, and the Box Method uses it.
- **Official review numbers:** search results use SteamSpy's counts, but `pipeline.official_reviews` gives analyzed games Steam's own.
  - The source is `steam_store.review_summary`, GetAppReviews' `query_summary` with `languages: ["all"]`. It matches the store page's "All Reviews" exactly, and excludes off-topic review-bomb periods that Steam confirmed. Without `languages` it is English-only.
  - Fallback: the histogram totals, then SteamSpy.
  - `Game.rating_source` and `steamspy_rating` record the choice, and `report.rating_source_text` shows it. SteamSpy can be far off (Feed the Cups: SteamSpy 30%, Steam 73%).
  - Review-bomb periods: a second call with `filter_offtopic_activity: 0` counts them too. The difference goes into `Game.offtopic_reviews`, which `Game.reviews` (demand, Box Method) includes but `Game.rating` doesn't, because those reviewers bought the game but the bomb isn't about its quality. Feed the Cups: 73% of 4,855 rated, 11,224 counted for demand.

## Data sources and constraints

- **SteamDB:** has no public API and forbids scraping, so don't add a SteamDB scraper.
- **SteamSpy** (`steamspy.com/api.php?request=tag`): games by tag, with positive and negative counts, price/initialprice/discount and owners. Limit is about 1 request/sec. Its tag lists may be incomplete. Its tag names are older than Steam's catalog, which the picker shows. Renamed tags (Roguelite is "Rogue-lite" on SteamSpy) are mapped in `config.STEAMSPY_TAG_NAMES`. Tags it can't search (any name with `&` or `'`, and missing tags such as Incremental) are listed in `config.STEAMSPY_UNSEARCHABLE_TAGS`; their games come from Steam's store search instead (below). Both lists came from querying every Steam tag in Nov 2026; redo that if Steam adds tags.
- **Steam store endpoints:**
  - Work from this machine: `api/appdetails?appids=` (type, price, categories) and `appreviewhistogram/{appid}` (monthly up/down rollups, used to detect streamer spikes).
  - Store search, `search/results/?tags=<tagid>&infinite=1` (`sources/steam_search.py`, used only for `STEAMSPY_UNSEARCHABLE_TAGS`): JSON whose `results_html` rows carry the appid, title, "N% of the M user reviews" and `data-price-final` (cents). It can't sort by review count (`Reviews_DESC` sorts by % positive), so a tag is read page by page, 100 rows each. It is stricter than the rest of the store: HTTP 429 after ~30 pages at 1.5 s, so `http.URL_INTERVAL` paces it at 3 s/page, and a 429 retries with 10-60 s waits. Incremental (~9,300 games) takes ~5 min the first time, then comes from the cache. The parser reads HTML, so a Steam layout change breaks it; `test_parse_search_page` pins the format.
  - Retired: `store.steampowered.com/appreviews` (review texts) has redirected to the homepage since about Oct 2026. Use its replacement, `api.steampowered.com/IUserReviewsService/GetAppReviews/v1/`. It needs no key, and parameters go in `input_json`. Gotchas: `review_type` is numeric (1 = positive, 2 = negative; strings are silently ignored), so is `filter` (0 = most helpful, 1 = newest first; "recent" is ignored), and `day_range` must be 0 for all-time results (the default is 30 days, and `filter:"all"` is capped at 365). Don't spoof browser User-Agents.
- **Review mining is keyword-only.** An LLM complaint detector (`mining/llm.py`, `evaluate --miner llm`) was measured in Nov 2026 and not adopted: on the held-out reviews gemma3:12b got 67%/88% precision/recall and qwen3:30b-a3b 49%/84%, against 86%/62% for keywords, and a blind relabeling by the user sided with the labels, not the LLM, on most disputed "too little content" cases. The LLM is used only for the opportunity summary.
  - Re-measured Nov 2026 on both human held-out sets together (`labeled_reviews_holdout.jsonl` + the 73 sure reviews of `labeled_reviews_holdout2.jsonl`; `evaluate.load` skips `unsure`), precision/recall on a 16 GB RTX 4060 Ti: keywords 81%/63%; qwen3:14b 65%/74%; phi4:14b 67%/74%; mistral-small3.2:24b 66%/74% (~25 min/game, 88% in VRAM); gpt-oss:20b 69%/68%; gemma3:12b 57%/72%; qwen3:30b-a3b 58%/65%. None reaches 85% precision; all over-flag. gpt-oss gets `think: "low"` in `llm._request` (it can't turn thinking off).
  - Embeddings + one logistic regression per category (`scripts/embed_classifier.py`, run with `uv run --with numpy --with scikit-learn`; trained on the Claude set + tuning set, threshold per category from 5-fold CV) didn't beat keywords either, on the same 120 held-out reviews: bge-m3 79%/46% and nomic-embed-text 81%/49% at an 85% precision target; lower targets trade precision for recall (bge-m3 at 65%: 60%/66%). Keywords OR classifier raised recall to 70-81% but cut precision to 54-74%. The classifier held 85% in cross-validation but not on the held-out games, so numpy/scikit-learn were not added as dependencies.
  - Keywords checked by an LLM (`llm.verify`, `evaluate --miner verify`): the keywords find candidates and the model may only drop them (with a quote that must be in the review). Same 120 held-out reviews, after the Claude-set lexicon tuning: keywords 80%/64%; checked by gemma3:12b 88%/61%, by qwen3:14b 87%/62%, ~2 s per review (~6-8 min per game). Precision rose ~7-8 points but recall fell 2-3 points and a 15-game run would take 1.5-2 h, so it isn't used in the app.

## Gotchas

- The Windows console uses code page cp1254. Rich output must keep **ASCII symbols** (`>=`, `-`, `x`, not `≥`, `–`, `×`), or printing raises `UnicodeEncodeError`. Turkish letters (ç ğ ı ö ş ü İ, also â) are in cp1254 and print fine. The web catalog can use any symbol (`≥`, `→`).
