"""Search area panel — search FitGirl, pick a file, or paste a magnet link."""
from __future__ import annotations

import math
from pathlib import Path

import bencodepy

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Static
from textual.binding import Binding

# ── Backend imports (project root is on sys.path via __main__) ───────────
import sys, os
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scrapers.scrape_fitgirl import (
    search as fitgirl_search,
    find_torrent_url,
    download_attachment_to_ram,
    SearchResult,
)
from parser import parse_file_info


# ───────────────────────────────────────────────────────────────────────────
# Messages bubbled up to the app
# ───────────────────────────────────────────────────────────────────────────

class TorrentSelected(Message):
    """Fired when the user double-clicks a search result and
    the .torrent bytes have been downloaded into RAM."""

    def __init__(self, torrent_data: dict, title: str) -> None:
        super().__init__()
        self.torrent_data = torrent_data   # decoded bencode dict
        self.title = title


# ───────────────────────────────────────────────────────────────────────────
# Single search-result row
# ───────────────────────────────────────────────────────────────────────────

class ResultRow(Static):
    """One row in the results list.  Alternates dark/light background."""

    class DoubleClicked(Message):
        def __init__(self, result: SearchResult) -> None:
            super().__init__()
            self.result = result

    def __init__(self, result: SearchResult, index: int) -> None:
        self.result = result
        self._index = index
        super().__init__(result.title)

    def on_mount(self) -> None:
        if self._index % 2 == 0:
            # Dark row
            self.styles.background = "#1E2714"
            self.styles.color = "#A0A880"
        else:
            # Light row
            self.styles.background = "#A0A880"
            self.styles.color = "#1E2714"
        self.styles.padding = (0, 1)
        self.styles.width = "100%"
        self.styles.height = 3

    def on_click(self, event) -> None:
        """Detect double-click via Textual's built-in event."""
        # Textual doesn't expose double-click natively on Static, so
        # we track it ourselves with a small timer.
        import time
        now = time.monotonic()
        last = getattr(self, "_last_click", 0.0)
        if now - last < 0.4:
            self.post_message(self.DoubleClicked(self.result))
            self._last_click = 0.0
        else:
            self._last_click = now


# ───────────────────────────────────────────────────────────────────────────
# Main widget
# ───────────────────────────────────────────────────────────────────────────

class SearchWidget(Static):
    """Hosts the three input modes and the results list."""

    DEFAULT_CSS = """
    SearchWidget {
        width: 100%;
        height: 100%;
    }

    #search-tabs {
        height: 3;
        width: 100%;
        dock: top;
    }

    #search-tabs Button {
        min-width: 20;
        height: 3;
        margin: 0 1 0 0;
        text-style: none;
    }

    #search-tabs .tab-active {
        background: #4A5A30;
        color: #FFFFFF;
        border: tall #C8D6A0;
    }

    #search-tabs .tab-inactive {
        background: #2E3A1F;
        color: #A0A880;
        border: tall #3A4A28;
    }

    #input-area {
        height: 3;
        width: 100%;
        padding: 0 0;
    }

    #input-area Input {
        width: 1fr;
        height: 3;
        background: #1E2714;
        color: #E0E8D0;
        border: tall #4A5A30;
    }

    #results-area {
        height: 1fr;
        width: 100%;
        padding: 0;
    }

    #status-bar {
        height: 1;
        width: 100%;
        dock: bottom;
        color: #A0A880;
        text-align: center;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "clear_results", "Clear", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_tab = "search"  # "search" | "file" | "magnet"

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-tabs"):
            yield Button("🔍 Search", id="tab-search", classes="tab-active")
            yield Button("📁 Open File", id="tab-file", classes="tab-inactive")
            yield Button("🧲 Magnet Link", id="tab-magnet", classes="tab-inactive")

        with Horizontal(id="input-area"):
            yield Input(
                placeholder="Search for a video game or a movie ...",
                id="search-input",
            )

        with VerticalScroll(id="results-area"):
            pass   # results injected dynamically

        yield Static("", id="status-bar")

    # ── Tab switching ─────────────────────────────────────────────────────

    def _set_tab(self, tab: str) -> None:
        self._current_tab = tab
        tab_ids = {"search": "tab-search", "file": "tab-file", "magnet": "tab-magnet"}
        for key, btn_id in tab_ids.items():
            btn = self.query_one(f"#{btn_id}", Button)
            if key == tab:
                btn.remove_class("tab-inactive")
                btn.add_class("tab-active")
            else:
                btn.remove_class("tab-active")
                btn.add_class("tab-inactive")

        inp = self.query_one("#search-input", Input)
        placeholders = {
            "search": "Search for a video game or a movie ...",
            "file": "Browse is not wired yet — coming soon!",
            "magnet": "Paste magnet link here ...",
        }
        inp.value = ""
        inp.placeholder = placeholders[tab]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "tab-search": "search",
            "tab-file": "file",
            "tab-magnet": "magnet",
        }
        tab = mapping.get(event.button.id)
        if tab:
            self._set_tab(tab)

    # ── Input submitted ───────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._current_tab == "search":
            query = event.value.strip()
            if query:
                self._run_search(query)

    # ── Search (runs in a worker thread) ──────────────────────────────────

    @work(thread=True, exclusive=True, group="search")
    def _run_search(self, query: str) -> None:
        status = self.query_one("#status-bar", Static)
        self.app.call_from_thread(status.update, f"Searching FitGirl for \"{query}\" ...")

        # Clear old results
        results_area = self.query_one("#results-area", VerticalScroll)
        self.app.call_from_thread(results_area.remove_children)

        try:
            results = fitgirl_search(query, timeout=20)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"Search error: {exc}")
            return

        if not results:
            self.app.call_from_thread(status.update, "No results found.")
            return

        def _mount_rows():
            for i, r in enumerate(results):
                row = ResultRow(r, i)
                results_area.mount(row)

        self.app.call_from_thread(_mount_rows)
        self.app.call_from_thread(
            status.update,
            f"Found {len(results)} result(s). Double-click to load torrent info.",
        )

    # ── Double-click handler → download .torrent into RAM ─────────────────

    def on_result_row_double_clicked(self, event: ResultRow.DoubleClicked) -> None:
        self._download_torrent(event.result)

    @work(thread=True, exclusive=True, group="torrent-dl")
    def _download_torrent(self, result: SearchResult) -> None:
        status = self.query_one("#status-bar", Static)
        self.app.call_from_thread(
            status.update, f"Fetching torrent link for \"{result.title}\" ..."
        )

        try:
            torrent_url = find_torrent_url(result, timeout=20)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"Error finding torrent link: {exc}")
            return

        self.app.call_from_thread(
            status.update, f"Downloading .torrent file into RAM (via browser) ..."
        )

        try:
            raw_bytes = download_attachment_to_ram(torrent_url, timeout=45)
            torrent_data = bencodepy.decode(raw_bytes)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"Download error: {exc}")
            return

        self.app.call_from_thread(
            status.update, f"Torrent loaded! Showing stats for \"{result.title}\"."
        )

        # Bubble up to the app so it can populate the stats panel
        self.app.call_from_thread(
            self.post_message, TorrentSelected(torrent_data, result.title)
        )

    # ── Escape to clear ──────────────────────────────────────────────────

    def action_clear_results(self) -> None:
        results_area = self.query_one("#results-area", VerticalScroll)
        results_area.remove_children()
        self.query_one("#status-bar", Static).update("")
