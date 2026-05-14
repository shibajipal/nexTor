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
from parser import calculate_info_hash, parse_magnet_link, parse_torrent, parse_file_info
from peer import read_exactly, tcp_handshake, extension_handshake, find_peers, PeerSession, find_peers_auto
from concurrent.futures import ThreadPoolExecutor, as_completed


class ProgressTracker:
    def __init__(self, piece_count, piece_length, total_length):
        self.piece_count = piece_count
        self.piece_length = piece_length
        self.total_length = total_length
        self.completed_pieces = 0
        self.bytes_downloaded = 0
        self.start_time = time.time()
    
    def update(self, piece_bytes):
        self.completed_pieces += 1
        self.bytes_downloaded += piece_bytes
    
    def display(self):
        elapsed = time.time() - self.start_time
        downloaded = self.bytes_downloaded
        percent = downloaded / self.total_length if self.total_length > 0 else 0
        
        speed = downloaded / elapsed if elapsed > 0 else 0
        remaining = self.total_length - downloaded
        eta = remaining / speed if speed > 0 else 0
        
        # format sizes
        if self.total_length >= 1024 * 1024 * 1024:
            dl_str = f"{downloaded / (1024**3):.2f}"
            total_str = f"{self.total_length / (1024**3):.2f} GB"
        elif self.total_length >= 1024 * 1024:
            dl_str = f"{downloaded / (1024**2):.1f}"
            total_str = f"{self.total_length / (1024**2):.1f} MB"
        else:
            dl_str = f"{downloaded / 1024:.0f}"
            total_str = f"{self.total_length / 1024:.0f} KB"
        
        # format speed
        if speed >= 1024 * 1024:
            speed_str = f"{speed / (1024**2):.1f} MB/s"
        else:
            speed_str = f"{speed / 1024:.1f} KB/s"
        
        # format ETA
        eta_min, eta_sec = divmod(int(eta), 60)
        eta_hr, eta_min = divmod(eta_min, 60)
        if eta_hr > 0:
            eta_str = f"{eta_hr}h{eta_min:02d}m"
        elif eta_min > 0:
            eta_str = f"{eta_min}m{eta_sec:02d}s"
        else:
            eta_str = f"{eta_sec}s"
        
        # draw bar
        bar_width = 30
        filled = int(bar_width * percent)
        bar = "█" * filled + "░" * (bar_width - filled)
        
        line = f"\r  [{bar}] {percent*100:5.1f}%  {dl_str}/{total_str}  {speed_str}  ETA {eta_str}  [{self.completed_pieces}/{self.piece_count} pieces]  "
        sys.stdout.write(line)
        sys.stdout.flush()


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
            for piece_index in remaining:
                for _ in sessions:
                    queue.put_nowait(piece_index)
                    

async def peer_worker(session, queue, length, total_length, content_pieces, progress, endgame_threshold=5):
    while True:
        try:
            piece_index = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        
        
        if content_pieces[piece_index] is not None:
            continue
        
        if not session.has_piece(piece_index):
            queue.put_nowait(piece_index)
            await asyncio.sleep(0)
            continue
        
        try:
            loop = asyncio.get_event_loop()
            buffer = await loop.run_in_executor(None, download_piece, session.sock, piece_index, length, total_length)
            
            
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
            print(f"\npeer {session.host} failed: {e}")
            return
        
async def progress_display(progress, content_pieces):
    while progress.completed_pieces < progress.piece_count:
        progress.display()
        await asyncio.sleep(0.5)
        # also exit if all pieces are actually done (endgame dedup can mismatch counter)
        if all(p is not None for p in content_pieces):
            break
    progress.display()
    print()  # newline after bar completes

async def download_all(sessions, piece_count, length, total_length):
    content_pieces = [None] * piece_count
    queue = asyncio.Queue()
    progress = ProgressTracker(piece_count, length, total_length)
    for i in range(piece_count):
        queue.put_nowait(i)
    
    display_task = asyncio.create_task(progress_display(progress, content_pieces))
    endgame_task = asyncio.create_task(endgame_checker(content_pieces, queue, sessions, piece_count))
    tasks = [peer_worker(session, queue, length, total_length, content_pieces, progress) for session in sessions]
    await asyncio.gather(*tasks)
    
    # workers are done — stop background tasks and do final display
    endgame_task.cancel()
    display_task.cancel()
    try:
        await display_task
    except asyncio.CancelledError:
        pass
    progress.display()
    print()  # final newline
    return b"".join(content_pieces)
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
        # for p in all_peers:
        #     HOST, PORT = p.split(":")
        #     session = PeerSession(HOST, int(PORT), info_hash)
        #     try:
        #         session.connect()
        #         sessions.append(session)
        #         print(f"connected to {p}")    
        #     except Exception as e:
        #         print(f"failed to connect to {p}: {e}")
        # if not sessions:
        #     print(f"failed to connect to any peer")
            
            
        total_content = b""
        piece_count = math.ceil(total_length / length)
        print(f"there are {files} files in total and total length is {total_length}")
        print(f"the info hash is {info_hash}")
        print(f"there will be total {piece_count} pieces and each piece is {math.ceil(total_length / piece_count)}")
        

        total_content = await download_all(sessions, piece_count, length, total_length)
        # for i in content_pieces:
        #     total_content += i
        
        if len(files) == 1:
            with open(download_path, "wb") as f:
                f.write(total_content)
        else:
            offset = 0
            for file_path, file_length in files:
                output_path = os.path.join(download_path, file_path)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                file_data = total_content[offset : offset + file_length]
                with open(output_path, "wb") as f:
                    f.write(file_data)
                    
                print(f"written: {file_path} ({file_length}) bytes")
                offset += file_length
            
            
    elif command == "magnet_download":
        download_path = sys.argv[2]
        magnet_link = sys.argv[3]
        info_hash, tracker = parse_magnet_link(magnet_link)
        info_hash = bytes.fromhex(info_hash)
        all_peers = find_peers(tracker=tracker, info_hash=info_hash, left=10)
        p = all_peers[0]
        HOST, PORT = p.split(":")
        peer = socket.create_connection((HOST, PORT))

        received_peer_id = tcp_handshake(sock=peer, info_hash=info_hash, type="magnet")
        peer_metadata_id = extension_handshake(peer)
        
        # request metadata piece (msg_type=0 means request, piece=0)
        request_payload = bencodepy.encode({b"msg_type": 0, b"piece": 0})
        request_msg = (len(request_payload) + 2).to_bytes(4, "big") + (20).to_bytes(1, "big") + int(peer_metadata_id).to_bytes(1, "big") + request_payload
        peer.send(request_msg)
        
        # receive metadata piece response
        while True:
            length_prefix = read_exactly(peer, 4)
            message_length = int.from_bytes(length_prefix, "big")
            message_body = read_exactly(peer, message_length)
            if message_body[0] == 20:
                payload = message_body[2:]
                # response is: bencoded dict + raw info dict bytes
                # find end of bencoded dict by decoding it
                dict_end = payload.index(b"ee") + 2
                raw_info = payload[dict_end:]
                info = bencodepy.decode(raw_info)
                break
        total_length = info[b"length"]
        piece_length = info[b"piece length"]

        interested_message = (1).to_bytes(4, "big") + (2).to_bytes(1, "big")
        print("interested message", interested_message)
        peer.send(interested_message)
        while True:
            length_prefix = read_exactly(peer, 4)
            message_length = int.from_bytes(length_prefix, "big")
            unchoke_body = read_exactly(peer, message_length)
            print("unchoke body", unchoke_body)
            if unchoke_body[0] == 1:
                break
        
        total_content = b""
        for piece_index in range(0, math.ceil(total_length / piece_length)):
            buffer = download_piece(peer, piece_index, piece_length, total_length)
            total_content += buffer
            print("total content", len(total_content))
        with open(download_path, "wb") as f:
            f.write(total_content)
    else:
        raise NotImplementedError(f"Unknown command {command}")
        
if __name__ == "__main__":
    asyncio.run(main())