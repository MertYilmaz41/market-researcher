"""Browser smoke test of the web UI (the JS has no unit tests).

Runs the real FastAPI app in a thread with the pipeline faked, and drives it with Playwright.
Skipped when Playwright or a browser is missing (CI installs Chromium: see .github/workflows/test.yml).
"""

import socket
import threading
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

from market_researcher.cache import Cache  # noqa: E402
from market_researcher.http import HttpClient  # noqa: E402
from market_researcher import pipeline  # noqa: E402
from market_researcher.market import TagMarket, TrackRecord, market_stats  # noqa: E402
from market_researcher.models import GameSummary, OpportunitySummary, OtherComplaint, SummaryPoint  # noqa: E402
from market_researcher.runs import RunStore  # noqa: E402
from market_researcher.web import server  # noqa: E402

from test_m4 import analysis, game  # noqa: E402
from test_web import fake_result  # noqa: E402

TAGS = ["Crafting", "Job Simulator", "Survival", "Colony Sim", "Building"]
# Nothing is pre-picked on a first visit: most tests start as a returning user with one tag remembered.
PICKED = "localStorage.getItem('filters') || localStorage.setItem('filters', JSON.stringify({tags: ['Job Simulator']}))"
ENGLISH = "localStorage.setItem('lang', 'en')"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    searches = []

    def run_tag(http, tags, *args):
        searches.append(tags)
        if tags == ["Survival"]:
            time.sleep(2)  # slow enough to analyze a game while it runs
        if tags == ["Colony Sim"]:  # runs until cancelled
            for i in range(3000):
                args[-2]("Analyzing games", i, 3000)
                time.sleep(0.01)
        r = fake_result()
        if tags == ["Building"]:  # games show one by one; one waits on its reviews; ten games in the end
            on_game = args[-1]
            on_game(1, "Best Sim", "done", 0, 0, analysis(60, "Best Sim", appid=1))
            on_game(5, "Stuck Game", "reviews", 100, 400, None)
            time.sleep(3)
            r.analyses = [analysis(50 - i, f"Game {i}", appid=10 + i) for i in range(10)]
        else:
            r.analyses[0].opportunity.penalty = 20  # "Other" is a risky game
            r.analyses[1].game.tags = {"Crafting": 90, "Building": 40}  # Best Sim's tag chips
        r.market = market_stats([a.game for a in r.analyses], 100, 5, 70)
        return r

    def run_markets(http, min_reviews, lo, hi, step):
        step("Reading tag Crafting", 1, 2)
        rows = [TagMarket(tag=t, stats=market_stats([game(), game(pos=950, neg=50, appid=2)], 100, 5, 70))
                for t in ["Survival", "Crafting"]]
        return pipeline.MarketsResult(rows=rows, skipped=["Incremental"])

    def track_record(http, tags, on_step):
        on_step("Reading review histories", 1, 2)
        time.sleep(0.5)  # long enough to see "Measuring"
        return TrackRecord(start=2022 * 12 + 10, entrants=40, hits=6, sold=12)

    mp.setattr(pipeline, "track_record", track_record)
    mp.setattr(server.steam_store, "tag_names", lambda http: TAGS)
    mp.setattr(pipeline, "run_tag", run_tag)
    mp.setattr(pipeline, "run_markets", run_markets)
    mp.setattr(pipeline, "analyze_game", lambda http, appid, n: analysis(45, "Lone Game", appid=appid))
    mp.setattr(server.summary, "write", lambda tag, analyses, market, lang, **kw: OpportunitySummary(
        pitch="A bus sim that works.", model="gemma3:12b",
        loved=[SummaryPoint(text="Driving the <b>bus</b>.", games=["Other"])]))
    mp.setattr(server.summary, "write_game", lambda a, negative, lang, **kw: GameSummary(
        why="Players hate the <i>cheaters</i>.", fix=["Anti-cheat"], model="gemma3:12b",
        other=[OtherComplaint(text="Cheaters", quote="cheaters everywhere")]))
    mp.setattr(server.pipeline, "review_sample", lambda http, appid, kind, limit: [])
    mp.setattr(server, "_runs", RunStore(tmp_path_factory.mktemp("runs") / "runs.sqlite"))
    mp.setattr(server, "_jobs", {})
    mp.setattr(server, "_http_client", HttpClient(cache=Cache(tmp_path_factory.mktemp("cache") / "cache.sqlite")))

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(5)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        for kwargs in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                b = p.chromium.launch(**kwargs)
                break
            except Exception:
                continue
        else:
            pytest.skip("no browser for Playwright (run: uv run playwright install chromium)")
        yield b
        b.close()


def _open(browser, base_url, width=1400, height=900, picked=True, english=True):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    if english:
        page.add_init_script(ENGLISH)
    if picked:
        page.add_init_script(PICKED)
    page.goto(base_url)
    if picked:
        page.wait_for_selector(".tag-chip")  # app.js is running
    return page


def _search(page):
    page.click("#run")
    page.wait_for_selector("#ranking tbody tr")


def _tick(page, *tags):
    """Open the search box's list, click each tag (ticks or unticks it), close the list."""
    page.click("#tag")
    for t in tags:
        page.locator(f'#tag-list li[role=option][data-tag="{t}"]').click()
    page.keyboard.press("Escape")


def _chips(page):
    return page.eval_on_selector_all(".tag-chip", "cs => cs.map(c => c.firstChild.textContent)")


def _setting(page, button):
    """Language and theme are two separate switches in the top bar."""
    page.click(button)


def test_ui_smoke(base_url, browser):
    page = _open(browser, base_url, english=False)

    # Tick two tags in the search box (Job Simulator is remembered: untick it).
    _tick(page, "Job Simulator", "Crafting", "Colony Sim")
    assert _chips(page) == ["Crafting", "Colony Sim"]

    _search(page)
    assert page.locator("#ranking tbody tr").count() == 2
    assert page.text_content("#table-title") == "Crafting + Colony Sim"
    assert page.is_visible("#market-line") and "games with demand" in page.inner_text("#market-line")
    assert page.is_visible("#download") and page.is_visible("#download-csv")
    # The risky game shows its penalty in the list.
    assert "−20" in page.inner_text('#ranking tr[data-appid="2"] .risk-badge')

    # Hovering a score explains it; moving away hides it.
    page.hover("#ranking tbody tr:first-child .score-pill")
    tip = page.inner_text("#score-tip")
    for text in ["Opportunity score 60", "Demand", "Dissatisfaction", "Fixability", "Combined", "weight 40%"]:
        assert text in tip
    page.mouse.move(5, 5)
    assert page.is_hidden("#score-tip")

    # The first game opens in the drawer; x closes it, clicking a row opens it again.
    assert page.is_visible("#drawer") and page.text_content("#panel h3") == "Best Sim"
    page.click("#drawer-close")
    assert page.is_hidden("#drawer") and page.locator("#ranking tbody tr.selected").count() == 0
    page.click("#ranking tbody tr:first-child td:nth-child(2)")
    assert page.is_visible("#drawer")
    page.keyboard.press("Escape")
    assert page.is_hidden("#drawer")

    # 2D map (Map mode): a bubble per game; clicking one shows it in the drawer.
    page.click('#games-mode button[data-mode="map"]')
    assert page.is_hidden("#ranking") and page.is_visible("#map")
    assert page.locator(".map2d .bubble").count() == 2
    page.locator(".map2d .bubble").last.click()
    assert page.text_content("#panel h3") in ("Best Sim", "Other")
    page.click('#games-mode button[data-mode="table"]')

    # Open a game by AppID (pasted into the search box) while a (slow) search runs.
    page.evaluate("document.querySelector('#toasts').replaceChildren()")
    _tick(page, "Crafting", "Colony Sim", "Survival")
    page.click("#run")
    page.wait_for_selector("body.searching")
    page.fill("#tag", "777")
    assert page.is_visible("#tag-list li.open-game")
    page.press("#tag", "Enter")
    page.wait_for_function("document.querySelector('#panel h3')?.textContent === 'Lone Game'")
    assert "searching" in page.get_attribute("body", "class")
    page.wait_for_function("!document.body.classList.contains('searching')", timeout=10_000)
    assert page.text_content("#panel h3") == "Lone Game"  # the finished search keeps it

    # Markets view: build, then click a tag to search it.
    page.click('#table-view button[data-view="markets"]')
    page.click("#markets-run")
    page.wait_for_selector("#market-tools")
    assert page.locator("#markets tbody tr").count() == 0 and page.is_hidden("#market-cards")  # 20+ only
    page.uncheck("#market-big")  # the fake markets are small
    assert page.locator("#markets tbody tr").count() == 2 and page.locator("#market-cards .market-card").count() == 2
    assert "Incremental" not in page.text_content("#markets tbody")
    page.click("#markets tbody tr:first-child")
    page.wait_for_function("!document.body.classList.contains('searching') && "
                           "document.querySelector('#table-title').textContent === 'Survival'",
                           timeout=10_000)
    assert page.is_visible("#games-view")

    # Past searches, listed in the empty search box: reopening the first brings its tags back.
    page.click("#tag")
    page.wait_for_selector("#runs-list li .run-main")
    labels = page.eval_on_selector_all("#runs-list .run-main b", "bs => bs.map(b => b.textContent)")
    assert labels == ["Survival", "Markets: all tags", "Survival", "Crafting + Colony Sim"]
    page.click("#runs-list li:last-child .run-main")
    page.wait_for_function("document.querySelector('#table-title').textContent === 'Crafting + Colony Sim'")
    assert sorted(_chips(page)) == ["Colony Sim", "Crafting"]

    # Cancel a search: the button frees at once and the previous results come back.
    _tick(page, "Crafting")  # untick it: only Colony Sim, whose fake search runs until cancelled
    page.click("#run")
    page.wait_for_selector("#search-status .cancel-run")
    page.click("#search-status .cancel-run")
    page.wait_for_function("!document.body.classList.contains('searching')", timeout=3000)
    assert page.is_hidden("#search-status") and page.text_content("#run") == "Search"
    assert "Search cancelled" in page.inner_text("#toasts")
    assert page.text_content("#table-title") == "Crafting + Colony Sim"  # previous results stay

    assert page.errors == []


def test_ui_live_list_and_slow_reviews(base_url, browser, monkeypatch):
    monkeypatch.setattr(server, "SLOW_REVIEW_SECONDS", 1)
    page = _open(browser, base_url)
    _tick(page, "Job Simulator", "Building")
    page.click("#run")

    # While it runs: the step card and each game as it goes, finished ones with their score.
    page.wait_for_selector("#live-table tbody tr >> nth=1")
    assert page.is_visible("#search-status") and "Step 2 of 3" in page.text_content("#search-status .step-badge")
    live = page.inner_text("#live-table")
    assert "Best Sim" in live and "Stuck Game" in live and "Reading reviews · 100 / 400" in live
    assert page.is_hidden("#results")
    # A game stuck on its review pages: warned once.
    page.wait_for_function("document.querySelector('#toasts').innerText.includes(\"Steam's review service is slow\")")

    # Done: the first 8 games, the rest behind "Show 2 more".
    page.wait_for_selector("#ranking tbody tr")
    assert page.is_hidden("#live") and page.locator("#ranking tbody tr").count() == 8
    assert page.text_content("#show-more") == "Show 2 more"
    page.click("#show-more")
    assert page.locator("#ranking tbody tr").count() == 10 and page.is_hidden("#show-more")
    assert page.text_content("#toasts").count("Steam's review service is slow") == 1
    assert page.errors == []


def test_ui_turkish(base_url, browser):
    page = _open(browser, base_url, english=False)
    _search(page)
    page.click("#ranking tbody tr:first-child")

    # Switch to Turkish with results on screen: everything is redrawn, nothing is lost.
    _setting(page, '#lang button[data-lang="tr"]')
    page.wait_for_function("document.querySelector('#run').textContent === 'Ara'")
    assert page.get_attribute("html", "lang") == "tr"
    assert page.get_attribute('#lang button[data-lang="tr"]', "aria-pressed") == "true"
    assert page.inner_text("#help-toggle").strip() == "Nasıl çalışır?"
    assert page.text_content("#ranking thead th:nth-child(3)") == "Puan"
    assert page.locator("#ranking tbody tr").count() == 2
    assert "Şikayetler" in page.inner_text("#panel .tabs") and "Genel bakış" in page.inner_text("#panel .tabs")
    page.hover("#ranking tbody tr:first-child .score-pill")
    tip = page.inner_text("#score-tip")
    assert "Fırsat puanı" in tip and "Talep" in tip and "Düzeltilebilirlik" in tip  # server text too
    page.mouse.move(5, 5)

    # The server's toasts and the report link follow the language.
    page.evaluate("document.querySelector('#toasts').replaceChildren()")
    page.click("#run")
    page.wait_for_function("document.querySelector('#toasts').innerText.includes('Analiz tamamlandı')")
    assert page.get_attribute("#download", "href").endswith("lang=tr")

    # Remembered after a reload; back to English with one click.
    page.reload()
    page.wait_for_selector(".tag-chip")
    assert page.text_content("#run") == "Ara"
    _setting(page, '#lang button[data-lang="en"]')
    assert page.text_content("#run") == "Search"
    assert page.text_content("#ranking thead th:nth-child(3)") == "Score"
    assert page.errors == []


def test_ui_opportunity_summary(base_url, browser):
    page = _open(browser, base_url)
    _search(page)
    assert page.is_visible("#ai-chip") and page.text_content("#ai-chip-text") == "Write an AI summary"
    assert page.is_hidden("#opp-summary")

    page.click("#ai-chip")
    # The market's price range is there before the summary is written (worked out from the data).
    assert "Price range in this market: median $9.99" in page.inner_text("#opp-summary .opp-price")
    page.click("#opp-summary .opp-empty button")
    page.wait_for_selector("#opp-summary .opp-pitch")
    body = page.inner_text("#opp-summary .opp-body")
    assert "A bus sim that works." in body and "WHAT PLAYERS LOVE" in body.upper()
    assert "Driving the <b>bus</b>." in body  # model text is shown as text, never as HTML
    assert page.text_content("#ai-chip-text").startswith("AI summary: A bus sim that works.")

    page.click("#opp-summary .opp-games button")  # a game chip opens that game
    assert page.text_content("#panel h3") == "Other"
    assert page.errors == []


def test_ui_game_summary_tab(base_url, browser):
    page = _open(browser, base_url)
    _search(page)
    page.click("#panel .tabs button:has-text('Summary')")
    page.click("#panel .opp-empty button")
    page.wait_for_selector("#panel .game-summary")
    text = page.inner_text("#panel .game-summary")
    assert "Players hate the <i>cheaters</i>." in text  # model text is shown as text, never as HTML
    assert "cheaters everywhere" in text and "Anti-cheat" in text
    assert page.get_attribute("#panel .tabs button.active", "role") == "tab"
    assert "Summary" in page.text_content("#panel .tabs button.active")  # stays on the tab
    assert page.errors == []


def test_ui_overview_and_history_tabs(base_url, browser):
    page = _open(browser, base_url)
    _search(page)
    # Overview: the score ring with its verdict and why, the four facts, links to the other tabs.
    assert page.get_attribute("#panel-tab-0", "aria-selected") == "true"
    assert page.is_visible("#panel .score-ring") and page.text_content("#panel .why .verdict")
    assert page.locator("#panel .facts .stat").count() == 4
    assert "[object" not in page.inner_text("#panel")  # nested nodes are appended, never stringified
    page.click("#panel .links button:has-text('Review history')")
    assert page.get_attribute("#panel-tab-3", "aria-selected") == "true"
    # History: every risk check, passed or flagged.
    page.wait_for_selector("#panel .checks .check-row")
    assert page.locator("#panel .checks .check-row").count() >= 5
    assert page.errors == []


def test_ui_remembers_filters_and_tags(base_url, browser):
    page = _open(browser, base_url)
    page.click("#filters-toggle")  # the filters sit behind the summary button under the title
    assert page.is_visible("#filters")
    page.click("#filters [data-preset=quick]")  # a preset only fills the fields
    assert page.input_value("#max-games") == "8" and page.input_value("#reviews") == "100"
    page.fill("#min-reviews", "250")
    page.press("#min-reviews", "Tab")  # change event
    assert page.text_content("#filters-summary").startswith("250+ reviews")
    page.keyboard.press("Escape")
    assert page.is_hidden("#filters")
    _tick(page, "Survival")

    page.reload()
    page.wait_for_selector(".tag-chip")
    assert page.input_value("#min-reviews") == "250" and page.input_value("#max-games") == "8"
    assert _chips(page) == ["Job Simulator", "Survival"]
    assert page.errors == []


def test_ui_top_bar_switches(base_url, browser):
    page = _open(browser, base_url)
    # How it works has a visible label; language and theme are separate switches, both always shown
    assert page.inner_text("#help-toggle").strip() == "How it works"
    assert page.is_visible("#lang") and page.is_visible("#theme")
    assert page.query_selector("#lang #theme, #theme #lang") is None
    page.click('#theme button[data-theme="light"]')
    assert page.get_attribute("html", "data-theme") == "light"
    assert page.get_attribute('#lang button[data-lang="en"]', "aria-pressed") == "true"  # the language didn't change
    assert page.errors == []


def test_ui_track_record_after_a_search(base_url, browser):
    page = _open(browser, base_url)
    _search(page)
    page.wait_for_function("document.querySelector('#track-line').innerText.includes('Track record: 6 of 40 games')")
    assert page.is_visible("#track-line .info[data-term=track_record]")
    assert page.errors == []


def test_ui_cache_settings(base_url, browser, monkeypatch):
    from market_researcher import config
    server._http().cache.set("old", {"a": "x" * 10_000}, ttl=-1)
    monkeypatch.setattr(config, "CACHE_WARN_BYTES", 0)
    page = _open(browser, base_url)
    # A big cache warns once at load, and the ⚙ gets a dot.
    page.wait_for_function("document.querySelector('#toasts').innerText.includes('The cache takes')")
    assert "has-dot" in page.get_attribute("#settings-toggle", "class")
    page.click("#settings-toggle")
    page.wait_for_function("document.querySelector('#cache-size').textContent.includes('MB')")
    assert "1 expired entries" in page.text_content("#cache-size")
    page.click("#cache-prune")
    page.wait_for_function("document.querySelector('#toasts').innerText.includes('Cache cleaned')")
    assert "0 expired entries" in page.text_content("#cache-size")
    page.keyboard.press("Escape")
    assert page.is_hidden("#settings")
    assert page.errors == []


def test_ui_logo_goes_home(base_url, browser):
    page = _open(browser, base_url)
    _search(page)
    page.click("#ranking tbody tr:first-child")
    page.click('#table-view button[data-view="shortlist"]')
    chips = _chips(page)
    with page.expect_navigation():
        page.click(".brand")
    # the start page: the Games view, no result, no game open; tags and filters stay remembered
    page.wait_for_selector("#tag-form")
    assert page.get_attribute('#table-view button[data-view="games"]', "aria-pressed") == "true"
    assert page.query_selector_all("#ranking tbody tr") == [] and page.is_hidden("#drawer")
    page.wait_for_function(f"document.querySelectorAll('.tag-chip').length === {len(chips)}")
    assert _chips(page) == chips


def test_ui_shortlist(base_url, browser):
    page = _open(browser, base_url)
    _search(page)

    page.click("#panel .star")
    page.wait_for_selector("#panel .star.on")
    assert page.text_content("#shortlist-count") == "1"
    page.click('#table-view button[data-view="shortlist"]')
    page.wait_for_selector("#shortlist .sl-card")
    assert "Best Sim" in page.inner_text("#shortlist .sl-card") and page.is_visible("#shortlist-csv")
    page.fill("#shortlist textarea.note", "Better bus <b>physics</b>")
    page.press("#shortlist textarea.note", "Tab")
    page.wait_for_selector("text=Note saved")

    page.reload()
    page.wait_for_selector(".tag-chip")
    page.click('#table-view button[data-view="shortlist"]')
    page.wait_for_selector("#shortlist .sl-card")
    assert page.input_value("#shortlist textarea.note") == "Better bus <b>physics</b>"
    page.click("#shortlist .sl-card .remove")
    page.wait_for_function("!document.querySelector('#shortlist .sl-card')")
    assert "No games yet" in page.text_content("#shortlist-note") and page.is_hidden("#shortlist-csv")
    assert page.errors == []


def test_ui_tag_chips_search_one_tag(base_url, browser):
    page = _open(browser, base_url)
    _search(page)
    # A tag chip in the panel searches that one tag.
    page.locator("#panel .chips button.chip").first.click()
    page.wait_for_selector("text=Only this tag")
    page.wait_for_function("document.querySelector('#table-title').textContent === 'Crafting' && "
                           "!document.body.classList.contains('searching')")
    assert _chips(page) == ["Crafting"]
    assert page.errors == []


def test_ui_help_dialog(base_url, browser):
    page = _open(browser, base_url)
    page.click("#help-toggle")
    assert page.is_visible("#help") and page.locator("#help section").count() == 11
    assert "80%" in page.inner_text("#help") and "not shown to predict success" in page.inner_text("#help")
    glossary = page.inner_text("#help-terms")
    assert "Fixability" in glossary and "Unmet share" in glossary and "Fading demand" in page.inner_text("#help-risks")
    page.keyboard.press("Escape")
    assert page.is_hidden("#help")

    # An info button explains its term on hover.
    page.hover('#ranking th .info[data-term="revenue"]')
    assert page.is_visible("#term-tip") and "Box Method" in page.inner_text("#term-tip")
    page.mouse.move(5, 5)
    assert page.is_hidden("#term-tip")

    # Dark | light: the switch sets the theme on <html> and remembers it across a reload.
    assert page.get_attribute("html", "data-theme") in ("dark", "light")
    _setting(page, '#theme button[data-theme="light"]')
    assert page.get_attribute("html", "data-theme") == "light"
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.reload()
    page.wait_for_selector(".tag-chip")
    assert page.get_attribute("html", "data-theme") == "light"
    assert page.get_attribute('#theme button[data-theme="light"]', "aria-pressed") == "true"
    _setting(page, '#theme button[data-theme="dark"]')
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != bg

    _setting(page, '#lang button[data-lang="tr"]')
    page.click("#help-toggle")
    assert page.text_content("#help-title") == "Nasıl çalışır?" and "Skor" in page.inner_text("#help")
    assert "Karşılanmama oranı" in page.inner_text("#help-terms")
    page.click("#help .help-head button")
    assert page.is_hidden("#help")
    assert page.errors == []


def test_ui_keyboard(base_url, browser):
    page = _open(browser, base_url)
    _search(page)
    active = lambda: page.evaluate("document.activeElement.id || document.activeElement.dataset.appid || ''")  # noqa: E731
    # The page opens the top game by itself, without pulling the focus into the drawer.
    assert page.is_visible("#drawer") and active() != "drawer-close"
    page.keyboard.press("Escape")

    # A row opens with Enter; the focus moves to the drawer and comes back to the row on Esc.
    row = page.locator("#ranking tbody tr").nth(1)
    appid = row.get_attribute("data-appid")
    row.focus()
    page.keyboard.press("Enter")
    assert page.is_visible("#drawer") and active() == "drawer-close"
    # Tabs: arrow keys move the selection.
    page.focus('#panel [role=tab][aria-selected="true"]')
    page.keyboard.press("ArrowRight")
    assert page.get_attribute('#panel [role=tab][aria-selected="true"]', "id") == "panel-tab-1"
    assert active() == "panel-tab-1"
    page.keyboard.press("Escape")
    assert page.is_hidden("#drawer") and active() == appid
    assert page.errors == []


def test_ui_first_visit_and_narrow_screen(base_url, browser):
    page = _open(browser, base_url, width=800, picked=False)
    page.focus("#tag")  # opens the list (once the tags are in)
    page.wait_for_selector("#tag-list li[role=option]")
    # A first visit picks no tag; the filters say the first search is slow.
    assert page.locator(".tag-chip").count() == 0
    page.locator('#tag-list li[data-tag="Crafting"]').click()
    page.keyboard.press("Escape")
    page.click("#filters-toggle")
    assert page.is_visible("#run-hint")
    page.keyboard.press("Escape")
    _search(page)
    # On a narrow screen the ranking stays in view: no game opens by itself.
    assert page.is_hidden("#drawer")
    # The run's warnings stay listed above the ranking and can be dismissed.
    items = page.locator("#result-notices li")
    if items.count():
        n = items.count()
        page.click("#result-notices li .close")
        assert items.count() == n - 1
    assert page.errors == []


def test_ui_phone_sheet(base_url, browser):
    page = _open(browser, base_url, width=390, height=800)
    _search(page)
    assert page.is_hidden("#drawer")
    page.click("#ranking tbody tr:first-child")
    # The game is a full-screen sheet: back to the ranking at the top, the actions stuck to the bottom.
    assert page.is_visible("#drawer") and page.is_visible("#sheet-back") and page.is_hidden("#drawer-close")
    assert page.text_content("#sheet-pos") == "1 of 2"
    assert page.evaluate("getComputedStyle(document.querySelector('#panel .actions')).position") == "sticky"
    assert page.evaluate("document.querySelector('#drawer').getBoundingClientRect().width") >= 380
    assert page.evaluate("document.documentElement.scrollWidth") <= 390  # no sideways scrolling
    page.click("#sheet-back")
    assert page.is_hidden("#drawer")
    assert page.errors == []


def test_ui_star_a_game_analyzed_by_appid(base_url, browser):
    page = _open(browser, base_url)
    page.fill("#tag", "https://store.steampowered.com/app/4242/Lone_Game/")
    page.click("#tag-list li.open-game")
    page.wait_for_function("document.querySelector('#panel h3')?.textContent === 'Lone Game'")
    page.click("#panel .star")
    page.wait_for_selector('#panel .star.on[data-appid="4242"]')
    page.click('#table-view button[data-view="shortlist"]')
    card = page.locator('#shortlist .sl-card[data-appid="4242"]')
    assert "Lone Game" in card.inner_text() and "AppID" in card.inner_text()
    page.click("#panel .star")  # unstar
    page.wait_for_selector('#panel .star:not(.on)[data-appid="4242"]')
    assert page.errors == []
