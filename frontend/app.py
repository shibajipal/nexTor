"""
nexTor TUI - Main Application
Run:  python -m frontend.app   (from the nexTor project root)
  or: python frontend/app.py
"""
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical

from .widgets.logo import LogoWidget
from .widgets.downloads import DownloadsWidget
from .widgets.stats import StatsWidget
from .widgets.search import SearchWidget, TorrentSelected


CSS_PATH = Path(__file__).parent / "layout.tcss"


class NexTorApp(App):
    """The nexTor terminal-UI shell."""

    CSS_PATH = CSS_PATH
    TITLE = "nexTor"
    SUB_TITLE = "BitTorrent Client"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            # Left column: top row (logo + downloads), then search area 
            with Vertical(id="left-column"):
                with Horizontal(id="top-row"):
                    # Logo box (ASCII art)
                    with Vertical(id="logo-box", classes="panel"):
                        yield LogoWidget()

                    # Current downloads box (heading on top-right border)
                    with Vertical(id="downloads-box", classes="panel") as d_box:
                        d_box.border_title = " current downloads "
                        yield DownloadsWidget()

                # Search area box (heading on top-right border)
                with Vertical(id="search-box", classes="panel") as s_box:
                    s_box.border_title = " search area "
                    yield SearchWidget()

            # Right column: stats box (heading on top-right border) 
            with Vertical(id="stats-box", classes="panel") as st_box:
                st_box.border_title = " stats "
                yield StatsWidget()

    # ── Wire search → stats ───────────────────────────────────────────────

    def on_torrent_selected(self, event: TorrentSelected) -> None:
        """When a .torrent is downloaded into RAM, populate the stats panel."""
        stats = self.query_one(StatsWidget)
        stats.show_torrent_info(event.torrent_data, event.title)


# Allow running directly: python frontend/app.py
if __name__ == "__main__":
    app = NexTorApp()
    app.run()
