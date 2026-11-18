"""Stats panel — shows torrent metadata after a .torrent is loaded into RAM."""
from __future__ import annotations

import math
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Static

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parser import parse_file_info


def _fmt_size(n: int) -> str:
    """Human-readable byte size."""
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.2f} GB"
    elif n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    elif n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


class StatsWidget(Static):
    """Displays torrent metadata: name, size, pieces, etc."""

    DEFAULT_CSS = """
    StatsWidget {
        width: 100%;
        height: 100%;
    }

    #stats-placeholder {
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: #A0A880;
    }

    #stats-scroll {
        width: 100%;
        height: 1fr;
    }

    #download-btn {
        margin-top: 1;
        width: 100%;
        height: 3;
        background: #4A5A30;
        color: #FFFFFF;
        text-style: none;
        border: tall #C8D6A0;
        content-align: center middle;
        text-align: center;
        dock: bottom;
    }

    #download-btn:hover {
        background: #5A6A40;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._torrent_data: dict | None = None

    def compose(self) -> ComposeResult:
        yield Static("No stats yet", id="stats-placeholder")

    def show_torrent_info(self, torrent_data: dict, title: str) -> None:
        """Populate the panel with parsed torrent metadata."""
        self._torrent_data = torrent_data
        info = torrent_data.get(b"info", {})

        # ── Extract fields ────────────────────────────────────────────
        name = info.get(b"name", b"Unknown").decode("utf-8", "replace")

        # Created-by (torrent-level, not always present)
        raw_created = torrent_data.get(b"created by", b"")
        if isinstance(raw_created, bytes):
            created_by = raw_created.decode("utf-8", "replace") or "N/A"
        else:
            created_by = str(raw_created) or "N/A"

        # Piece info
        piece_length = info.get(b"piece length", 0)
        pieces_blob = info.get(b"pieces", b"")
        piece_count = len(pieces_blob) // 20 if pieces_blob else 0

        # Total size
        files, total_length = parse_file_info(info)
        file_count = len(files)

        # ── Build the display text ────────────────────────────────────
        lines = []
        rows = [
            ("TORRENT NAME", name),
            ("CREATED BY", created_by),
            ("FILE COUNT", str(file_count)),
            ("TOTAL SIZE", _fmt_size(total_length)),
            ("PIECES", f"{piece_count:,}"),
            ("PIECE LENGTH", _fmt_size(piece_length)),
        ]
        for label, value in rows:
            lines.append(f"[#A0A880]  {label}[/]")
            lines.append(f"[#FFFFFF]    {value}[/]")
            lines.append("")  # spacer line

        markup = "\n".join(lines)

        # ── Swap UI ───────────────────────────────────────────────────
        # Remove placeholder
        try:
            self.query_one("#stats-placeholder").remove()
        except Exception:
            pass
        # Remove old scroll / button if re-loading
        for sel in ("#stats-scroll", "#download-btn"):
            try:
                self.query_one(sel).remove()
            except Exception:
                pass

        info_static = Static(markup, id="stats-scroll")
        info_static.styles.width = "100%"
        info_static.styles.height = "auto"
        info_static.styles.padding = (1, 0)

        self.mount(info_static)
        self.mount(Button("⬇  Download Now", id="download-btn"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "download-btn":
            # Placeholder — download functionality will be added later
            event.button.label = "⏳  Coming soon ..."
