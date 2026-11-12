"""Current-downloads panel - placeholder for download items."""
from textual.widgets import Static


class DownloadsWidget(Static):
    """Displays active torrent downloads."""

    DEFAULT_CSS = """
    DownloadsWidget {
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: #A0A880;
        text-style: none;
    }
    """

    def __init__(self) -> None:
        super().__init__("No active downloads")
