"""Shared log primitives for the Draft Developer Cockpit.

Houses ``SelectableRichLog``, the drag-to-select ``RichLog`` subclass
used by every log surface in the cockpit.

The subclass fixes two RichLog behaviors that break drag-to-select and
reading during active agent execution:

* ``auto_scroll=True`` scrolls to the bottom on *every* write, yanking
  the view away from older output the user is reading and moving
  content under the cursor mid-drag. We keep RichLog's native
  auto-scroll off and implement *follow* behavior instead: writes only
  scroll to the newest content when the user is already at/near the
  bottom, or when following was explicitly enabled via ``set_follow``.
* ``get_selection`` joined the *stored* strips, which are wrapped at
  write-time width (``min_width``, default 78). When the log is
  narrower than that, every stored line holds characters the user never
  sees and the extracted text does not match the visible span. We now
  crop the stored lines to the same window the compositor renders, so
  extracted text matches exactly what is on screen.
"""

from __future__ import annotations

from textual.geometry import Offset
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import RichLog


# ════════════════════════════════════════════════════════════════
# SELECTABLE RICH LOG
# ════════════════════════════════════════════════════════════════

class SelectableRichLog(RichLog):
    """A RichLog that supports drag-to-select text.

    Textual's ``RichLog`` does not implement the widget selection
    protocol (``get_selection`` / ``selection_updated``), so dragging
    the mouse over log content produces no selection and nothing can
    be copied. This subclass adds:

    * ``get_selection`` — extract the selected text from the log lines
      so ``Screen.get_selected_text()`` works. Extraction operates on
      the same cropped representation the compositor renders, so the
      copied text always matches the visible span, even for wrapped
      content written at a different width.
    * ``selection_updated`` — repaint when the selection changes.
    * Content offset metadata and selection styling in ``_render_line``
      so precise ranges are highlighted while dragging.
    * Follow-based auto scrolling (``set_follow``) that never yanks the
      user away from older output they are reading.

    The app copies the selection to the clipboard on mouse release via
    its ``on_text_selected`` handler.
    """

    ALLOW_SELECT = True

    DEFAULT_CSS = """
    SelectableRichLog {
        overflow-x: hidden;
        overflow-y: scroll;
    }
    """

    def __init__(
        self,
        *,
        auto_scroll: bool = True,
        min_width: int = 0,
        **kwargs,
    ) -> None:
        """Create a SelectableRichLog.

        ``auto_scroll`` is accepted for RichLog compatibility but is
        *not* passed through: RichLog's native scroll-to-end-on-every-
        write is replaced by the follow behavior in ``write``. The
        ``min_width`` default is lowered to 0 so wrapped content is
        wrapped at the log's actual width and is never clipped or
        horizontally scrollable.
        """
        super().__init__(auto_scroll=False, min_width=min_width, **kwargs)
        self._follow = auto_scroll
        """Whether writes may scroll the log (master switch)."""
        self._explicit_follow = False
        """Follow was explicitly requested via ``set_follow(True)``;
        writes scroll even when the user is scrolled away."""

    # ── Follow / smart auto-scroll ───────────────────────────────

    def set_follow(self, enabled: bool) -> None:
        """Enable or disable follow-to-newest behavior.

        When enabled explicitly, writes scroll to the newest content
        even if the user is scrolled away (until the user scrolls).
        When enabled implicitly (the default), writes only scroll when
        the user is at/near the bottom.
        """
        self._follow = enabled
        self._explicit_follow = enabled

    def _at_bottom(self) -> bool:
        """Is the user at (or within one line of) the newest content?"""
        return (
            self.max_scroll_y <= 0
            or self.scroll_offset.y >= self.max_scroll_y - 1
        )

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Drop explicit follow once the user scrolls away from the
        bottom; following resumes automatically when they return."""
        super().watch_scroll_y(old_value, new_value)
        if self._explicit_follow and round(new_value) < round(self.max_scroll_y):
            self._explicit_follow = False

    def scroll_to(
        self,
        x: float | None = None,
        y: float | None = None,
        *,
        animate: bool = True,
        **kwargs,
    ) -> None:
        """Scroll to a coordinate.

        Log surfaces never animate scrolling: writes stream in during
        active agent execution and drag-selection relies on a stable
        viewport, so all scrolls (wheel, scrollbar, programmatic) land
        immediately. The ``animate`` argument is accepted for API
        compatibility but ignored.
        """
        super().scroll_to(x, y, animate=False, **kwargs)

    def write(
        self,
        content,
        width: int | None = None,
        expand: bool = True,
        shrink: bool = True,
        scroll_end: bool | None = None,
        animate: bool = False,
    ):
        """Write content, following the newest output only when the
        user is at the bottom (or explicitly following).

        RichLog's native auto_scroll is disabled, so this override is
        the only thing that ever scrolls the log on write. The scroll
        is synchronous (``immediate=True``) so a write never leaves a
        deferred scroll behind that could yank the view later.
        """
        follow = (
            self._follow
            and (self._explicit_follow or self._at_bottom())
            and not self.is_vertical_scrollbar_grabbed
        )
        super().write(content, width, expand, shrink, scroll_end, animate)
        if follow:
            self.scroll_end(animate=False, immediate=True, x_axis=False)
        return self

    # ── Selection ────────────────────────────────────────────────

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Get the text under the given selection.

        The extraction text is built from the same cropped window the
        compositor renders (``crop_extend`` at the scroll offset and
        content width), so line breaks and characters always match the
        visible span — even when stored lines were wrapped at a wider
        write-time width. The selection x offsets are translated into
        window coordinates to match.

        Args:
            selection: Selection information.

        Returns:
            Tuple of extracted text and line ending, or ``None`` if no
            text could be extracted.
        """
        scroll_x = self.scroll_offset.x
        width = self.scrollable_content_region.width
        lines = [
            self.lines[y]
            .crop_extend(scroll_x, scroll_x + width, self.rich_style)
            .text.rstrip()
            for y in range(len(self.lines))
        ]
        text = "\n".join(lines)

        start, end = selection
        if start is not None:
            start = Offset(max(0, start.x - scroll_x), start.y)
        if end is not None:
            end = Offset(max(0, end.x - scroll_x), end.y)
        return Selection(start, end).extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        """Repaint the log when the selection changes."""
        self._line_cache.clear()
        self.refresh()

    def render_line(self, y: int) -> Strip:
        """Render a line of content.

        Args:
            y: Y coordinate of the line.

        Returns:
            A rendered line with the selection highlight applied.
        """
        scroll_x, scroll_y = self.scroll_offset
        return self._render_line(
            scroll_y + y,
            scroll_x,
            self.scrollable_content_region.width,
        )

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        """Render a line with selection highlighting and offset metadata.

        Args:
            y: Y offset of the line (content coordinates).
            scroll_x: Current horizontal scroll.
            width: Width of the widget.

        Returns:
            A Strip suitable for rendering.
        """
        if y >= len(self.lines):
            return Strip.blank(width, self.rich_style)

        key = (y + self._start_line, scroll_x, width, self._widest_line_width)
        selection = self.text_selection
        if selection is None and key in self._line_cache:
            return self._line_cache[key]

        line = self.lines[y].crop_extend(
            scroll_x, scroll_x + width, self.rich_style
        )
        line = line.apply_style(self.rich_style)

        if selection is not None:
            span = selection.get_span(y)
            if span is not None:
                span_start, span_end = span
                if span_end == -1:
                    span_end = scroll_x + width
                start = max(span_start - scroll_x, 0)
                end = min(span_end - scroll_x, width)
                if end > start:
                    selection_style = self.screen.get_component_rich_style(
                        "screen--selection"
                    )
                    before = line.crop_extend(0, start, self.rich_style)
                    selected = line.crop_extend(start, end, self.rich_style)
                    selected = selected.apply_style(selection_style)
                    after = line.crop_extend(end, width, self.rich_style)
                    line = before + selected + after

        # Offset metadata lets the compositor report precise content
        # offsets when the mouse is pressed, enabling exact selections.
        line = line.apply_offsets(scroll_x, y)
        self._line_cache[key] = line
        return line