# Steam Researcher

Find underserved Steam audiences: games people clearly wanted, but that disappointed them.

> **Proven Demand + Poor Execution = High Opportunity**

Based on CodeMonkey's Underserved Audience method: look for genres where players bought a game in large numbers but were let down by how it was made, then build the better version.

## What it does

- **Discovers** games in one or more tags (e.g. *Job Simulator*, or *Crafting + Survival*) with many reviews but a low rating (5–70% positive).
- **Compares markets:** ranks every Steam tag by how many of its popular games players rate poorly, against how many already serve them well.
- **Estimates sales and revenue** with the Box Method (reviews × 30–100).
- **Uses Steam's own review numbers** for analyzed games (the store page's "All Reviews"). Reviews from review-bomb periods count toward demand but not toward % positive.
- **Flags misleading numbers:** review bombs, sudden review spikes (a sale, an update, a streamer), deep discounts, very cheap prices, online multiplayer, niche audiences and AAA expectations. It also flags fading demand (few reviews lately) and games that are already improving (rated much better in the last 12 months).
- **Mines reviews:** what players complain about (bugs, controls, UI, content, performance, abandonment, ...), whether each complaint is still common lately, real quotes and a design pillar for each, plus what players love about the game. It reads both the most helpful and the newest reviews.
- **Ranks games** by an opportunity score. Hover a score to see exactly how it was calculated.
- **Remembers runs:** every search is saved, and a rerun shows which scores went up or down. Export a Markdown report or CSV.
- **English or Turkish interface:** web UI, command line and reports. Review analysis stays English.

## Installation

### One command

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/MertYilmaz41/steam-researcher/main/install.ps1 | iex"
```

**macOS / Linux:**

```sh
curl -LsSf https://raw.githubusercontent.com/MertYilmaz41/steam-researcher/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) if you don't have it, then the app with its own Python 3.13 (nothing else on your system changes). On Windows it also puts a **Steam Researcher** shortcut on the desktop. Start the app with the shortcut or by typing `steam-researcher`: it opens in your browser. The same `sr` commands described below work too (`sr report --tag ...`). Run the command again to update. No API keys are needed.

To remove it: `uv tool uninstall steam-researcher` (and delete the shortcut). Your saved runs stay in `~/.local/share/steam-researcher`.

### From the source code

For development, or to change the code. You need [uv](https://docs.astral.sh/uv/); it installs Python 3.13 by itself.

```powershell
# 1. Install uv (Windows; for macOS/Linux see https://docs.astral.sh/uv/)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Install dependencies, from the project folder
cd steam-researcher
uv sync

# 3. Optional: check that everything works
uv run pytest -q
```

## Usage

**Start the web UI.** It opens http://localhost:8501 in your browser. To stop it, close its window or press Ctrl+C in the terminal.

- Installed with the one command: use the **Steam Researcher** desktop shortcut (Windows), or type `steam-researcher`.
- From the source code: double-click **`Steam Researcher.bat`** (Windows), or run `uv run sr ui` in the project folder.

The page has a **top bar** (the Games | Markets | Shortlist views, the search box, How it works, and the language and theme switches), the **main area** (ranking, map, markets or shortlist), and the **details panel** that opens on the right when you pick a game. On a narrow window the details panel fills the screen.

Click the search box at the top and tick one or more Steam tags (up to 5; typing only filters the list). Games must have all the ticked tags. The button under the title shows the current **filters**; click it to change them (or pick a preset: Default, Proven demand, Quick look). Press **Search**. The page remembers your tags and filters for next time. While a search runs, each game appears as it is checked and scored; the first run of a tag takes about 30 seconds, and you can cancel it at any time.

- **List | Map:** the switch above the results shows the ranking as a list or as the opportunity map. The page remembers your choice.
- **Opportunity map (2D | 3D):** each bubble is a game. Left–right is demand (reviews) and height is dissatisfaction (% positive); in 3D, depth is fixability. Size is estimated revenue and color is the score (violet = high). The top right corner is the one the method looks for: proven demand, poor execution. Click a bubble to inspect it. In 3D, drag to orbit and scroll to zoom.
- **Market sentence:** under the title, how many of the tag's games with demand leave players disappointed, how many please them (85%+ positive), and the unmet share.
- **AI summary (optional):** the AI button under the title opens the summary; press **Write summary** and a local AI model reads the ranking and writes what players love, the complaints the games share, what a better game would do, and the caveats. Each point names the games it rests on; click one to open it. It takes about a minute, is saved with the run, and needs [Ollama](#optional-local-ai-for-the-summaries).
- **Ranking:** rank, game, score, biggest complaint and estimated revenue; a ⚠ −N badge marks games that lost points to risks. The first 8 show; **Show N more** lists the rest. ▲/▼ shows score changes since your previous run with the same tags and filters. Download the **Report (.md)** or the **CSV** above the list.
- **Details panel:** opens on the right when you click a row or a bubble, and closes with × or Esc. **Overview** has the score with a one-line why, the rating, reviews, last 12 months and estimated revenue, the top complaints with a quote, the risks that cost points, what players love and the game's tags (click one to search that tag). **Complaints** has every complaint category with trends, design pillars and quotes. **Summary** (optional, needs Ollama) has the local AI model read one game in about 20 seconds: why players are unhappy, what a better game would do, and complaints that fit none of the categories (e.g. price, cheaters), each with a quote. **History** has the monthly review chart and every risk check, passed or not.
- **What a term means:** every project-specific word (Fixability, Unmet share, Est. revenue, ...) has a small **i** next to it; hover or tap it for a one- or two-sentence explanation. **How it works** lists them all, plus every risk.
- **Score card:** hover or focus any score to see its three parts, their weights, each risk penalty and why.
- **Markets:** pick **Markets** in the top bar and press **Build market ranking** to rank every tag (about 7 minutes the first time, then from the cache). Find a tag by name, or show the small ones too. Click a tag to search it.
- **Shortlist:** press **Shortlist** in the details panel to keep a game. The **Shortlist** view shows the starred games with the score they had when you starred them; add a note to each, or download the list as CSV. It stays after a restart and a cache clear.
- **Past searches:** click the empty search box to reopen any earlier search or market ranking, even after a restart.
- **One game:** paste an AppID or a Steam store link into the search box and press Enter; the game opens in the details panel.
- **How it works:** the button at the top right explains the method, the filters, the score, the map and how accurate the complaint detection is.
- **Language and theme:** **EN | TR** at the top right switches between English and Turkish (the whole interface, including messages and the score card); the moon | sun switch next to it picks the dark or light theme. The page follows your system theme until you pick one, then remembers it.

**Command line.** The examples are written for the source code. If you installed with the one command, leave out `uv run`: type `sr report --tag "Job Simulator"`.

```powershell
uv run sr discover --tag "Job Simulator"           # list candidate games
uv run sr discover -t Crafting -t Survival         # games with all of these tags
uv run sr analyze 1330660                          # deep dive on one game (Steam AppID)
uv run sr analyze 1330660 --summary                # plus the game summary (needs Ollama)
uv run sr report --tag "Job Simulator"             # rank a tag, writes reports/job-simulator.md
uv run sr markets --top 30                         # rank every tag by underserved games
uv run sr report --tag "Job Simulator" --summary   # plus the opportunity summary (needs Ollama)
uv run sr runs                                     # saved runs (also in the web UI's past searches)
uv run sr --lang tr report --tag "Job Simulator"   # Turkish output and report
```

| Option | Example |
|---|---|
| Several tags (games must have all) | `-t Crafting -t Survival` |
| Minimum reviews | `--min-reviews 500` |
| % positive range | `--rating 20-60` |
| Games analyzed in a report | `--max-games 25` |
| Reviews read per game | `--reviews 300` |
| Report file | `--out my-report.md` |
| Language (`en` or `tr`, before the command) | `sr --lang tr ...`, or set `SR_LANG=tr` |
| Ignore cached data | `--no-cache` |
| Clear the cache | `uv run sr cache clear` |
| Help | `uv run sr --help`, `uv run sr report --help` |

The first run of a tag takes about 30 seconds because of API rate limits. After that, data comes from the cache in `~/.cache/steam-researcher` (refreshed daily, weekly for store details). Saved runs are kept separately in `~/.local/share/steam-researcher`, so clearing the cache keeps them.

### Optional: local AI for the summaries

The opportunity summary and the game summaries are written on your own computer by [Ollama](https://ollama.com) with the free `gemma4:12b` model (about 8 GB; a GPU with 12 GB+ of memory keeps it fast; Ollama 0.22 or newer). Nothing is sent to an online service. Everything else works without it.

```powershell
winget install Ollama.Ollama
ollama pull gemma4:12b
```

Treat the summaries as a first draft: check each point against the games and quotes it names.

## Tech stack

| Layer | Built with |
|---|---|
| **Language & tooling** | [Python 3.13](https://www.python.org/), managed with [uv](https://docs.astral.sh/uv/) (dependencies, virtual env, the `sr` and `steam-researcher` commands) |
| **Installation** | `install.ps1` / `install.sh` install the app as a [uv tool](https://docs.astral.sh/uv/concepts/tools/) with its own Python; packaged with `uv_build`, released to PyPI by a GitHub Actions workflow on version tags |
| **Command line** | [Typer](https://typer.tiangolo.com/) for commands and options, [Rich](https://rich.readthedocs.io/) for colored tables and progress |
| **Web server** | [FastAPI](https://fastapi.tiangolo.com/) on [Uvicorn](https://www.uvicorn.org/), bound to `127.0.0.1`. Long searches run as background jobs that the page polls |
| **Frontend** | Plain HTML, CSS and JavaScript ES modules, with **no build step and no framework**. The 2D map is hand-drawn SVG; the 3D map uses [three.js](https://threejs.org/) `0.170.0` from a CDN, and the page falls back to 2D without it |
| **Data models** | [Pydantic](https://docs.pydantic.dev/) for games, analyses, API payloads and saved runs |
| **HTTP** | [httpx](https://www.python-httpx.org/) with [tenacity](https://tenacity.readthedocs.io/) retries, per-host rate limiting and a SQLite response cache, so repeated runs barely touch Steam |
| **Storage** | [SQLite](https://www.sqlite.org/) (Python's built-in `sqlite3`): one database for the HTTP cache, a separate one for saved runs and the shortlist |
| **Review mining** | Regex keyword lexicon with negation handling and phrase counting. No ML dependencies; accuracy is measured against hand-labeled reviews |
| **Local AI (optional)** | [Ollama](https://ollama.com/) running `gemma4:12b` on your own machine, used only for the written summaries |
| **Reports** | [Jinja2](https://jinja.palletsprojects.com/) Markdown templates, plus CSV export |
| **Languages** | A small built-in English/Turkish i18n layer (Python and JS), with tests that fail if any text lacks a translation |
| **Testing & CI** | [pytest](https://pytest.org/) (unit, API and miner-accuracy tests), [Playwright](https://playwright.dev/python/) browser tests, plus a check that the built package installs and starts, run by GitHub Actions on every push |

```
SteamSpy / Steam APIs ──► HttpClient (rate limit, retry, SQLite cache)
                              │
                              ▼
            discover ─► verify "games only" ─► analyze each game
                                                 ├─ risk checks
                                                 ├─ review mining
                                                 ├─ Box Method revenue
                                                 └─ opportunity score
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        CLI (Typer)    Web UI (FastAPI)   Markdown / CSV report
                              │
                     Ollama summaries (optional)
```

## Data sources

- [SteamSpy](https://steamspy.com/api.php): games by tag, review counts, prices, tags.
- Steam Store: game details, the monthly review histogram, the tag list, and its search for the few tags SteamSpy can't search.
- Steam `IUserReviewsService/GetAppReviews`: review texts and the official review totals.

SteamDB isn't used because it has no public API.

## Is the method proven? A tool for exploring, not a forecast

The method assumes that where many players are unhappy, a better game will do well. The tool was tested against history to see if that holds at the market level (`uv run python -m steam_researcher.backtest --all`, report in `reports/backtest.md`):

- **How:** for 180 Steam tags, each tag's unmet share (underserved games / (underserved + well-served games)) was rebuilt as it was in January 2019, 2020, 2021 and 2022 from monthly review histories (32,000 games). Then the games released in the next 24 months were followed. A *hit* is a new game with 500+ reviews at 80%+ positive in its first two years; *sold* is 500+ reviews at any rating.
- **The rule, fixed before the results were seen:** the unmet share counts as a predictor only if tags with a higher share had more hits, beyond chance, also with market size held fixed, and the top fifth's hit rate was at least 1.25× the bottom fifth's.
- **Result: none of these held.**

  | Tags by unmet share (fifths) | Lowest | 2 | 3 | 4 | Highest |
  |---|---|---|---|---|---|
  | Hit rate (500+ reviews, 80%+ positive) | 11.6% | 11.2% | 11.0% | 11.0% | 10.7% |
  | Sold rate (500+ reviews) | 14.4% | 16.0% | 17.4% | 18.1% | 20.5% |

  The correlation of unmet share with the hit rate was −0.04 (95% interval −0.17 to +0.09): no link either way. With the sold rate it was +0.19 (+0.05 to +0.31).
- **What it means:** where the unmet share is high, players keep buying new games of that kind, so the demand is real. But the new games disappointed them about as often as the old ones; few of them were rated well. A high unmet share tells you where to look, not that a new game there will succeed. Making the better game is still on you.

So read the Markets view, the market strip and the unmet share as a **filter for exploring**: they narrow thousands of tags down to the ones worth a closer look. Then read the complaints and quotes of the games themselves. The backtest tests the tag-level share only; the per-game score and the complaint mining were not tested against later success. It also has known biases (games removed from Steam are missing, tags are today's), listed in the report.

## Limitations

- **The unmet share is not a proven predictor:** see [above](#is-the-method-proven-a-tool-for-exploring-not-a-forecast).

- **Revenue is a rough estimate:** full price, before Steam's cut, discounts and regional pricing.
- **Review mining is keyword-based and English-only.** On hand-labeled reviews from games it was never tuned on, it finds 64% of complaints, and 80% of what it reports is right. Read the quotes, not just the percentages.
- **No price history:** only the current price is checked for deep discounts.
- **SteamSpy tag lists may be incomplete**, and search results use SteamSpy's review counts until a game is analyzed.

