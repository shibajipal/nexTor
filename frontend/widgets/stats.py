"""Stats panel - placeholder for transfer metrics and peer stats."""
from textual.widgets import Static


class StatsWidget(Static):
    """Displays peer stats, speeds, and ratios."""

    DEFAULT_CSS = """
    StatsWidget {
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: #A0A880;
        text-style: none;
    }
    """

    def __init__(self) -> None:
        super().__init__("No stats yet")
