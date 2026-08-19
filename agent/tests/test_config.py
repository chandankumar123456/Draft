"""Tests for persistent configuration (endpoint + model)."""

import pytest

from config import (
    Config,
    clear_config,
    config_path,
    load_config,
    save_config,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect the config file to tmp_path and reset module state."""
    monkeypatch.setattr("config._project_root", lambda: tmp_path)
    monkeypatch.setattr("config._LOADED", False)
    monkeypatch.setattr("config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("MODEL_DEPLOYMENT", raising=False)
    yield


def test_load_config_defaults():
    cfg = load_config()
    assert isinstance(cfg, Config)
    assert cfg.endpoint == ""
    assert cfg.model == "gpt-4.1-mini"


def test_save_and_load_round_trip():
    save_config(endpoint="https://draft.services.ai.azure.com/api/projects/Draft", model="gpt-4.1-mini")
    assert config_path().exists()
    assert config_path().name == "config.json"
    cfg = load_config()
    assert cfg.endpoint == "https://draft.services.ai.azure.com/api/projects/Draft"
    assert cfg.model == "gpt-4.1-mini"


def test_file_overrides_env(monkeypatch):
    save_config(endpoint="https://from-file.azure.com")
    monkeypatch.setenv("PROJECT_ENDPOINT", "https://from-env.azure.com")
    cfg = load_config()
    assert cfg.endpoint == "https://from-file.azure.com"


def test_env_used_when_file_missing(monkeypatch):
    monkeypatch.setenv("PROJECT_ENDPOINT", "https://from-env.azure.com")
    monkeypatch.setenv("MODEL_DEPLOYMENT", "gpt-4o")
    cfg = load_config()
    assert cfg.endpoint == "https://from-env.azure.com"
    assert cfg.model == "gpt-4o"


def test_clear_config_removes_file():
    save_config(endpoint="https://x.azure.com")
    clear_config()
    assert not config_path().exists()
    assert load_config().endpoint == ""


def test_save_config_sets_environment():
    save_config(endpoint="https://y.azure.com", model="gpt-4.1")
    import os
    assert os.environ["PROJECT_ENDPOINT"] == "https://y.azure.com"
    assert os.environ["MODEL_DEPLOYMENT"] == "gpt-4.1"


def test_first_run_prompt_skipped_when_configured(monkeypatch):
    save_config(endpoint="https://configured.azure.com")
    monkeypatch.setattr("builtins.input", lambda prompt="": "should-not-be-called")
    from agent import _first_run_prompt  # noqa: PLC0415
    assert _first_run_prompt() is None


def test_first_run_prompt_asks_and_returns_values(monkeypatch):
    clear_config()
    answers = iter(["https://typed.azure.com", "gpt-4.1-mini"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    from agent import _first_run_prompt  # noqa: PLC0415
    endpoint, model = _first_run_prompt()
    assert endpoint == "https://typed.azure.com"
    assert model == "gpt-4.1-mini"


def test_first_run_prompt_empty_endpoint_returns_none(monkeypatch):
    clear_config()
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    from agent import _first_run_prompt  # noqa: PLC0415
    assert _first_run_prompt() is None
