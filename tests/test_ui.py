from pathlib import Path

from streamlit.testing.v1 import AppTest

from steam_researcher import pipeline
from steam_researcher.models import HistPoint
from steam_researcher.pipeline import TagResult

from test_m4 import analysis

UI = str(Path(__file__).parents[1] / "src" / "steam_researcher" / "ui.py")


def test_ui_tag_flow_offline(monkeypatch):
    a1 = analysis(60, "Best Sim", appid=1)
    a1.histogram = [HistPoint(date=1_700_000_000, up=10, down=5)]
    fake = TagResult(n_tag_games=50, candidates=[a1.game], analyses=[a1, analysis(20, "Other", appid=2)])
    monkeypatch.setattr(pipeline, "run_tag", lambda *args, **kw: fake)

    at = AppTest.from_file(UI, default_timeout=60).run()
    assert not at.exception
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert [h.value for h in at.subheader] == ["Job Simulator: opportunity ranking", "Best Sim"]
    assert list(at.dataframe[0].value["Game"]) == ["Best Sim", "Other"]
    assert at.metric[0].value == "60/100"


def test_ui_unknown_tag(monkeypatch):
    monkeypatch.setattr(pipeline, "run_tag", lambda *args, **kw: None)
    at = AppTest.from_file(UI, default_timeout=60).run()
    at.sidebar.button[0].click().run()
    assert "No games found" in at.error[0].value
