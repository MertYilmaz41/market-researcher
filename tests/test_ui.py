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

from steam_researcher.cache import Cache  # noqa: E402
from steam_researcher.http import HttpClient  # noqa: E402
from steam_researcher import pipeline  # noqa: E402
from steam_researcher.market import TagMarket, market_stats  # noqa: E402
from steam_researcher.models import GameSummary, OpportunitySummary, OtherComplaint, SummaryPoint  # noqa: E402
from steam_researcher.runs import RunStore  # noqa: E402
from steam_researcher.web import server  # noqa: E402

from test_m4 import analysis, game  # noqa: E402
from test_web import fake_result  # noqa: E402

TAGS = ["Crafting", "Job Simulator", "Survival", "Colony Sim"]


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
                args[-1]("Analyzing games", i, 3000)
                time.sleep(0.01)
        r = fake_result()
        r.analyses[0].opportunity.penalty = 20  # "Other" is a risky game (for the quick filter)
        r.analyses[1].game.tags = {"Crafting": 90, "Building": 40}  # Best Sim's tag chips
        r.market = market_stats([a.game for a in r.analyses], 100, 5, 70)
        return r

    def run_markets(http, min_reviews, lo, hi, step):
        step("Reading tag Crafting", 1, 2)
        rows = [TagMarket(tag=t, stats=market_stats([game(), game(pos=950, neg=50, appid=2)], 100, 5, 70))
                for t in ["Survival", "Crafting"]]
        return pipeline.MarketsResult(rows=rows, skipped=["Incremental"])

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


def test_ui_smoke(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d')")  # no CDN/WebGL needed
    page.goto(base_url)

    # Tick two tags in the checklist (Job Simulator is pre-picked: untick it).
    page.wait_for_selector(".tag-chip")
    page.click("#tag-toggle")
    opt = lambda t: page.locator(f'#tag-list li[role=option][data-tag="{t}"]')  # noqa: E731
    for t in ["Job Simulator", "Crafting", "Colony Sim"]:
        opt(t).click()
    page.keyboard.press("Escape")
    assert page.eval_on_selector_all(".tag-chip", "cs => cs.map(c => c.firstChild.textContent)") == ["Crafting", "Colony Sim"]

    page.click("#run")
    page.wait_for_selector("#ranking tbody tr")
    assert page.locator("#ranking tbody tr").count() == 2
    assert "Crafting + Colony Sim" in page.text_content("#table-title")
    assert page.is_visible("#market-strip") and "UNDERSERVED" in page.inner_text("#market-strip").upper()
    assert page.is_visible("#download") and page.is_visible("#download-csv")

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
    page.click("#ranking tbody tr:first-child td:nth-child(3)")
    assert page.is_visible("#drawer")
    page.keyboard.press("Escape")
    assert page.is_hidden("#drawer")

    # 2D map (Map mode): a bubble per game; clicking one shows it in the drawer.
    page.click('#games-mode button[data-mode="map"]')
    assert page.is_hidden("#ranking") and page.is_visible("#map-view")
    assert page.locator(".map2d .bubble").count() == 2
    page.locator(".map2d .bubble").last.click()
    assert page.text_content("#panel h3") in ("Best Sim", "Other")
    page.click('#games-mode button[data-mode="table"]')

    # Analyze a game while a (slow) search runs.
    page.evaluate("document.querySelector('#toasts').replaceChildren()")
    page.click("#tag-toggle")
    for t in ["Crafting", "Colony Sim", "Survival"]:
        opt(t).click()
    page.keyboard.press("Escape")
    page.click("#run")
    page.wait_for_selector("body.searching")
    page.fill("#appid", "777")
    page.press("#appid", "Enter")
    page.wait_for_function("document.querySelector('#panel h3')?.textContent === 'Lone Game'")
    assert "searching" in page.get_attribute("body", "class")
    page.wait_for_function("!document.body.classList.contains('searching')", timeout=10_000)
    assert page.text_content("#panel h3") == "Lone Game"  # the finished search keeps it

    # Markets view: build, then click a tag to search it.
    page.click('#table-view button[data-view="markets"]')
    page.click("#markets-run")
    page.wait_for_selector("#markets tbody tr")
    assert page.locator("#markets tbody tr").count() == 2
    assert "Incremental" not in page.text_content("#markets tbody")
    page.click("#markets tbody tr:first-child")
    page.wait_for_function("!document.body.classList.contains('searching') && "
                           "document.querySelector('#table-title').textContent.startsWith('Survival:')",
                           timeout=10_000)
    assert page.is_visible("#games-view")

    # Past runs: all four runs are listed; reopening the first search brings its tags back.
    page.click("#runs-toggle")
    page.wait_for_selector("#runs-list li .run-main")
    labels = page.eval_on_selector_all("#runs-list .run-main b", "bs => bs.map(b => b.textContent)")
    assert labels == ["Survival", "Markets: all tags", "Survival", "Crafting + Colony Sim"]
    page.click("#runs-list li:last-child .run-main")
    page.wait_for_function("document.querySelector('#table-title').textContent.startsWith('Crafting + Colony Sim')")
    assert sorted(page.eval_on_selector_all(".tag-chip", "cs => cs.map(c => c.firstChild.textContent)")) == ["Colony Sim", "Crafting"]

    # Cancel a search: the button frees at once and the previous results come back.
    page.keyboard.press("Escape")
    page.click("#tag-toggle")
    opt("Crafting").click()  # untick it: only Colony Sim, whose fake search runs until cancelled
    page.keyboard.press("Escape")
    page.click("#run")
    page.wait_for_selector("#search-status .cancel-run")
    page.click("#search-status .cancel-run")
    page.wait_for_function("!document.body.classList.contains('searching')", timeout=3000)
    assert page.is_hidden("#search-status") and page.text_content("#run") == "Find opportunities"
    assert "Search cancelled" in page.inner_text("#toasts")
    assert page.text_content("#table-title").startswith("Crafting + Colony Sim")  # previous results stay

    assert errors == []


def test_ui_turkish(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d')")
    page.goto(base_url)
    page.wait_for_selector(".tag-chip")  # Job Simulator is pre-picked
    page.click("#run")
    page.wait_for_selector("#ranking tbody tr")
    page.click("#ranking tbody tr:first-child")

    # Switch to Turkish with results on screen: everything is redrawn, nothing is lost.
    page.click('#lang button[data-lang="tr"]')
    page.wait_for_function("document.querySelector('#table-title').textContent.includes('fırsat sıralaması')")
    assert page.get_attribute("html", "lang") == "tr"
    assert page.text_content("#run") == "Fırsatları bul"
    assert page.text_content('#ranking th[data-key="score"]') == "Puan"
    assert page.locator("#ranking tbody tr").count() == 2
    assert "Şikayetler" in page.inner_text("#panel .tabs")
    assert "olumlu" in page.text_content("#map-legend") or "talep" in page.text_content("#map-legend")
    page.hover("#ranking tbody tr:first-child .score-pill")
    tip = page.inner_text("#score-tip")
    assert "Fırsat puanı" in tip and "Talep" in tip and "Düzeltilebilirlik" in tip  # server text too
    page.mouse.move(5, 5)

    # Toasts: the page's own and the server's.
    page.evaluate("document.querySelector('#toasts').replaceChildren()")
    page.fill("#appid", "abc")
    page.press("#appid", "Enter")
    assert "AppID ya da Steam mağaza linki değil" in page.inner_text("#toasts")
    page.click("#run")
    page.wait_for_function("document.querySelector('#toasts').innerText.includes('Analiz tamamlandı')")
    assert page.get_attribute("#download", "href").endswith("lang=tr")

    # Remembered after a reload; back to English with one click.
    page.reload()
    page.wait_for_selector(".tag-chip")
    assert page.text_content("#run") == "Fırsatları bul"
    page.click('#lang button[data-lang="en"]')
    assert page.text_content("#run") == "Find opportunities"
    assert page.text_content('#ranking th[data-key="score"]') == "Score"
    assert errors == []


def test_ui_opportunity_summary(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d'); localStorage.setItem('lang', 'en')")
    page.goto(base_url)
    page.wait_for_selector(".tag-chip")
    page.click("#run")
    page.wait_for_selector("#ranking tbody tr")
    assert page.is_visible("#opp-summary") and "not written yet" in page.text_content("#opp-summary summary")

    page.click("#opp-summary summary")
    page.click("#opp-summary .opp-body button")
    page.wait_for_selector("#opp-summary .opp-pitch")
    body = page.inner_text("#opp-summary .opp-body")
    assert "A bus sim that works." in body and "WHAT PLAYERS LOVE" in body.upper()
    assert "Driving the <b>bus</b>." in body  # model text is shown as text, never as HTML

    page.click("#opp-summary .opp-games button")  # a game chip opens that game
    assert page.text_content("#panel h3") == "Other"
    assert errors == []


def test_ui_game_summary_tab(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d'); localStorage.setItem('lang', 'en')")
    page.goto(base_url)
    page.wait_for_selector(".tag-chip")
    page.click("#run")
    page.wait_for_selector("#ranking tbody tr")
    page.click("#panel .tabs button:has-text('Summary')")
    page.click("#panel .opp-empty button")
    page.wait_for_selector("#panel .game-summary")
    text = page.inner_text("#panel .game-summary")
    assert "Players hate the <i>cheaters</i>." in text  # model text is shown as text, never as HTML
    assert '"cheaters everywhere"' in text and "Anti-cheat" in text
    assert page.get_attribute("#panel .tabs button.active", "role") == "tab"
    assert "Summary" in page.text_content("#panel .tabs button.active")  # stays on the tab
    assert errors == []


def test_ui_remembers_filters_and_tags(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d'); localStorage.setItem('lang', 'en')")
    page.goto(base_url)
    page.wait_for_selector(".tag-chip")

    page.click("#filters [data-preset=quick]")  # the Filters section is open on wide screens  # a preset only fills the fields
    assert page.input_value("#max-games") == "8" and page.input_value("#reviews") == "100"
    page.fill("#min-reviews", "250")
    page.press("#min-reviews", "Tab")  # change event
    page.click("#tag-toggle")
    page.locator('#tag-list li[role=option][data-tag="Survival"]').click()
    page.keyboard.press("Escape")

    page.reload()
    page.wait_for_selector(".tag-chip")
    assert page.input_value("#min-reviews") == "250" and page.input_value("#max-games") == "8"
    chips = page.eval_on_selector_all(".tag-chip", "cs => cs.map(c => c.firstChild.textContent)")
    assert chips == ["Job Simulator", "Survival"]
    assert errors == []


def test_ui_shortlist(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d'); localStorage.setItem('lang', 'en')")
    page.goto(base_url)
    page.wait_for_selector(".tag-chip")
    page.click("#run")
    page.wait_for_selector("#ranking tbody tr")

    page.click("#ranking tbody tr:first-child .star")
    page.wait_for_selector("#ranking tbody tr:first-child .star.on")
    assert page.text_content("#panel h3") == "Best Sim"  # the star doesn't select the row's game twice
    page.click('#table-view button[data-view="shortlist"]')
    page.wait_for_selector("#shortlist tbody tr")
    assert "Best Sim" in page.inner_text("#shortlist tbody tr") and page.is_visible("#shortlist-csv")
    page.fill("#shortlist input.note", "Better bus <b>physics</b>")
    page.press("#shortlist input.note", "Tab")
    page.wait_for_selector("text=Note saved")

    page.reload()
    page.wait_for_selector(".tag-chip")
    page.click('#table-view button[data-view="shortlist"]')
    page.wait_for_selector("#shortlist tbody tr")
    assert page.input_value("#shortlist input.note") == "Better bus <b>physics</b>"
    page.click("#shortlist tbody tr .remove")
    page.wait_for_function("!document.querySelector('#shortlist tbody tr')")
    assert "No games yet" in page.text_content("#shortlist-note") and page.is_hidden("#shortlist-csv")
    assert errors == []


def test_ui_quick_filter_and_tag_chips(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d'); localStorage.setItem('lang', 'en')")
    page.goto(base_url)
    page.wait_for_selector(".tag-chip")
    page.click("#run")
    page.wait_for_selector("#ranking tbody tr")
    assert page.locator("#ranking tbody tr").count() == 2 and page.text_content("#filter-count") == ""

    page.fill("#name-filter", "best")
    assert page.locator("#ranking tbody tr").count() == 1
    page.click('#games-mode button[data-mode="map"]')  # the map is drawn only while shown
    assert page.locator(".map2d .bubble").count() == 1
    page.click('#games-mode button[data-mode="table"]')
    assert page.text_content("#ranking tbody tr td.num") == "1"  # keeps its rank
    assert page.text_content("#filter-count") == "1 of 2 games shown"
    page.fill("#name-filter", "")
    # The Risks column shows the points, and the checkbox hides exactly those games.
    risks = page.eval_on_selector_all("#ranking tbody tr", "rs => rs.map(r => r.children[2].textContent + ':' + r.lastChild.textContent)")
    assert "Other:-20" in risks and "Best Sim:-" in risks
    page.check("#hide-risky")  # "Other" has a risk penalty in the fake result
    names = page.eval_on_selector_all("#ranking tbody tr", "rs => rs.map(r => r.children[2].textContent)")
    assert names == ["Best Sim"]
    page.uncheck("#hide-risky")

    # A tag chip in the panel searches that one tag.
    page.locator("#panel .chips button.chip").first.click()
    page.wait_for_selector("text=Only this tag")
    page.wait_for_function("document.querySelector('#table-title').textContent.includes('Crafting')")
    assert page.eval_on_selector_all(".tag-chip", "cs => cs.map(c => c.firstChild.textContent)") == ["Crafting"]
    assert errors == []


def test_ui_help_dialog(base_url, browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("localStorage.setItem('mapView', '2d'); localStorage.setItem('lang', 'en')")
    page.goto(base_url)
    page.wait_for_selector(".tag-chip")  # app.js is running
    page.click("#help-toggle")
    assert page.is_visible("#help") and page.locator("#help section").count() == 9
    assert "80%" in page.inner_text("#help")
    glossary = page.inner_text("#help-terms")
    assert "Fixability" in glossary and "Unmet share" in glossary and "Fading demand" in page.inner_text("#help-risks")
    page.keyboard.press("Escape")
    assert page.is_hidden("#help")

    # An info button explains its term on hover; clicking it doesn't sort the column.
    page.hover('#ranking th[data-key="gross"] .info')
    assert page.is_visible("#term-tip") and "Box Method" in page.inner_text("#term-tip")
    page.click('#ranking th[data-key="gross"] .info')
    assert "sorted" not in (page.get_attribute('#ranking th[data-key="gross"]', "class") or "")
    page.mouse.move(5, 5)
    assert page.is_hidden("#term-tip")

    # Dark | light: the switch sets the theme on <html> and remembers it across a reload.
    assert page.get_attribute("html", "data-theme") in ("dark", "light")
    page.click('#theme button[data-theme="light"]')
    assert page.get_attribute("html", "data-theme") == "light"
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.reload()
    page.wait_for_selector(".tag-chip")
    assert page.get_attribute("html", "data-theme") == "light"
    assert page.get_attribute('#theme button[data-theme="light"]', "aria-pressed") == "true"
    page.click('#theme button[data-theme="dark"]')
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != bg

    page.click('#lang button[data-lang="tr"]')
    page.click("#help-toggle")
    assert page.text_content("#help-title") == "Nasıl çalışır?" and "Skor" in page.inner_text("#help")
    assert "Karşılanmama oranı" in page.inner_text("#help-terms")
    page.click("#help .help-head button")
    assert page.is_hidden("#help")
    assert errors == []
