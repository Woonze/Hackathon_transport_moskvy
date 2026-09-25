import pytest

from backend.app import config


@pytest.fixture(autouse=True)
def isolated_overlay(tmp_path, monkeypatch):
    """Тесты не должны писать в реальный artifacts/ingested.csv."""
    monkeypatch.setattr(config, "OVERLAY", tmp_path / "ingested.csv")
