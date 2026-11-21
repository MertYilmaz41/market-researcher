import pytest

from market_researcher import config, pipeline, regional
from market_researcher.models import RegionalPrice
from market_researcher.sources import exchange, steam_store


def price(cc, currency, cents, final=None, discount=0):
    return RegionalPrice(country=cc, currency=currency, initial_cents=cents,
                         final_cents=cents if final is None else final, discount_percent=discount, text=f"{cents}")


def test_parse_price():
    data = {"413150": {"success": True, "data": {"price_overview": {
        "currency": "JPY", "initial": 148000, "final": 148000, "discount_percent": 0,
        "initial_formatted": "", "final_formatted": "¥ 1,480"}}}}
    p = steam_store.parse_price(413150, "jp", data)
    assert (p.country, p.currency, p.initial_cents, p.text) == ("jp", "JPY", 148000, "¥ 1,480")


def test_parse_price_shows_the_undiscounted_price():
    data = {"5": {"success": True, "data": {"price_overview": {
        "currency": "BRL", "initial": 10799, "final": 3239, "discount_percent": 70,
        "initial_formatted": "R$ 107,99", "final_formatted": "R$ 32,39"}}}}
    p = steam_store.parse_price(5, "br", data)
    assert p.text == "R$ 107,99" and p.final_cents == 3239 and p.discount_percent == 70


@pytest.mark.parametrize("data", [
    {"5": {"success": False}},  # unknown or region-locked
    {"5": {"success": True, "data": []}},  # free: Steam sends an empty list
    {"5": {"success": True, "data": {}}},
    {},
])
def test_parse_price_not_sold(data):
    assert steam_store.parse_price(5, "us", data) is None


def test_parse_rates():
    rates, date = exchange.parse_rates({"result": "success", "time_last_update_utc": "Fri, 20 Nov 2026 00:02:32 +0000",
                                        "rates": {"USD": 1, "JPY": 160}})
    assert rates == {"USD": 1.0, "JPY": 160.0} and date.startswith("Fri, 20 Nov")
    with pytest.raises(RuntimeError):
        exchange.parse_rates({"result": "error", "error-type": "unsupported-code"})


def test_compare_sorts_by_dollars_and_compares_with_us():
    rows = regional.compare(
        {"us": price("us", "USD", 2000), "jp": price("jp", "JPY", 160000, discount=50, final=80000),
         "xx": price("xx", "XXX", 500), "kp": None},
        {"USD": 1, "JPY": 160})
    assert [r.country for r in rows] == ["jp", "us", "xx", "kp"]  # no rate, then not sold, last
    jp = rows[0]
    assert jp.usd == pytest.approx(10.0)  # the undiscounted price, not the sale one
    assert jp.vs_us == pytest.approx(-0.5)
    assert rows[1].vs_us == 0 and rows[2].usd is None and rows[2].vs_us is None


def test_compare_without_us_price():
    rows = regional.compare({"us": None, "jp": price("jp", "JPY", 160000)}, {"JPY": 160})
    assert rows[0].usd == pytest.approx(10.0) and rows[0].vs_us is None


def test_regional_prices_keep_local_prices_without_rates(monkeypatch):
    monkeypatch.setattr(config, "PRICE_COUNTRIES", ["us", "jp"])
    monkeypatch.setattr(steam_store, "regional_price", lambda http, appid, cc: price(cc, "USD" if cc == "us" else "JPY", 1000))

    def down(http):
        raise RuntimeError("open.er-api.com did not return JSON rates: x")

    monkeypatch.setattr(exchange, "usd_rates", down)
    r = pipeline.regional_prices(None, 1)
    assert len(r.rows) == 2 and all(row.usd is None for row in r.rows)
    assert [n.title for n in r.notices] == ["Prices shown without dollar figures"]


def test_regional_prices_for_a_free_game(monkeypatch):
    monkeypatch.setattr(config, "PRICE_COUNTRIES", ["us", "jp"])
    monkeypatch.setattr(steam_store, "regional_price", lambda http, appid, cc: None)
    r = pipeline.regional_prices(None, 1)
    assert r.rows == [] and r.notices[0].title == "No regional prices"


# ---------- mr report --prices ----------

def fake_prices(appid=1):
    return pipeline.RegionalPrices(
        rows=regional.compare({"us": price("us", "USD", 2000), "jp": price("jp", "JPY", 160000, final=80000, discount=50),
                               "kp": None}, {"USD": 1, "JPY": 160}),
        rates_date="Fri, 20 Nov 2026 00:02:32 +0000")


def test_report_lists_regional_prices():
    from market_researcher.i18n import use
    from market_researcher.report import render
    from test_web import fake_result

    r = fake_result()
    args = dict(tag="Job Simulator", analyses=r.analyses, n_candidates=3, n_tag_games=50, min_reviews=100,
                lo=5, hi=70, not_games=[], unlisted=[], prices={1: fake_prices()})
    text = render(**args)
    assert "### Regional prices" in text and text.count("### Regional prices") == 1  # only the game that has them
    assert "| Japan | 160000 (50% off now) | $10.00 | -50% |" in text
    assert "| United States | 2000 | $20.00 |  |" in text and "| kp |" not in text and "| Not sold | - | - |" in text
    assert text.index("| Japan") < text.index("| United States")
    assert "[Exchange Rate API](https://www.exchangerate-api.com), 2026-11-20." in text
    assert "Regional prices" not in render(**{**args, "prices": None})
    with use("tr"):
        tr = render(**args)
    assert "### Bölgesel fiyatlar" in tr and "| Japonya | 160000 (şu an %50 indirimli) | $10,00 | -%50 |" in tr


def test_report_cli_prices_flag(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from market_researcher import cli
    from test_web import fake_result

    monkeypatch.setattr(cli, "run_tag", lambda *a: fake_result())
    asked = []

    def prices(http, appid):
        asked.append(appid)
        if appid == 2:
            raise RuntimeError("Steam redirected https://store.steampowered.com/api/appdetails")
        return fake_prices()

    monkeypatch.setattr(cli, "regional_prices", prices)
    out = tmp_path / "r.md"
    res = CliRunner().invoke(cli.app, ["report", "-t", "Job Simulator", "-o", str(out)])
    assert res.exit_code == 0 and asked == [] and "Regional prices" not in out.read_text(encoding="utf-8")
    res = CliRunner().invoke(cli.app, ["report", "-t", "Job Simulator", "-o", str(out), "--prices"])
    assert res.exit_code == 0, res.output
    assert sorted(asked) == [1, 2]  # ranked games only, not the DLC
    assert "Couldn't load the regional prices of Other" in res.output  # one failure doesn't lose the report
    assert out.read_text(encoding="utf-8").count("### Regional prices") == 1
