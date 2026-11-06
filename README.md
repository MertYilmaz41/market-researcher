# Steam Researcher

Find underserved Steam audiences: games people clearly wanted, but that disappointed them.

> **Proven Demand + Poor Execution = High Opportunity**

Based on CodeMonkey's Underserved Audience method: look for genres where players bought a game in large numbers but were let down by how it was made, then build the better version.

## What it does

- **Discovers** games in one or more tags (e.g. *Job Simulator*, or *Crafting + Survival*) with many reviews but a low rating (5–70% positive).
- **Compares markets:** ranks every Steam tag by how many of its popular games players rate poorly, against how many already serve them well.
- **Estimates sales and revenue** with the Box Method (reviews × 30–100).
- **Uses Steam's own review numbers** for analyzed games (the store page's "All Reviews"). Reviews from review-bomb periods count toward demand but not toward % positive.
- **Flags misleading numbers:** review bombs, streamer spikes, deep discounts, very cheap prices, online multiplayer, niche audiences and AAA expectations. It also flags fading demand (few reviews lately) and games that are already improving (rated much better in the last 12 months).
- **Mines reviews:** what players complain about (bugs, controls, UI, content, performance, abandonment, ...), whether each complaint is still common lately, real quotes and a design pillar for each, plus the "core fantasy" they loved. It reads both the most helpful and the newest reviews.
- **Ranks games** by an opportunity score. Hover a score to see exactly how it was calculated.
- **Remembers runs:** every search is saved, and a rerun shows which scores went up or down. Export a Markdown report or CSV.
- **English or Turkish interface:** web UI, command line and reports. Review analysis stays English.

## Installation

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.13 by itself, and no API keys are needed.

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

**Easiest (Windows):** double-click **`Steam Researcher.bat`**. It starts the web UI and opens your browser; close the window to stop it.

**Web UI from a terminal.** This opens http://localhost:8501 in your browser; press Ctrl+C in the terminal to stop it.

```powershell
uv run sr ui
```

Click the tag field and tick one or more Steam tags (up to 5; typing only filters the list). Games must have all the ticked tags. Adjust the **Filters** if you like, and press **Find opportunities**. The first run of a tag takes about 30 seconds; you can cancel it at any time.

- **Opportunity map (2D | 3D):** each bubble is a game. Left–right is demand and height is dissatisfaction; in 3D, depth is fixability. Size is estimated revenue and color is the score (blue = low, gold = high). Click a bubble to inspect it. In 3D, drag to orbit and scroll to zoom.
- **Market strip:** how many games in the tag have demand, how many are underserved and how many are well served (85%+ positive), with a short verdict.
- **Opportunity summary (optional):** under the market strip, press **Write summary** and a local AI model reads the ranking and writes what players love, the complaints the games share, what a better game would do, and the caveats. Each point names the games it rests on; click one to open it. It takes about a minute, is saved with the run, and needs [Ollama](#optional-local-ai-for-the-summaries).
- **Detail panel:** score breakdown, review numbers and their source, the last 12 months of reviews, revenue estimate, what players complain about (with quotes, trends and design pillars), the core fantasy, risk checks and a monthly review chart. Its **Summary** tab (optional, needs Ollama) has the local AI model read one game in about 20 seconds: why players are unhappy, what a better game would do, and complaints that fit none of the complaint categories (e.g. price, cheaters), each with a quote from a review. It is saved with the run and added to the report.
- **Score card:** hover or focus any score to see its three parts, their weights, each risk penalty and why.
- **Ranking table:** click a column header to sort and a row to select a game. ▲/▼ shows score changes since your previous run with the same tags and filters. Download the **Report (.md)** or the **CSV**.
- **Markets:** switch the table to **Markets** and press **Build market ranking** to rank every tag (about 7 minutes the first time, then from the cache). Click a tag to search it.
- **Past runs:** reopen any earlier search or market ranking, even after a restart.
- **Single game:** paste an AppID or a Steam store link into the box at the top right.
- **Language:** the **EN | TR** switch at the top right changes the whole interface, including messages and the score card.

**Command line:**

```powershell
uv run sr discover --tag "Job Simulator"           # list candidate games
uv run sr discover -t Crafting -t Survival         # games with all of these tags
uv run sr analyze 1330660                          # deep dive on one game (Steam AppID)
uv run sr analyze 1330660 --summary                # plus the game summary (needs Ollama)
uv run sr report --tag "Job Simulator"             # rank a tag, writes reports/job-simulator.md
uv run sr markets --top 30                         # rank every tag by underserved games
uv run sr report --tag "Job Simulator" --summary   # plus the opportunity summary (needs Ollama)
uv run sr runs                                     # saved runs (also in the web UI's Past runs)
uv run sr --lang tr report --tag "Job Simulator"   # Turkish output and report
```

| Option | Example |
|---|---|
| Several tags (games must have all) | `-t Crafting -t Survival` |
| Minimum reviews | `--min-reviews 500` |
| % positive range | `--rating 20-60` |
| Games analyzed in a report | `--max-games 25` |
| Reviews mined per game | `--reviews 300` |
| Report file | `--out my-report.md` |
| Language (`en` or `tr`, before the command) | `sr --lang tr ...`, or set `SR_LANG=tr` |
| Ignore cached data | `--no-cache` |
| Clear the cache | `uv run sr cache clear` |
| Help | `uv run sr --help`, `uv run sr report --help` |

The first run of a tag takes about 30 seconds because of API rate limits. After that, data comes from the cache in `~/.cache/steam-researcher` (refreshed daily, weekly for store details). Saved runs are kept separately in `~/.local/share/steam-researcher`, so clearing the cache keeps them.

### Optional: local AI for the summaries

The opportunity summary and the game summaries are written on your own computer by [Ollama](https://ollama.com) with the free `gemma3:12b` model (about 8 GB; a GPU with 12 GB+ of memory keeps it fast). Nothing is sent to an online service. Everything else works without it.

```powershell
winget install Ollama.Ollama
ollama pull gemma3:12b
```

Treat the summaries as a first draft: check each point against the games and quotes it names.

## Data sources

- [SteamSpy](https://steamspy.com/api.php): games by tag, review counts, prices, tags.
- Steam Store: game details, the monthly review histogram, the tag list, and its search for the few tags SteamSpy can't search.
- Steam `IUserReviewsService/GetAppReviews`: review texts and the official review totals.

SteamDB isn't used because it has no public API.

## Limitations

- **Revenue is a rough estimate:** full price, before Steam's cut, discounts and regional pricing.
- **Review mining is keyword-based and English-only.** On hand-labeled reviews from games it was never tuned on, it finds 64% of complaints, and 80% of what it reports is right. Read the quotes, not just the percentages.
- **No price history:** only the current price is checked for deep discounts.
- **SteamSpy tag lists may be incomplete**, and search results use SteamSpy's review counts until a game is analyzed.
