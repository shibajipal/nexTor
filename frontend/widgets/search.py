"""Search area panel - placeholder for torrent searching / magnet input."""
from textual.widgets import Static


class SearchWidget(Static):
    """Hosts torrent search and magnet link input."""

    DEFAULT_CSS = """
    SearchWidget {
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: #A0A880;
        text-style: none;
    }
    """

    def __init__(self) -> None:
        super().__init__("Search / paste magnet link ...")
