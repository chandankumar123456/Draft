"""Tests for drag-to-select text copy in the TUI logs.

The Draft TUI renders all log content with ``SelectableRichLog``, a
``RichLog`` subclass that implements Textual's widget selection
protocol. These tests verify that:

* selecting a range of a log line extracts the expected text,
* the selection is visually highlighted when rendered,
* releasing the drag (``TextSelected``) copies the text to the
  clipboard.
"""

import pytest
from pathlib import Path
from textual.events import TextSelected
from textual.geometry import Offset
from textual.selection import Selection

from tui.app import DraftApp
from tui.widgets import SelectableRichLog

_TUI_STYLES = (
    Path(__file__).resolve().parent.parent / "tui" / "styles.tcss"
)


class _TestDraftApp(DraftApp):
    """DraftApp without agent runtime initialization."""

    CSS_PATH = _TUI_STYLES

    def _init_agent(self) -> None:
        pass


@pytest.fixture
def app():
    return _TestDraftApp()


async def _fill_log(
    app: DraftApp, pilot, text: str
) -> SelectableRichLog:
    log = app.query_one("#workspace-log", SelectableRichLog)
    log.clear()
    log.write(text)
    await pilot.pause()
    return log


@pytest.mark.anyio
async def test_partial_selection_extracts_text(app: DraftApp) -> None:
    """Selecting a range on a line returns exactly that text."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = await _fill_log(app, pilot, "line one\nhello world")

        app.screen.selections = {
            log: Selection.from_offsets(Offset(0, 1), Offset(5, 1))
        }
        await pilot.pause()

        assert app.screen.get_selected_text() == "hello"


@pytest.mark.anyio
async def test_multi_line_selection_extracts_text(app: DraftApp) -> None:
    """Selecting across lines returns both lines joined by a newline."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = await _fill_log(app, pilot, "alpha\nbeta\ngamma")

        app.screen.selections = {
            log: Selection.from_offsets(Offset(0, 0), Offset(2, 2))
        }
        await pilot.pause()

        assert app.screen.get_selected_text() == "alpha\nbeta\nga"


@pytest.mark.anyio
async def test_markup_is_stripped_from_selection(app: DraftApp) -> None:
    """Rich markup tags are not part of the extracted text."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = await _fill_log(
            app, pilot, "[bold cyan]AGENT[/bold cyan]\nplain text"
        )

        app.screen.selections = {
            log: Selection.from_offsets(Offset(0, 0), Offset(5, 0))
        }
        await pilot.pause()

        assert app.screen.get_selected_text() == "AGENT"


@pytest.mark.anyio
async def test_selection_is_highlighted_in_render(app: DraftApp) -> None:
    """Rendered lines show a distinct style for the selected span."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = await _fill_log(app, pilot, "line one\nhello world")

        app.screen.selections = {
            log: Selection.from_offsets(Offset(0, 1), Offset(5, 1))
        }
        await pilot.pause()

        strip = log.render_line(1)
        styles = [
            segment.style
            for segment in strip
            for _ in segment.text
        ]
        # Selected cells (0-4) must differ from unselected cells (6+)
        assert styles[0] != styles[6]
        assert styles[0] == styles[4]

        # After clearing, all cells share the same style again
        app.screen.clear_selection()
        await pilot.pause()
        strip = log.render_line(1)
        styles = [
            segment.style
            for segment in strip
            for _ in segment.text
        ]
        assert styles[0] == styles[6]


@pytest.mark.anyio
async def test_release_copies_selection_to_clipboard(app: DraftApp) -> None:
    """TextSelected (mouse release after a drag) copies to the clipboard."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = await _fill_log(app, pilot, "line one\nhello world")

        app.screen.selections = {
            log: Selection.from_offsets(Offset(0, 1), Offset(5, 1))
        }
        await pilot.pause()

        app.post_message(TextSelected())
        await pilot.pause()

        assert app._clipboard == "hello"


@pytest.mark.anyio
async def test_copy_action_copies_selection(app: DraftApp) -> None:
    """The copy action writes the selection to the clipboard."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = await _fill_log(app, pilot, "line one\nhello world")

        app.screen.selections = {
            log: Selection.from_offsets(Offset(0, 0), Offset(4, 0))
        }
        await pilot.pause()

        app.action_copy_text()
        await pilot.pause()

        assert app._clipboard == "line"