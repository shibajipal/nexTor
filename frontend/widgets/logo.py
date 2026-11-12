"""Logo panel - renders the nexTor ASCII art cleanly without line wrapping."""
from rich.text import Text
from textual.widgets import Static
from textual import events

from ..theme import NEXTOR_ASCII, NEXTOR_ASCII_COMPACT


class LogoWidget(Static):
    """Displays the nexTor ASCII logo without line-wrapping or corruption."""

    DEFAULT_CSS = """
    LogoWidget {
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: #FFFFFF;
        text-style: none;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text(NEXTOR_ASCII, no_wrap=True))

    def on_resize(self, event: events.Resize) -> None:
        """Adapt between full ANSI shadow and compact ASCII on small terminals."""
        if event.size.width < 54:
            self.update(Text(NEXTOR_ASCII_COMPACT, no_wrap=True))
        else:
            self.update(Text(NEXTOR_ASCII, no_wrap=True))
