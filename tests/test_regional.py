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
