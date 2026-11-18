"""Stats panel — shows torrent metadata, then live download progress."""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import time
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parser import calculate_info_hash, parse_file_info
from client import DownloadManager, ProgressTracker, format_size
from storage import TorrentStorage


def _fmt_size(n: int) -> str:
    """Human-readable byte size."""
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.2f} GB"
    elif n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    elif n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


# ─── Messages ───────────────────────────────────────────────────────────────

class DownloadStarted(Message):
    """Fired when a download begins, so the app can update other panels."""
    def __init__(self, torrent_name: str) -> None:
        super().__init__()
        self.torrent_name = torrent_name


class DownloadFinished(Message):
    """Fired when a download completes."""
    def __init__(self, torrent_name: str, success: bool, message: str = "") -> None:
        super().__init__()
        self.torrent_name = torrent_name
        self.success = success
        self.message = message


# ─── Widget ─────────────────────────────────────────────────────────────────

class StatsWidget(Static):
    """Displays torrent metadata, directory picker, and live download stats."""

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

    #live-stats {
        width: 100%;
        height: 1fr;
        padding: 0 0;
    }

    #live-stats-scroll {
        width: 100%;
        height: 1fr;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._torrent_data: dict | None = None
        self._title: str = ""
        self._download_active: bool = False
        self._progress: ProgressTracker | None = None
        self._download_done: bool = False
        self._manager: DownloadManager | None = None
        self._refresh_timer = None

    def compose(self) -> ComposeResult:
        yield Static("No stats yet", id="stats-placeholder")

    # ── Show initial torrent info (before download) ──────────────────────

    def show_torrent_info(self, torrent_data: dict, title: str) -> None:
        """Populate the panel with parsed torrent metadata."""
        self._torrent_data = torrent_data
        self._title = title
        self._download_active = False
        self._download_done = False
        info = torrent_data.get(b"info", {})

        name = info.get(b"name", b"Unknown").decode("utf-8", "replace")
        raw_created = torrent_data.get(b"created by", b"")
        if isinstance(raw_created, bytes):
            created_by = raw_created.decode("utf-8", "replace") or "N/A"
        else:
            created_by = str(raw_created) or "N/A"

        piece_length = info.get(b"piece length", 0)
        pieces_blob = info.get(b"pieces", b"")
        piece_count = len(pieces_blob) // 20 if pieces_blob else 0
        files, total_length = parse_file_info(info)
        file_count = len(files)

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
            lines.append("")

        markup = "\n".join(lines)

        # Swap UI
        self._clear_all()

        info_static = Static(markup, id="stats-scroll")
        info_static.styles.width = "100%"
        info_static.styles.height = "auto"
        info_static.styles.padding = (1, 0)

        self.mount(info_static)
        self.mount(Button("⬇  Download Now", id="download-btn"))

    # ── Button handler → open directory picker ───────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "download-btn" and not self._download_active:
            self._open_dir_picker()

    def _open_dir_picker(self) -> None:
        from .dir_picker import DirectoryPickerScreen
        self.app.push_screen(DirectoryPickerScreen(), callback=self._on_dir_chosen)

    def _on_dir_chosen(self, chosen_dir: str | None) -> None:
        if chosen_dir is None:
            return
        if not os.path.isdir(chosen_dir):
            try:
                os.makedirs(chosen_dir, exist_ok=True)
            except OSError:
                return

        self._start_download(chosen_dir)

    # ── Download orchestration ───────────────────────────────────────────

    def _start_download(self, download_dir: str) -> None:
        """Set up the DownloadManager and switch stats to live-progress view."""
        if self._torrent_data is None or self._download_active:
            return

        self._download_active = True
        info = self._torrent_data[b"info"]

        # Parse torrent metadata
        piece_length = info[b"piece length"]
        files, total_length = parse_file_info(info)
        info_hash = calculate_info_hash(self._torrent_data)

        trackers = []
        if b"announce-list" in self._torrent_data:
            for tier in self._torrent_data[b"announce-list"]:
                for tracker_url in tier:
                    trackers.append(tracker_url)
            trackers.append(self._torrent_data[b"announce"])
        else:
            trackers = [self._torrent_data[b"announce"]]

        piece_count = math.ceil(total_length / piece_length)
        pieces_hash = info[b"pieces"]

        torrent_name = info.get(b"name", b"").decode("utf-8", "replace")
        if not torrent_name:
            torrent_name = self._title

        # Create storage
        storage = TorrentStorage(download_dir, files, piece_length)

        # Create DownloadManager
        self._manager = DownloadManager(
            storage, info_hash, trackers, piece_count,
            piece_length, total_length, torrent_name,
            pieces_hash=pieces_hash,
        )

        # Create ProgressTracker for the UI to read
        self._progress = ProgressTracker(piece_count, piece_length, total_length, torrent_name)

        # Switch to live-progress view
        self._show_live_stats_view(torrent_name, total_length, piece_count, piece_length)

        # Fire app-level message
        self.post_message(DownloadStarted(torrent_name))

        # Launch the download worker
        self._run_download(storage, pieces_hash, piece_count, piece_length, total_length)

    def _show_live_stats_view(self, name: str, total_length: int, piece_count: int, piece_length: int) -> None:
        """Replace the stats panel content with live download stats."""
        self._clear_all()

        # Build initial "connecting" view in the same compact format
        bar_w = 30
        bar = f"{'░' * bar_w}"
        pieces_str = f"0/{piece_count}"

        lines = []
        lines.append(f"[#A0A880]  TORRENT NAME[/]")
        lines.append(f"[#FFFFFF]    {name}  [#A0A880]({_fmt_size(total_length)})[/][/]")
        lines.append("")
        lines.append(f"[#A0A880]  PIECES[/]")
        lines.append(f"[#FFFFFF]    {piece_count:,}  [#A0A880]({_fmt_size(piece_length)} each)[/][/]")
        lines.append("")
        lines.append(f"[#4A5A30]  {'─' * 40}[/]")
        lines.append("")
        lines.append(f"[#FFFFFF]  [{bar}] 0.0% [#A0A880]({pieces_str})[/]  [#A0A880]ETA[/] --:--[/]")
        lines.append("")
        lines.append(f"[#4A5A30]  {'─' * 40}[/]")
        lines.append("")
        lines.append(f"[#A0A880]  DL Speed  [/][#FFFFFF]{'0.0 KB/s':<14}[/][#A0A880]UL Speed  [/][#FFFFFF]0.0 KB/s[/]")
        lines.append(f"[#A0A880]  Total DL  [/][#FFFFFF]{'0.0 MiB':<14}[/][#A0A880]Total UL  [/][#FFFFFF]0.0 MiB[/]")
        lines.append("")
        lines.append(f"[#A0A880]  Connecting to peers...[/]")

        markup = "\n".join(lines)

        scroll = VerticalScroll(id="live-stats-scroll")
        scroll.styles.width = "100%"
        scroll.styles.height = "1fr"
        self.mount(scroll)

        live = Static(markup, id="live-stats")
        live.styles.width = "100%"
        live.styles.height = "auto"
        live.styles.padding = (1, 0)
        scroll.mount(live)

        # Start the refresh timer (updates every 0.5s)
        self._refresh_timer = self.set_interval(0.5, self._refresh_live_stats)

    def _refresh_live_stats(self) -> None:
        """Read from the ProgressTracker and update the live-stats widget."""
        p = self._progress
        if p is None:
            return

        try:
            live = self.query_one("#live-stats", Static)
        except Exception:
            return

        name = p.file_name
        total = p.total_length
        pc = p.piece_count
        pl = p.piece_length

        # Recalculate speeds (mimicking ProgressTracker.display logic)
        current_time = time.time()
        elapsed = current_time - p.start_time

        active_bytes = sum(recv for recv, _ in list(p.active_pieces.values()))
        committed = p.bytes_downloaded
        downloaded = committed + active_bytes

        percent = min(1.0, committed / total) if total > 0 else 0

        avg_speed = committed / elapsed if elapsed > 0 else 0
        remaining = max(0, total - committed)
        eta = remaining / avg_speed if avg_speed > 0 else 0

        dt = current_time - p._last_time
        if dt >= 0.3:
            raw_speed = max(0.0, (downloaded - p._last_downloaded) / dt)
            raw_ul_speed = max(0.0, (p.bytes_uploaded - p._last_uploaded) / dt)

            if p._current_speed > 0:
                p._current_speed = 0.6 * raw_speed + 0.4 * p._current_speed
            else:
                p._current_speed = raw_speed

            if p._current_ul_speed > 0:
                p._current_ul_speed = 0.6 * raw_ul_speed + 0.4 * p._current_ul_speed
            else:
                p._current_ul_speed = raw_ul_speed

            p._last_downloaded = downloaded
            p._last_uploaded = p.bytes_uploaded
            p._last_time = current_time

        # Format values
        dl_speed = p._format_speed(p._current_speed)
        ul_speed = p._format_speed(p._current_ul_speed)
        total_dl = f"{downloaded / (1024**2):.1f} MiB"
        total_ul = f"{p.bytes_uploaded / (1024**2):.1f} MiB"
        eta_str = p._format_time(eta)
        pct_str = f"{percent * 100:.1f}%"
        pieces_done = f"{p.completed_pieces}/{pc}"

        # Build progress bar
        bar_w = 30
        filled = min(bar_w, int(bar_w * percent))
        bar = f"{'█' * filled}{'░' * (bar_w - filled)}"

        lines = []
        lines.append(f"[#A0A880]  TORRENT NAME[/]")
        lines.append(f"[#FFFFFF]    {name}  [#A0A880]({_fmt_size(total)})[/][/]")
        lines.append("")
        lines.append(f"[#A0A880]  PIECES[/]")
        lines.append(f"[#FFFFFF]    {pc:,}  [#A0A880]({_fmt_size(pl)} each)[/][/]")
        lines.append("")
        lines.append(f"[#4A5A30]  {'─' * 40}[/]")
        lines.append("")

        # Progress bar with piece count in brackets + ETA to the right
        lines.append(f"[#FFFFFF]  [{bar}] {pct_str} [#A0A880]({pieces_done})[/]  [#A0A880]ETA[/] {eta_str}[/]")
        lines.append("")
        lines.append(f"[#4A5A30]  {'─' * 40}[/]")
        lines.append("")

        # DL Speed + UL Speed on the same line
        lines.append(f"[#A0A880]  DL Speed  [/][#FFFFFF]{dl_speed:<14}[/][#A0A880]UL Speed  [/][#FFFFFF]{ul_speed}[/]")
        # Total DL + Total UL on the same line
        lines.append(f"[#A0A880]  Total DL  [/][#FFFFFF]{total_dl:<14}[/][#A0A880]Total UL  [/][#FFFFFF]{total_ul}[/]")
        lines.append("")

        # Active peers downloading from
        peers = dict(p.active_peers)
        active_pieces = dict(p.active_pieces)
        if peers:
            lines.append(f"[#4A5A30]  {'─' * 40}[/]")
            lines.append(f"[#A0A880]  Peers Downloading From (Active: {len(peers)})[/]")
            # Show top 5 by activity
            peer_list = []
            for peer_id, idx in peers.items():
                if idx in active_pieces:
                    recv, tot = active_pieces[idx]
                    pct_p = (recv / tot * 100) if tot > 0 else 0
                    peer_list.append((peer_id, idx, pct_p))
            peer_list.sort(key=lambda x: x[2], reverse=True)
            for host, idx, pct_p in peer_list[:5]:
                h = host[:21] if len(host) > 21 else host
                lines.append(f"[#FFFFFF]    {h:<21}[/] [#A0A880]|[/] [#FFFFFF]Piece {idx:>4} ({pct_p:>5.1f}%)[/]")
            lines.append("")

        # Active peers uploading to
        ul_peers = dict(p.active_upload_peers)
        if ul_peers:
            lines.append(f"[#A0A880]  Peers Uploading To (Active: {len(ul_peers)})[/]")
            ul_list = []
            for peer_id, (total_ul_bytes, piece_idx) in ul_peers.items():
                ul_str = f"{total_ul_bytes / 1024:.0f} KiB" if total_ul_bytes < 1024 * 1024 else f"{total_ul_bytes / (1024**2):.1f} MiB"
                ul_list.append((peer_id, piece_idx, total_ul_bytes, ul_str))
            ul_list.sort(key=lambda x: x[2], reverse=True)
            for host, idx, _, ul_s in ul_list[:5]:
                h = host[:21] if len(host) > 21 else host
                lines.append(f"[#FFFFFF]    {h:<21}[/] [#A0A880]|[/] [#FFFFFF]Piece {idx:>4} ({ul_s})[/]")
            lines.append("")

        # Completion message
        if self._download_done:
            lines.append(f"[#4A5A30]  {'─' * 40}[/]")
            lines.append(f"[#A0A880]  ✓  DOWNLOAD COMPLETE[/]")

        markup = "\n".join(lines)
        live.update(markup)

    # ── Actual download worker ───────────────────────────────────────────

    @work(thread=True, exclusive=True, group="download")
    def _run_download(self, storage: TorrentStorage, pieces_hash: bytes,
                      piece_count: int, piece_length: int, total_length: int) -> None:
        """Run the DownloadManager in a background thread."""
        manager = self._manager
        progress = self._progress
        if manager is None or progress is None:
            return

        # Monkey-patch the manager so it uses OUR progress tracker
        # We override download_all to inject our progress
        import asyncio as _aio

        async def _patched_download_all():
            from client import (
                progress_display, endgame_checker, completion_monitor,
                peer_worker, try_connect,
            )
            from concurrent.futures import ThreadPoolExecutor

            queue = _aio.Queue()

            # Resume check
            if manager.pieces_hash:
                verified_count = 0
                verified_bytes = 0
                for i in range(manager.piece_count):
                    expected = manager.pieces_hash[i * 20 : (i + 1) * 20]
                    piece_size = total_length - (i * piece_length) if (i == manager.piece_count - 1) else piece_length
                    data = storage.read_block(i, 0, piece_size)
                    if len(data) == piece_size and hashlib.sha1(data).digest() == expected:
                        manager.content_pieces[i] = True
                        storage.mark_completed(i)
                        verified_count += 1
                        verified_bytes += piece_size
                if verified_count > 0:
                    progress.completed_pieces = verified_count
                    progress.bytes_downloaded = verified_bytes

            for i in range(manager.piece_count):
                if manager.content_pieces[i] is None:
                    queue.put_nowait(i)

            if all(p is not None for p in manager.content_pieces):
                storage.flush_all()
                return 1

            # No display_task — the TUI handles display via refresh timer
            endgame_task = _aio.create_task(endgame_checker(manager.content_pieces, queue, manager.sessions, manager.piece_count))
            monitor_task = _aio.create_task(completion_monitor(manager.content_pieces, manager.sessions))

            peer_workers = set()
            connected_addrs = set()
            loop = _aio.get_running_loop()

            from client import find_peers_auto
            tracker_executor = ThreadPoolExecutor(max_workers=max(30, len(manager.trackers) + 5), thread_name_prefix="tracker")
            conn_executor = ThreadPoolExecutor(max_workers=100, thread_name_prefix="conn")

            async def tracker_worker(t):
                while not all(p is not None for p in manager.content_pieces):
                    try:
                        left_bytes = max(0, total_length - progress.bytes_downloaded)
                        peers = await loop.run_in_executor(
                            tracker_executor, lambda: find_peers_auto(t, manager.info_hash, left=left_bytes)
                        )
                        if peers:
                            for p in peers:
                                if p not in connected_addrs:
                                    manager.all_peers.add(p)
                            await _aio.sleep(45)
                        else:
                            await _aio.sleep(15)
                    except Exception:
                        await _aio.sleep(15)

            async def tracker_discovery():
                tasks = [_aio.create_task(tracker_worker(t)) for t in manager.trackers]
                if tasks:
                    await _aio.gather(*tasks, return_exceptions=True)

            async def connection_worker():
                pending_connections = set()
                last_connect_attempt = {}
                while not all(p is not None for p in manager.content_pieces):
                    now = time.time()
                    unconnected = [
                        p for p in list(manager.all_peers)
                        if p not in connected_addrs and p not in pending_connections
                        and (now - last_connect_attempt.get(p, 0)) >= 15
                    ]
                    for p_addr in unconnected:
                        pending_connections.add(p_addr)
                        last_connect_attempt[p_addr] = now

                        async def connect_and_spawn(addr):
                            try:
                                session = await loop.run_in_executor(conn_executor, try_connect, addr, manager.info_hash, storage)
                                manager.sessions.append(session)
                                connected_addrs.add(addr)
                                worker_task = _aio.create_task(
                                    peer_worker(storage, session, queue, manager.length, total_length, manager.content_pieces, progress, manager.sessions, connected_addrs, addr)
                                )
                                peer_workers.add(worker_task)
                                worker_task.add_done_callback(peer_workers.discard)
                            except Exception:
                                pass
                            finally:
                                pending_connections.discard(addr)

                        _aio.create_task(connect_and_spawn(p_addr))
                    await _aio.sleep(0.5)

            discovery_task = _aio.create_task(tracker_discovery())
            conn_task = _aio.create_task(connection_worker())

            await monitor_task

            discovery_task.cancel()
            conn_task.cancel()
            endgame_task.cancel()
            for w in list(peer_workers):
                w.cancel()

            tracker_executor.shutdown(wait=False)
            conn_executor.shutdown(wait=False)

            storage.flush_all()
            return 1

        # Run the patched download in a new event loop on this thread
        loop = _aio.new_event_loop()
        try:
            loop.run_until_complete(_patched_download_all())
        finally:
            loop.close()

        # Verify SHA1
        pieces_hash_local = pieces_hash
        failed = []
        for i in range(piece_count):
            expected = pieces_hash_local[i * 20 : (i + 1) * 20]
            if i == piece_count - 1:
                piece_size = total_length - (i * piece_length)
            else:
                piece_size = piece_length
            data = storage.read_block(i, 0, piece_size)
            actual = hashlib.sha1(data).digest()
            if actual != expected:
                failed.append(i)

        storage.close_all()

        self._download_done = True
        self._download_active = False

        name = progress.file_name
        if failed:
            msg = f"SHA1 FAILED for {len(failed)} piece(s)"
            self.app.call_from_thread(self.post_message, DownloadFinished(name, False, msg))
        else:
            msg = f"All {piece_count} pieces verified OK"
            self.app.call_from_thread(self.post_message, DownloadFinished(name, True, msg))

        # Stop the refresh timer after a final refresh
        def _stop():
            self._refresh_live_stats()
            if self._refresh_timer is not None:
                self._refresh_timer.stop()
                self._refresh_timer = None

        self.app.call_from_thread(_stop)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _clear_all(self) -> None:
        """Remove all children from the widget."""
        for sel in ("#stats-placeholder", "#stats-scroll", "#download-btn", "#live-stats-scroll", "#live-stats"):
            try:
                self.query_one(sel).remove()
            except Exception:
                pass
