# client.py
# this is the main file that is run, and both downloading torrent and magnet files is supported
# usage:-  python client.py download_torrent <path> <torrent>
import os
import sys
import time
import socket
import math
import hashlib
import bencodepy
import asyncio
import select
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
        self.bytes_uploaded = 0
        self.start_time = time.time()
        
        self.min_speed = float('inf')
        self.max_speed = 0.0
        self._last_time = self.start_time
        self._last_downloaded = 0
        self._last_uploaded = 0
        self._current_speed = 0.0
        self._current_ul_speed = 0.0

        self.active_pieces = {}  # shared dict: piece_index -> (received, total)
        self.active_peers = {}   # peer_id -> piece_index
        self.active_upload_peers = {} # peer_id -> (bytes_uploaded_total, last_piece)
        self._peer_speeds = {}   # peer_id -> (last_time, last_received, speed, piece_index)
        self._peer_ul_speeds = {} # peer_id -> (last_time, last_bytes, speed, last_piece)
        self._last_lines = 0     # how many lines we printed last frame

    def update(self, piece_bytes):
        self.completed_pieces += 1
        self.bytes_downloaded += piece_bytes

    def update_upload(self, bytes_sent, peer_id, piece_idx):
        self.bytes_uploaded += bytes_sent
        cur_bytes, _ = self.active_upload_peers.get(peer_id, (0, piece_idx))
        self.active_upload_peers[peer_id] = (cur_bytes + bytes_sent, piece_idx)

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
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        active_bytes = sum(recv for recv, _ in list(self.active_pieces.values()))
        committed = self.bytes_downloaded
        downloaded = committed + active_bytes

        percent = min(1.0, committed / self.total_length) if self.total_length > 0 else 0

        avg_speed = committed / elapsed if elapsed > 0 else 0
        remaining = max(0, self.total_length - committed)
        eta = remaining / avg_speed if avg_speed > 0 else 0

        dt = current_time - self._last_time
        if dt >= 0.3:
            raw_speed = max(0.0, (downloaded - self._last_downloaded) / dt)
            raw_ul_speed = max(0.0, (self.bytes_uploaded - self._last_uploaded) / dt)

            if self._current_speed > 0:
                self._current_speed = 0.6 * raw_speed + 0.4 * self._current_speed
            else:
                self._current_speed = raw_speed
                
            if self._current_ul_speed > 0:
                self._current_ul_speed = 0.6 * raw_ul_speed + 0.4 * self._current_ul_speed
            else:
                self._current_ul_speed = raw_ul_speed

            self._last_downloaded = downloaded
            self._last_uploaded = self.bytes_uploaded
            self._last_time = current_time
            
            if self._current_speed > 0:
                if self._current_speed < self.min_speed:
                    self.min_speed = self._current_speed
                if self._current_speed > self.max_speed:
                    self.max_speed = self._current_speed

        dl_speed_str = self._format_speed(self._current_speed)
        ul_speed_str = self._format_speed(self._current_ul_speed)
        total_dl_str = f"{downloaded / (1024**2):.1f} MiB"
        total_ul_str = f"{self.bytes_uploaded / (1024**2):.1f} MiB"
        eta_str = self._format_time(eta)
        pieces_str = f"{self.completed_pieces}/{self.piece_count}"

        if self._last_lines > 1:
            sys.stdout.write(f"\r\033[{self._last_lines - 1}A")
        elif self._last_lines == 1:
            sys.stdout.write("\r")

        lines = []

        # UI progress stuff
        bar_w = 30
        filled = min(bar_w, int(bar_w * percent))  # clamp to prevent overflow
        bar = f"{'#' * filled}{'-' * (bar_w - filled)}"
        
        lines.append(f"{self.CYAN}{'=' * 78}{self.RESET}")
        
        pct_str = f"<{percent*100:.1f}%>"
        visible_len = len(self.file_name) + 1 + 1 + bar_w + 1 + 1 + len(pct_str)
        pad = max(0, 78 - visible_len) // 2
        lines.append(" " * pad + f"{self.file_name} [{bar}] {pct_str}")
        
        lines.append(f"{self.CYAN}{'=' * 78}{self.RESET}")
        
        header = f"{'Curr DL Speed':<14}{'Curr UL Speed':<14}{'Total DL':<13}{'Total UL':<13}{'ETA':<10}{'Piece Count':<12}"
        lines.append(header)
        
        values = f"{dl_speed_str:<14}{ul_speed_str:<14}{total_dl_str:<13}{total_ul_str:<13}{eta_str:<10}{pieces_str:<12}"
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
                    if len(state) == 4:
                        last_time, last_recv, last_speed, last_idx = state
                        last_total = total
                    else:
                        last_time, last_recv, last_speed, last_idx, last_total = state
                        
                    p_dt = current_time - last_time
                    
                    if p_dt >= 0.5:
                        if p_dt > 3.0:
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
            lines.append(f"{self.DIM}Top Peers Downloading From (Active: {len(peers)}):{self.RESET}")
            for host, p_speed, idx, recv, total in top_peers:
                p = recv / total if total > 0 else 0
                p_speed_str = self._format_speed(p_speed)
                lines.append(
                    f"  {self.CYAN}{host:<21}{self.RESET} | "
                    f"{self.GREEN}{p_speed_str:<10}{self.RESET} | "
                    f"Piece {idx:>4} ({p*100:>5.1f}%)"
                )

        ul_peers = dict(self.active_upload_peers)
        ul_peer_stats = []
        for peer_id, (total_ul, piece_idx) in ul_peers.items():
            if peer_id not in self._peer_ul_speeds:
                self._peer_ul_speeds[peer_id] = (current_time, total_ul, 0.0, piece_idx)
                peer_ul_speed = 0.0
            else:
                last_time, last_bytes, last_speed, last_piece = self._peer_ul_speeds[peer_id]
                p_dt = current_time - last_time
                if p_dt >= 0.5:
                    if p_dt > 5.0 and total_ul == last_bytes:
                        peer_ul_speed = 0.0
                    else:
                        bytes_diff = max(0, total_ul - last_bytes)
                        raw_ul = bytes_diff / p_dt
                        peer_ul_speed = (0.6 * raw_ul) + (0.4 * last_speed) if last_speed > 0 else raw_ul
                    self._peer_ul_speeds[peer_id] = (current_time, total_ul, peer_ul_speed, piece_idx)
                else:
                    peer_ul_speed = last_speed
            ul_peer_stats.append((peer_id, peer_ul_speed, piece_idx, total_ul))

        ul_peer_stats.sort(key=lambda x: x[1], reverse=True)
        top_ul_peers = ul_peer_stats[:5]

        if top_ul_peers:
            lines.append(f"{self.DIM}Top Peers Uploading To (Active: {len(ul_peers)}):{self.RESET}")
            for host, p_speed, idx, total_ul in top_ul_peers:
                p_speed_str = self._format_speed(p_speed)
                ul_total_str = f"{total_ul / (1024**2):.2f} MiB" if total_ul >= 1024*1024 else f"{total_ul / 1024:.1f} KiB"
                lines.append(
                    f"  {self.CYAN}{host:<21}{self.RESET} | "
                    f"{self.GREEN}{p_speed_str:<10}{self.RESET} | "
                    f"Piece {idx:>4} ({ul_total_str})"
                )

        # pad with blank lines if fewer active pieces than last frame
        while len(lines) < self._last_lines:
            lines.append("")

        output = "\n".join(f"\033[K{l}" for l in lines)
        sys.stdout.write(output)
        sys.stdout.flush()
        self._last_lines = len(lines)


def try_connect(peer_address, info_hash, storage=None):
    HOST, PORT = peer_address.split(":")
    session = PeerSession(HOST, int(PORT), info_hash)
    session.connect()
    if storage:
        for p_idx in list(storage.completed):
            session.send_have(p_idx)
    return session

def _serve_idle_sync(session, storage, progress):
    try:
        if not session.sock:
            return
        r, _, _ = select.select([session.sock], [], [], 0.0)
        while r:
            msg_id, payload = session.read_message()
            if msg_id == 6 and payload is not None:
                uploaded = session.serve_request(storage, payload)
                if uploaded > 0 and progress is not None:
                    peer_id = f"{session.host}:{session.port}"
                    req_piece = int.from_bytes(payload[0:4], "big")
                    progress.update_upload(uploaded, peer_id, req_piece)
            elif msg_id == 4 and payload is not None and len(payload) >= 4:
                session.have_pieces.add(int.from_bytes(payload[0:4], "big"))
            elif msg_id == 1:
                session.peer_choking = False
            elif msg_id == 14:
                session.has_all = True
            r, _, _ = select.select([session.sock], [], [], 0.0)
    except Exception:
        pass

async def serve_idle_peer(session, storage, progress):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _serve_idle_sync, session, storage, progress)

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
            for piece_index in remaining:
                for _ in sessions:
                    queue.put_nowait(piece_index)
                    

async def peer_worker(storage, session, queue, length, total_length, content_pieces, progress, sessions=None):
    while True:
        try:
            piece_index = queue.get_nowait()
        except asyncio.QueueEmpty:
            if all(p is not None for p in content_pieces):
                return
            await serve_idle_peer(session, storage, progress)
            await asyncio.sleep(0.1)
            continue
        
        if content_pieces[piece_index] is not None:
            continue
        
        if not session.has_piece(piece_index):
            queue.put_nowait(piece_index)
            await serve_idle_peer(session, storage, progress)
            await asyncio.sleep(0.05)
            continue
        
        try:
            peer_id = f"{session.host}:{session.port}"
            progress.active_peers[peer_id] = piece_index
            loop = asyncio.get_event_loop()
            try:
                buffer = await loop.run_in_executor(
                    None, download_piece, storage, session, piece_index, length, total_length, progress.active_pieces, progress
                )
            finally:
                if progress.active_peers.get(peer_id) == piece_index:
                    del progress.active_peers[peer_id]
            
            if content_pieces[piece_index] is None:
                content_pieces[piece_index] = buffer
                storage.mark_completed(piece_index)
                progress.update(len(buffer))
                if sessions:
                    for s in sessions:
                        try:
                            s.send_have(piece_index)
                        except Exception:
                            pass
        except ChokedError:
            queue.put_nowait(piece_index)
            def wait_for_unchoke():
                while True:
                    msg_id, _ = session.read_message()
                    if msg_id == 1:
                        return
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, wait_for_unchoke),
                    timeout=30
                )
            except Exception:
                return
        except Exception as e:
            if content_pieces[piece_index] is None:
                queue.put_nowait(piece_index)
            return
        
async def progress_display(progress):
    while progress.completed_pieces < progress.piece_count:
        progress.display()
        await asyncio.sleep(0.3)

async def completion_monitor(content_pieces, sessions):
   
    while True:
        await asyncio.sleep(0.5)
        if all(p is not None for p in content_pieces):
            # All pieces confirmed downloaded — kill sockets so any blocked
            # read_exactly calls in executor threads raise OSError and exit.
            for session in sessions:
                try:
                    session.sock.close()
                except Exception:
                    pass
            return

class DownloadManager:
    def __init__(self, storage, info_hash, trackers, piece_count, length, total_length, torrent_name="Download", initial_peers=None):
        self.storage = storage
        self.info_hash = info_hash
        self.trackers = trackers
        self.piece_count = piece_count
        self.length = length
        self.total_length = total_length
        self.torrent_name = torrent_name
        self.all_peers = set(initial_peers or [])
        self.sessions = []
        self.content_pieces = [None] * piece_count

    async def download_all(self):
        queue = asyncio.Queue()
        progress = ProgressTracker(self.piece_count, self.length, self.total_length, self.torrent_name)
        for i in range(self.piece_count):
            queue.put_nowait(i)

        display_task = asyncio.create_task(progress_display(progress))
        endgame_task = asyncio.create_task(endgame_checker(self.content_pieces, queue, self.sessions, self.piece_count))
        monitor_task = asyncio.create_task(completion_monitor(self.content_pieces, self.sessions))
        
        peer_workers = set()
        connected_addrs = set()
        loop = asyncio.get_running_loop()
        
        tracker_executor = ThreadPoolExecutor(max_workers=max(30, len(self.trackers) + 5), thread_name_prefix="tracker")
        conn_executor = ThreadPoolExecutor(max_workers=100, thread_name_prefix="conn")
        
        async def tracker_worker(t):
            try:
                peers = await loop.run_in_executor(
                    tracker_executor, lambda: find_peers_auto(t, self.info_hash, left=self.total_length)
                )
                for p in peers:
                    if p not in connected_addrs:
                        self.all_peers.add(p)
            except Exception:
                pass
                
        async def tracker_discovery():
            tasks = [asyncio.create_task(tracker_worker(t)) for t in self.trackers]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        async def connection_worker():
            pending_connections = set()
            while not all(p is not None for p in self.content_pieces):
                unconnected = [p for p in list(self.all_peers) if p not in connected_addrs and p not in pending_connections]
                for p_addr in unconnected:
                    pending_connections.add(p_addr)
                    
                    async def connect_and_spawn(addr):
                        try:
                            session = await loop.run_in_executor(conn_executor, try_connect, addr, self.info_hash, self.storage)
                            self.sessions.append(session)
                            connected_addrs.add(addr)
                            worker_task = asyncio.create_task(
                                peer_worker(self.storage, session, queue, self.length, self.total_length, self.content_pieces, progress, self.sessions)
                            )
                            peer_workers.add(worker_task)
                            worker_task.add_done_callback(peer_workers.discard)
                        except Exception:
                            pass
                        finally:
                            pending_connections.discard(addr)
                            
                    asyncio.create_task(connect_and_spawn(p_addr))
                await asyncio.sleep(0.5)

        discovery_task = asyncio.create_task(tracker_discovery())
        conn_task = asyncio.create_task(connection_worker())
        
        await monitor_task
        
        discovery_task.cancel()
        conn_task.cancel()
        endgame_task.cancel()
        display_task.cancel()
        for w in list(peer_workers):
            w.cancel()
            
        tracker_executor.shutdown(wait=False)
        conn_executor.shutdown(wait=False)
        
        try:
            await display_task
        except asyncio.CancelledError:
            pass
            
        progress.active_pieces.clear()
        progress.display()
        self.storage.flush_all()
        return 1

async def download_all(storage, sessions, piece_count, length, total_length, file_name="Download"):
    # Legacy wrapper if needed by external scripts
    return 1

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
        
        piece_count = math.ceil(total_length / length)
        if len(files) > 1:
            download_dir = download_path
        else:
            download_dir = os.path.dirname(download_path) if os.path.dirname(download_path) else "."
        print(f"there are {len(files)} files in total and total length is {total_length}")
        print(f"the info hash is {info_hash}")
        print(f"there will be total {piece_count} pieces and each piece is {length}")
        print(f"saving to directory: {download_dir}")
        storage = TorrentStorage(download_dir, files, length)
        
        torrent_name = content[b"info"].get(b"name", b"").decode("utf-8", "replace")
        if not torrent_name:
            torrent_name = os.path.basename(file)

        manager = DownloadManager(storage, info_hash, trackers, piece_count, length, total_length, torrent_name)
        val = await manager.download_all()

        print("\nVERIFYING SHA1 HASHES...")
        pieces_hash = content[b"info"][b"pieces"]
        failed = []
        for i in range(piece_count):
            expected = pieces_hash[i * 20 : (i + 1) * 20]
            if i == piece_count - 1:
                piece_size = total_length - (i * length)
            else:
                piece_size = length
            data = storage.read_block(i, 0, piece_size)
            actual = hashlib.sha1(data).digest()
            if actual != expected:
                failed.append(i)
        if failed:
            print(f"SHA1 VERIFICATION FAILED FOR {len(failed)} PIECE(S): {failed}")
        else:
            print(f"SHA1 VERIFICATION PASSED - ALL {piece_count} PIECES OK")
        print("DOWNLOAD COMPLETED")
        print(f"SAVED IN {os.path.abspath(download_dir)}")
        storage.close_all()

    elif command == "magnet_download":
        ### this is unusuable at the moment, will fix it later!
        download_path = sys.argv[2]
        magnet_link = sys.argv[3]
        info_hash, trackers = parse_magnet_link(magnet_link)
        info_hash = bytes.fromhex(info_hash)
        
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
                        """tracker failed"""
                        # print(f"tracker {t} failed: {e}")
            except TimeoutError:
                """tracker timeout"""
                # print(f"tracker discovery timed out, continuing with {len(all_peers)} peers found")
        all_peers = list(all_peers)
        # print(f"found {len(all_peers)} unique peers from {len(trackers)} trackers")
        
        if not all_peers:
            raise Exception("Could not find any peers from the provided magnet trackers.")
            
        info = None
        def fetch_metadata_from_peer(p_addr):
            HOST, PORT = p_addr.split(":")
            peer = socket.create_connection((HOST, int(PORT)), timeout=5)
            tcp_handshake(sock=peer, info_hash=info_hash, type="magnet")
            peer_metadata_id, metadata_size = extension_handshake(peer)
            
            if metadata_size <= 0:
                peer.close()
                raise Exception("no metadata")

            piece_count = math.ceil(metadata_size / 16384)
            metadata_pieces = [None] * piece_count

            for piece in range(piece_count):
                request_payload = bencodepy.encode({b"msg_type": 0, b"piece": piece})
                request_msg = (len(request_payload) + 2).to_bytes(4, "big") + (20).to_bytes(1, "big") + int(peer_metadata_id).to_bytes(1, "big") + request_payload
                peer.send(request_msg)
                
                while True:
                    length_prefix = read_exactly(peer, 4)
                    message_length = int.from_bytes(length_prefix, "big")
                    message_body = read_exactly(peer, message_length)
                    if message_body[0] == 20:
                        payload = message_body[2:]
                        response_dict = bencodepy.decode(payload)
                        dict_len = len(bencodepy.encode(response_dict))

                        if response_dict[b"msg_type"] == 2:
                            peer.close()
                            raise Exception("rejected")
                        
                        if response_dict[b"msg_type"] == 1:
                            raw_piece = payload[dict_len:]
                            metadata_pieces[piece] = raw_piece
                            break

            peer.close()
            full_metadata = b"".join(metadata_pieces)
            info_dict = bencodepy.decode(full_metadata)
            return info_dict

        # print("Fetching metadata from peers in parallel...")
        with ThreadPoolExecutor(max_workers=250) as executor:
            futures = {executor.submit(fetch_metadata_from_peer, p): p for p in all_peers}
            for future in as_completed(futures):
                try:
                    info = future.result()
                    # print(f"Successfully fetched metadata!")
                    break
                except Exception:
                    pass
                    
        if not info:
            raise Exception("Could not fetch metadata from any peer.")
            
        length = info[b"piece length"]
        files, total_length = parse_file_info(info)

        total_content = b""
        piece_count = math.ceil(total_length / length)
        if len(files) > 1:
            download_dir = download_path
        else:
            download_dir = os.path.dirname(download_path) if os.path.dirname(download_path) else "."
        print(f"there are {len(files)} files in total and total length is {total_length}")
        print(f"the info hash is {info_hash}")
        print(f"there will be total {piece_count} pieces and each piece is {length}")
        print(f"saving to directory: {download_dir}")
        storage = TorrentStorage(download_dir, files, length)
        
        torrent_name = info.get(b"name", b"").decode("utf-8", "replace")
        if not torrent_name:
            torrent_name = os.path.basename(download_path)

        manager = DownloadManager(storage, info_hash, trackers, piece_count, length, total_length, torrent_name, initial_peers=list(all_peers))
        val = await manager.download_all()

        print("\nVERIFYING SHA1 HASHES...")
        pieces_hash = info[b"pieces"]
        failed = []
        for i in range(piece_count):
            expected = pieces_hash[i * 20 : (i + 1) * 20]
            if i == piece_count - 1:
                piece_size = total_length - (i * length)
            else:
                piece_size = length
            data = storage.read_block(i, 0, piece_size)
            actual = hashlib.sha1(data).digest()
            if actual != expected:
                failed.append(i)
        if failed:
            print(f"SHA1 VERIFICATION FAILED FOR {len(failed)} PIECE(S): {failed}")
        else:
            print(f"SHA1 VERIFICATION PASSED - ALL {piece_count} PIECES OK")
        print("DOWNLOAD COMPLETED")
        print(f"SAVED IN {os.path.abspath(download_dir)}")
        storage.close_all()
    else:
        raise NotImplementedError(f"Unknown command {command}")
        
if __name__ == "__main__":
    asyncio.run(main())