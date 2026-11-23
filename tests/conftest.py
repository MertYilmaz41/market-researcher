import pytest

from market_researcher import config


@pytest.fixture(autouse=True)
def private_data_paths(tmp_path, monkeypatch):
    """No test ever reads or writes the user's real cache or saved runs (a long backtest may be using them)."""
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite")
    monkeypatch.setattr(config, "RUNS_DB", tmp_path / "runs.sqlite")


@pytest.fixture(autouse=True)
def no_peer_read(monkeypatch):
    """No test reads every rated Steam game (~36 min): the score's similar-games read fails at once unless a
    test fakes pipeline.read_peers."""
    from market_researcher import pipeline

    def offline(*a, **kw):
        raise RuntimeError("tests don't read every Steam game")

    monkeypatch.setattr(pipeline, "read_peers", offline)
