"""Tests for TUI config persistence (.draft/config.json)."""

import pytest
from pathlib import Path

from tui.app import DraftApp

_TUI_STYLES = (
    Path(__file__).resolve().parent.parent / "tui" / "styles.tcss"
)


class _TestDraftApp(DraftApp):
    """DraftApp without agent runtime initialization."""

    CSS_PATH = _TUI_STYLES

    def _init_agent(self) -> None:
        pass


@pytest.mark.anyio
async def test_update_endpoint_persists_to_config(tmp_path, monkeypatch) -> None:
    """/endpoint must persist even when the runtime is not yet created."""
    import config as config_module
    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)

    app = _TestDraftApp()
    async with app.run_test(size=(80, 24)):
        app._update_endpoint("https://persisted.azure.com")

    from config import load_config
    assert load_config().endpoint == "https://persisted.azure.com"


@pytest.mark.anyio
async def test_config_reset_clears_saved_config(tmp_path, monkeypatch) -> None:
    """/config-reset deletes the saved config file."""
    import config as config_module
    from config import clear_config, config_path, save_config

    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)
    save_config(endpoint="https://persisted.azure.com")
    assert config_path().exists()

    clear_config()
    assert not config_path().exists()
