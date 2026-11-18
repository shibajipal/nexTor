"""Directory picker modal — lets the user browse and select a download folder."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Static


def _get_root_path() -> str:
    """Return a sensible root for the directory tree.

    On Windows we want to show drive letters (C:\\, D:\\, etc.), so we
    start at the root of the current drive.  The user can type another
    drive letter into the input field.
    """
    if sys.platform == "win32":
        # Start at the filesystem root of the current drive (e.g. C:\)
        return os.path.splitdrive(os.getcwd())[0] + "\\"
    return "/"


class DirOnlyTree(DirectoryTree):
    """A DirectoryTree that only shows directories (no files)."""

    def filter_paths(self, paths):
        return [p for p in paths if p.is_dir()]


class DirectoryPickerScreen(ModalScreen[str | None]):
    """Modal popup that lets the user browse to a directory and confirm."""

    DEFAULT_CSS = """
    DirectoryPickerScreen {
        align: center middle;
    }

    #dir-picker-dialog {
        width: 70;
        height: 30;
        border: round #C8D6A0;
        background: #2E3A1F;
        padding: 1 2;
    }

    #dir-picker-title {
        width: 100%;
        height: 1;
        text-align: center;
        color: #FFFFFF;
        text-style: none;
        margin-bottom: 1;
    }

    #dir-tree {
        width: 100%;
        height: 1fr;
        background: #1E2714;
        color: #A0A880;
        border: tall #4A5A30;
        margin-bottom: 1;
    }

    #dir-path-input {
        width: 100%;
        height: 3;
        background: #1E2714;
        color: #E0E8D0;
        border: tall #4A5A30;
        margin-bottom: 1;
    }

    #dir-picker-buttons {
        width: 100%;
        height: 3;
        align-horizontal: right;
    }

    #dir-picker-buttons Button {
        min-width: 16;
        height: 3;
        margin-left: 1;
        text-style: none;
    }

    #btn-select {
        background: #4A5A30;
        color: #FFFFFF;
        border: tall #C8D6A0;
    }

    #btn-select:hover {
        background: #5A6A40;
    }

    #btn-cancel {
        background: #3A2A1F;
        color: #FFFFFF;
        border: tall #8A7A6A;
    }

    #btn-cancel:hover {
        background: #4A3A2F;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, start_path: str | None = None) -> None:
        super().__init__()
        self._start = start_path or _get_root_path()

    def compose(self) -> ComposeResult:
        with Vertical(id="dir-picker-dialog"):
            yield Static("📂  Choose Download Directory", id="dir-picker-title")
            yield DirOnlyTree(self._start, id="dir-tree")
            yield Input(value=self._start, placeholder="Directory path...", id="dir-path-input")
            with Horizontal(id="dir-picker-buttons"):
                yield Button("Cancel", id="btn-cancel")
                yield Button("✓  Select", id="btn-select")

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """When the user clicks on a directory in the tree, update the input."""
        self.query_one("#dir-path-input", Input).value = str(event.path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-select":
            path = self.query_one("#dir-path-input", Input).value.strip()
            if path:
                self.dismiss(path)
            else:
                self.dismiss(None)
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow pressing Enter in the input to confirm."""
        path = event.value.strip()
        if path:
            self.dismiss(path)

    def action_cancel(self) -> None:
        self.dismiss(None)
