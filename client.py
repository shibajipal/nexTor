# client.py
# this is the main file that is run, and both downloading torrent and magnet files is supported
# usage:-  python client.py download_torrent <path> <torrent>
import os
import sys
import time
import socket
import math
import bencodepy
import asyncio
from downloader import download_piece, ChokedError
from storage import TorrentStorage
from parser import calculate_info_hash, parse_magnet_link, parse_torrent, parse_file_info
from peer import read_exactly, tcp_handshake, extension_handshake, find_peers, PeerSession, find_peers_auto
from concurrent.futures import ThreadPoolExecutor, as_completed


def format_size(n):
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024**3):.2f} GB"
    elif n >= 1024 * 1024:
        return f"{n / (1024**2):.1f} MB"
    else:
        return f"{n / 1024:.0f} KB"

class ProgressTracker:
    """Terminal progress tracker with requested UI format."""

    # ANSI color codes
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    def __init__(self, piece_count, piece_length, total_length, file_name="Download"):
        self.piece_count = piece_count
        self.piece_length = piece_length
        self.total_length = total_length
        self.file_name = file_name
        self.completed_pieces = 0
        self.bytes_downloaded = 0
        self.start_time = time.time()
        
        self.min_speed = float('inf')
        self.max_speed = 0.0
        self._last_time = self.start_time
        self._last_downloaded = 0
        self._current_speed = 0.0

        self.active_pieces = {}  # shared dict: piece_index -> (received, total)
        self.active_peers = {}   # peer_id -> piece_index
        self._peer_speeds = {}   # peer_id -> (last_time, last_received, speed, piece_index)
        self._last_lines = 0     # how many lines we printed last frame

    def update(self, piece_bytes):
        self.completed_pieces += 1
        self.bytes_downloaded += piece_bytes

    @staticmethod
    def _format_time(seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"

    @staticmethod
    def _format_speed(speed):
        if speed >= 1024 * 1024:
            return f"{speed / (1024**2):.1f} MB/s"
        return f"{speed / 1024:.1f} KB/s"

    def display(self):
        elapsed = time.time() - self.start_time
        
        active_bytes = sum(recv for recv, _ in list(self.active_pieces.values()))
        downloaded = self.bytes_downloaded + active_bytes
        
        percent = downloaded / self.total_length if self.total_length > 0 else 0

        avg_speed = downloaded / elapsed if elapsed > 0 else 0
        remaining = self.total_length - downloaded
        eta = remaining / avg_speed if avg_speed > 0 else 0

        current_time = time.time()
        dt = current_time - self._last_time
        if dt >= 0.5:
            self._current_speed = (downloaded - self._last_downloaded) / dt
            self._last_downloaded = downloaded
            self._last_time = current_time
            
            if self._current_speed > 0 and self._current_speed < self.min_speed:
                self.min_speed = self._current_speed
            if self._current_speed > self.max_speed:
                self.max_speed = self._current_speed

        speed_str = self._format_speed(self._current_speed)
        avg_speed_str = self._format_speed(avg_speed)
        min_speed_str = self._format_speed(self.min_speed) if self.min_speed != float('inf') else "0.0 KB/s"
        max_speed_str = self._format_speed(self.max_speed)
        eta_str = self._format_time(eta)
        pieces_str = f"{self.completed_pieces}/{self.piece_count}"

        if self._last_lines > 1:
            sys.stdout.write(f"\r\033[{self._last_lines - 1}A")
        elif self._last_lines == 1:
            sys.stdout.write("\r")

        lines = []

        # ── overall progress UI ──
        bar_w = 30
        filled = int(bar_w * percent)
        bar = f"{'#' * filled}{'-' * (bar_w - filled)}"
        
        lines.append(f"{self.CYAN}{'=' * 78}{self.RESET}")
        
        pct_str = f"<{percent*100:.1f}%>"
        visible_len = len(self.file_name) + 1 + 1 + bar_w + 1 + 1 + len(pct_str)
        pad = max(0, 78 - visible_len) // 2
        lines.append(" " * pad + f"{self.file_name} [{bar}] {pct_str}")
        
        lines.append(f"{self.CYAN}{'=' * 78}{self.RESET}")
        
        header = f"{'Curr Speed':<14}{'Min Speed':<14}{'Avg Speed':<14}{'Max Speed':<14}{'ETA':<10}{'piece count':<12}"
        lines.append(header)
        
        values = f"{speed_str:<14}{min_speed_str:<14}{avg_speed_str:<14}{max_speed_str:<14}{eta_str:<10}{pieces_str:<12}"
        lines.append(values)
        
        lines.append(f"{self.CYAN}{'=' * 78}{self.RESET}")

        
        active = dict(self.active_pieces)
        peers = dict(self.active_peers)
        
        peer_stats = []
        for peer_id, idx in peers.items():
            if idx in active:
                recv, total = active[idx]
                if peer_id not in self._peer_speeds:
                    self._peer_speeds[peer_id] = (current_time, recv, 0, idx, total)
                    peer_speed = 0
                else:
                    state = self._peer_speeds[peer_id]
                    # Handle tuple length gracefully in case of hot-reload
                    if len(state) == 4:
                        last_time, last_recv, last_speed, last_idx = state
                        last_total = total
                    else:
                        last_time, last_recv, last_speed, last_idx, last_total = state
                        
                    p_dt = current_time - last_time
                    
                    if p_dt >= 0.5:
                        if p_dt > 3.0:
                            # If it's been asleep/choked for a long time, don't calculate a massive spike
                            peer_speed = 0
                        else:
                            if last_idx == idx:
                                bytes_diff = recv - last_recv
                            else:
                                bytes_diff = max(0, last_total - last_recv) + recv
                                
                            raw_speed = max(0, bytes_diff / p_dt)
                            peer_speed = (0.6 * raw_speed) + (0.4 * last_speed) if last_speed > 0 else raw_speed
                        
                        self._peer_speeds[peer_id] = (current_time, recv, peer_speed, idx, total)
                    else:
                        peer_speed = last_speed
                        
                peer_stats.append((peer_id, peer_speed, idx, recv, total))
        seen = set()
        peer_stats = [x for x in peer_stats if not(x[0] in seen or seen.add(x[0]))]
        peer_stats.sort(key=lambda x: x[1], reverse=True)
        top_peers = peer_stats[:5]
        
        if top_peers:
            lines.append(f"{self.DIM}Top Peers in Swarm (Active: {len(peers)}):{self.RESET}")
            for host, p_speed, idx, recv, total in top_peers:
                p = recv / total if total > 0 else 0
                p_speed_str = self._format_speed(p_speed)
                lines.append(
                    f"  {self.CYAN}{host:<21}{self.RESET} | "
                    f"{self.GREEN}{p_speed_str:<10}{self.RESET} | "
                    f"Piece {idx:>4} ({p*100:>5.1f}%)"
                )

        # pad with blank lines if fewer active pieces than last frame
        while len(lines) < self._last_lines:
            lines.append("")

        output = "\n".join(f"\033[K{l}" for l in lines)
        sys.stdout.write(output)
        sys.stdout.flush()
        self._last_lines = len(lines)


def try_connect(peer_address, info_hash):
    HOST, PORT = peer_address.split(":")
    session = PeerSession(HOST, int(PORT), info_hash)
    session.connect()
    return session

async def endgame_checker(content_pieces, queue, sessions, piece_count):
    threshold = len(sessions)
    triggered = False
    
    while not triggered:
        await asyncio.sleep(1)
        remaining = [i for i in range(piece_count) if content_pieces[i] is None]
        if not remaining:
            return  # all done, nothing to do
        if len(remaining) <= threshold:
            triggered = True
            print("ENDGAME MODE BABY!")
            for piece_index in remaining:
                for _ in sessions:
                    queue.put_nowait(piece_index)
                    

async def peer_worker(storage, session, queue, length, total_length, content_pieces, progress):
    while True:
        try:
            piece_index = queue.get_nowait()
        except asyncio.QueueEmpty:
            # Check if all pieces are done before exiting
            if all(p is not None for p in content_pieces):
                return
            # Queue is empty but pieces still downloading, wait a bit and retry
            await asyncio.sleep(0.1)
            continue
        
        
        if content_pieces[piece_index] is not None:
            continue
        
        if not session.has_piece(piece_index):
            queue.put_nowait(piece_index)
            await asyncio.sleep(0)
            continue
        
        try:
            peer_id = f"{session.host}:{session.port}"
            progress.active_peers[peer_id] = piece_index
            loop = asyncio.get_event_loop()
            try:
                buffer = await loop.run_in_executor(
                    None, download_piece, storage, session.sock, piece_index, length, total_length, progress.active_pieces
                )
            finally:
                if progress.active_peers.get(peer_id) == piece_index:
                    del progress.active_peers[peer_id]
            
            if content_pieces[piece_index] is None:
                content_pieces[piece_index] = buffer
                progress.update(len(buffer))
        except ChokedError:
            # peer choked us — put piece back for another peer
            queue.put_nowait(piece_index)
            # wait for unchoke in a thread so we don't block the event loop
            def wait_for_unchoke():
                while True:
                    msg_id, _ = session.read_message()
                    if msg_id == 1:  # unchoke
                        return
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, wait_for_unchoke),
                    timeout=30
                )
            except Exception:
                return  # peer is dead or timed out, stop this worker
        except Exception as e:
            # timeout, disconnect, etc. — put piece back and retire this peer
            queue.put_nowait(piece_index)
            # print(f"\npeer {session.host} failed: {e}")
            return
        
async def progress_display(progress):
    while progress.completed_pieces < progress.piece_count:
        progress.display()
        await asyncio.sleep(0.3)

async def download_all(storage, sessions, piece_count, length, total_length, file_name="Download"):
    print("test1")
    content_pieces = [None] * piece_count
    queue = asyncio.Queue()
    progress = ProgressTracker(piece_count, length, total_length, file_name)
    for i in range(piece_count):
        queue.put_nowait(i)
    
    display_task = asyncio.create_task(progress_display(progress))
    endgame_task = asyncio.create_task(endgame_checker(content_pieces, queue, sessions, piece_count))
    tasks = [peer_worker(storage, session, queue, length, total_length, content_pieces, progress) for session in sessions]
    await asyncio.gather(*tasks)
    
    # workers are done — stop background tasks and do final display
    endgame_task.cancel()
    display_task.cancel()
    try:
        await display_task
    except asyncio.CancelledError:
        pass
    progress.active_pieces.clear()
    progress.display()
    print("test")  # final newline
    
    # Close all file handles to ensure data is flushed to disk
    storage.close_all()
    
    return 1
    # return b"".join(content_pieces)
async def main():
    command = sys.argv[1]
    if command == "download_torrent":
        download_path = sys.argv[2]
        file = sys.argv[3]
        
        content = parse_torrent(file)
        tracker = content[b"announce"]
        length = content[b"info"][b"piece length"]
        files, total_length = parse_file_info(content[b"info"])
        
        info_hash = calculate_info_hash(content)
        
        
        trackers = []
        if b"announce-list" in content:
            for tier in content[b"announce-list"]:
                for tracker_url in tier:
                    trackers.append(tracker_url)
            trackers.extend([content[b"announce"]])
        else:
            trackers = [content[b"announce"]]
        
        # query all trackers in parallel (5s timeout each)
        all_peers = set()
        def query_tracker(t):
            return find_peers_auto(tracker=t, info_hash=info_hash, left=total_length)
        with ThreadPoolExecutor(max_workers=250) as executor:
            futures = {executor.submit(query_tracker, t): t for t in trackers}
            try:
                for future in as_completed(futures, timeout=10):
                    t = futures[future]
                    try:
                        peers = future.result(timeout=5)
                        all_peers.update(peers)
                    except Exception as e:
                        print(f"tracker {t} failed: {e}")
            except TimeoutError:
                print(f"tracker discovery timed out, continuing with {len(all_peers)} peers found")
        all_peers = list(all_peers)
        print(f"found {len(all_peers)} unique peers from {len(trackers)} trackers")

        sessions = []
        with ThreadPoolExecutor(max_workers=250) as executor:
            futures = {
                executor.submit(try_connect, peer, info_hash) : peer for peer in all_peers
            }
            
            for future in as_completed(futures):
                p = futures[future]
                try:
                    session = future.result()
                    sessions.append(session)
                    print(f"connected to {p}")
                except Exception as e:
                    print(f"failed to connect to {p}: {e}")
        print(f"sessions: {sessions}")

            
        total_content = b""
        piece_count = math.ceil(total_length / length)
        # For multi-file torrents, use full download_path; for single-file, use dirname
        if len(files) > 1:
            download_dir = download_path
        else:
            download_dir = os.path.dirname(download_path) if os.path.dirname(download_path) else "."
        storage = TorrentStorage(download_dir, files, length)
        print(f"there are {len(files)} files in total and total length is {total_length}")
        print(f"the info hash is {info_hash}")
        print(f"there will be total {piece_count} pieces and each piece is {length}")
        print(f"saving to directory: {download_dir}")
        
        torrent_name = content[b"info"].get(b"name", b"").decode("utf-8", "replace")
        if not torrent_name:
            torrent_name = os.path.basename(file)

        val = await download_all(storage, sessions, piece_count, length, total_length, torrent_name)

    elif command == "magnet_download":
        ### this is unusuable at the moment, will fix it later!
        download_path = sys.argv[2]
        magnet_link = sys.argv[3]
        info_hash, trackers = parse_magnet_link(magnet_link)
        info_hash = bytes.fromhex(info_hash)
        
        # query all trackers in parallel to find peers (5s timeout each)
        all_peers = set()
        def query_tracker(t):
            return find_peers_auto(tracker=t, info_hash=info_hash, left=10)
        with ThreadPoolExecutor(max_workers=250) as executor:
            futures = {executor.submit(query_tracker, t): t for t in trackers}
            try:
                for future in as_completed(futures, timeout=10):
                    t = futures[future]
                    try:
                        peers = future.result(timeout=5)
                        all_peers.update(peers)
                    except Exception as e:
                        print(f"tracker {t} failed: {e}")
            except TimeoutError:
                print(f"tracker discovery timed out, continuing with {len(all_peers)} peers found")
        all_peers = list(all_peers)
        print(f"found {len(all_peers)} unique peers from {len(trackers)} trackers")
        
        if not all_peers:
            raise Exception("Could not find any peers from the provided magnet trackers.")
            
        # Race to fetch metadata from any of these peers
        info = None
        def fetch_metadata_from_peer(p_addr):
            HOST, PORT = p_addr.split(":")
            peer = socket.create_connection((HOST, int(PORT)), timeout=5)
            tcp_handshake(sock=peer, info_hash=info_hash, type="magnet")
            peer_metadata_id = extension_handshake(peer)
            
            request_payload = bencodepy.encode({b"msg_type": 0, b"piece": 0})
            request_msg = (len(request_payload) + 2).to_bytes(4, "big") + (20).to_bytes(1, "big") + int(peer_metadata_id).to_bytes(1, "big") + request_payload
            peer.send(request_msg)
            
            while True:
                length_prefix = read_exactly(peer, 4)
                message_length = int.from_bytes(length_prefix, "big")
                message_body = read_exactly(peer, message_length)
                if message_body[0] == 20:
                    payload = message_body[2:]
                    dict_end = payload.index(b"ee") + 2
                    raw_info = payload[dict_end:]
                    info_dict = bencodepy.decode(raw_info)
                    peer.close()
                    return info_dict

        print("Fetching metadata from peers in parallel...")
        with ThreadPoolExecutor(max_workers=250) as executor:
            futures = {executor.submit(fetch_metadata_from_peer, p): p for p in all_peers}
            for future in as_completed(futures):
                try:
                    info = future.result()
                    print(f"Successfully fetched metadata!")
                    break
                except Exception:
                    pass
                    
        if not info:
            raise Exception("Could not fetch metadata from any peer.")
            
        length = info[b"piece length"]
        files, total_length = parse_file_info(info)

        sessions = []
        with ThreadPoolExecutor(max_workers=250) as executor:
            futures = {
                executor.submit(try_connect, p_addr, info_hash) : p_addr for p_addr in all_peers
            }
            
            for future in as_completed(futures):
                p_addr = futures[future]
                try:
                    session = future.result()
                    sessions.append(session)
                    print(f"connected to {p_addr}")
                except Exception as e:
                    print(f"failed to connect to {p_addr}: {e}")
        print(f"sessions: {sessions}")

            
        total_content = b""
        piece_count = math.ceil(total_length / length)
        # For multi-file torrents, use full download_path; for single-file, use dirname
        if len(files) > 1:
            download_dir = download_path
        else:
            download_dir = os.path.dirname(download_path) if os.path.dirname(download_path) else "."
        storage = TorrentStorage(download_dir, files, length)
        print(f"there are {len(files)} files in total and total length is {total_length}")
        print(f"the info hash is {info_hash}")
        print(f"there will be total {piece_count} pieces and each piece is {length}")
        print(f"saving to directory: {download_dir}")
        
        torrent_name = info.get(b"name", b"").decode("utf-8", "replace")
        if not torrent_name:
            torrent_name = os.path.basename(download_path)

        val = await download_all(storage, sessions, piece_count, length, total_length, torrent_name)
    else:
        raise NotImplementedError(f"Unknown command {command}")
        
if __name__ == "__main__":
    asyncio.run(main())