import pytest

from market_researcher import config


@pytest.fixture(autouse=True)
def private_data_paths(tmp_path, monkeypatch):
    """No test ever reads or writes the user's real cache or saved runs (a long backtest may be using them)."""
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite")
    monkeypatch.setattr(config, "RUNS_DB", tmp_path / "runs.sqlite")
