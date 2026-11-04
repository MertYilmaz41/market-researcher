# Steam Researcher

Find underserved Steam audiences: games people clearly wanted, but that disappointed them.

> **Proven Demand + Poor Execution = High Opportunity**

Based on CodeMonkey's Underserved Audience method: look for genres where players bought a game in large numbers but were let down by how it was made, then build the better version.

## What it does

- **Discovers** games in a tag (e.g. *Job Simulator*) with many reviews but a low rating (5–70% positive).
- **Estimates sales and revenue** with the Box Method (reviews × 30–100).
- **Flags misleading numbers:** review bombs, streamer spikes, deep discounts, online multiplayer, niche audiences.
- **Mines reviews:** what players complain about (bugs, controls, UI, content, ...), with real quotes and a design pillar for each, plus the "core fantasy" they loved.
- **Ranks games** by an opportunity score, in a Markdown report or a web UI with an interactive 3D opportunity map.

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

In the UI, type a tag (e.g. *Job Simulator*), adjust the **Filters** if you like, and press **Find opportunities**. The first run of a tag takes about 30 seconds.

- **3D opportunity map:** each sphere is a game. Left–right is demand, height is dissatisfaction and depth is fixability; size is estimated revenue and color is the score (red = low, green = high). Drag to orbit, scroll to zoom, and click a sphere to inspect it.
- **Detail panel:** score breakdown, revenue estimate, what players complain about (with quotes and design pillars), the core fantasy, risk checks and a monthly review chart.
- **Ranking table:** click a column header to sort, click a row to select a game, and download the Markdown report.
- **Single game:** paste an AppID or a Steam store link into the box at the top right.

**Command line:**

```powershell
uv run sr discover --tag "Job Simulator"    # list candidate games
uv run sr analyze 1330660                   # deep dive on one game (Steam AppID)
uv run sr report --tag "Job Simulator"      # rank a tag, writes reports/job-simulator.md
```

| Option | Example |
|---|---|
| Minimum reviews | `--min-reviews 500` |
| % positive range | `--rating 20-60` |
| Games analyzed in a report | `--max-games 25` |
| Ignore cached data | `--no-cache` |
| Clear the cache | `uv run sr cache clear` |
| Help | `uv run sr --help`, `uv run sr report --help` |

The first run of a tag takes about 30 seconds because of API rate limits. After that, data comes from the cache in `~/.cache/steam-researcher` (refreshed daily, weekly for store details).

## Data sources

- [SteamSpy](https://steamspy.com/api.php): games by tag, review counts, prices, tags.
- Steam Store: game details and the monthly review histogram.
- Steam `IUserReviewsService/GetAppReviews`: review texts.

SteamDB isn't used because it has no public API.

## Limitations

- **Revenue is a rough estimate:** full price, before Steam's cut, discounts and regional pricing.
- **Review mining is keyword-based and English-only.** It has some false positives (e.g. "I crashed" in a driving game counts as a bug), so read the quotes, not just the percentages.
- **No price history:** only the current price is checked for deep discounts.
- **SteamSpy tag lists may be incomplete.**
