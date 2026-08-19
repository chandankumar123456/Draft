"""Tests for TUI config persistence (.draft/config.json)."""

import json
from pathlib import Path

import pytest

from tui.app import DraftApp
from tui.screens import ConfigModal

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

    from config import config_path
    data = json.loads(config_path().read_text(encoding="utf-8"))
    assert data["endpoint"] == "https://persisted.azure.com"


@pytest.mark.anyio
async def test_config_reset_clears_saved_config(tmp_path, monkeypatch) -> None:
    """/config-reset deletes the saved config file and reopens the modal."""
    import config as config_module
    from config import config_path, save_config

    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)
    save_config(endpoint="https://persisted.azure.com")
    assert config_path().exists()

    app = _TestDraftApp()
    async with app.run_test(size=(80, 24)):
        app._handle_slash_command("/config-reset")
        assert isinstance(app.screen, ConfigModal)

    assert not config_path().exists()
    assert "PROJECT_ENDPOINT" not in config_module.os.environ