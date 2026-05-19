# peer.py
# this file consists of helper functions that help to find out the peer 


import random
import struct
from urllib.parse import urlparse
import bencodepy
import requests
import socket

def find_udp_peers(tracker, info_hash, peer_id = "a"*20, port=6881, uploaded=0, downloaded=0, left=2**31-1):
    parsed = urlparse(tracker)
    HOST = parsed.hostname
    
    PORT = parsed.port or 6969
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    
    transaction_id = random.randint(0, 2**32-1)
    connect_request = struct.pack(">QII", 0x41727101980, 0, transaction_id)
    sock.sendto(connect_request, (HOST, PORT))
    response = sock.recv(16)
    action, response_transaction_id, connection_id = struct.unpack(">IIQ", response)
    
    
    transaction_id = random.randint(0, 2**32 - 1)
    announce_request = struct.pack(">QII", connection_id, 1, transaction_id)
    
    announce_request += info_hash
    announce_request += peer_id.encode()
    announce_request += struct.pack(">QQQ", downloaded, left, uploaded)
    announce_request += struct.pack(">IIIiH", 0, 0, random.randint(0, 2**32 - 1), -1, port)
    sock.sendto(announce_request, (HOST, PORT))
    response = sock.recv(4096)
    sock.close()
    
    action, resp_tid, interval, leechers, seeders = struct.unpack(">IIIII", response[:20])
    print(f"tracker: {tracker}, leechers: {leechers}, seeders: {seeders}")
    
    peer_data = response[20:]
    all_peers = []
    for i in range(0, len(peer_data), 6):
        ip = ".".join(str(b) for b in peer_data[i:i+4])
        
        port = struct.unpack(">H", peer_data[i+4:i+6])[0]
        all_peers.append(f"{ip}:{port}")
    # print(all_peers)
    return all_peers

def read_exactly(sock, n):
    data = b""
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            raise ConnectionError("Peer closed connection")
        data += packet
    return data


def tcp_handshake(sock,
                  info_hash,
                  peer_id="a"*20,
                  type="torrent"):
    if type == "magnet":
        reserved_bytes = b"\x00" * 5 + b"\x10" + b"\x00" * 2
    else:
        reserved_bytes = b"\x00" * 8
    message = (19).to_bytes(1, "big") + "BitTorrent protocol".encode() + reserved_bytes + info_hash + peer_id.encode()
    # print(message)
    sock.send(message)
    data = read_exactly(sock, 68)
    received_peer_id = data[48:68].hex()
    return received_peer_id



def extension_handshake(peer):
    # send extension handshake (msg_id=20, ext_id=0)
    ext_handshake_payload = bencodepy.encode({b"m": {b"ut_metadata": 1}})
    ext_message = (len(ext_handshake_payload) + 2).to_bytes(4, "big") + (20).to_bytes(1, "big") + (0).to_bytes(1, "big") + ext_handshake_payload
    peer.send(ext_message)
    
    # wait for peer's extension handshake response
    while True:
        length_prefix = read_exactly(peer, 4)
        message_length = int.from_bytes(length_prefix, "big")
        message_body = read_exactly(peer, message_length)
        if message_body[0] == 20 and message_body[1] == 0:
            peer_ext_handshake = bencodepy.decode(message_body[2:])
            peer_metadata_id = peer_ext_handshake[b"m"][b"ut_metadata"]
            break
    return peer_metadata_id

def find_peers(tracker,
               info_hash,
               peer_id="a"*20,
               port=6881,
               uploaded=0,
               downloaded=0,
               left=2 ** 31 - 1,
               compact=1):
    
    payload = {"info_hash": info_hash,
               "peer_id": peer_id,
               "port": port,
               "uploaded": uploaded,
               "downloaded": downloaded,
               "left": left,
               "compact": compact}
    
    r = requests.get(tracker, params=payload)
    
    data = bencodepy.decode(r.content)
    # print("data", data)
    # print(data)
    p = data[b"peers"]
    all_peers = []
    if isinstance(p, bytes):
        p = [i for i in p]
        for i in range(0, len(p), 6):
                ip = [str(p[x]) for x in range(i, i + 4)]
                ip = ".".join(ip)
                port_bytes = [p[i + 4], p[i + 5]]
                port_hex = "".join([f"{b:02x}" for b in port_bytes])
                port = int(port_hex, 16)
                final_peer = ip + ":" + str(port)
                all_peers.append(final_peer)
    elif isinstance(p, list):
        for i in p:
            all_peers.append(i[b'ip'].decode() + ":" + str(i[b'port']))
    # print(all_peers)
    
    return all_peers

def find_peers_auto(tracker, info_hash, **kwargs):
    tracker_str = tracker.decode() if isinstance(tracker, bytes) else tracker
    if tracker_str.startswith("udp://"):
        return find_udp_peers(tracker_str, info_hash, **kwargs)
    else:
        return find_peers(tracker, info_hash, **kwargs)














class PeerSession:

    def __init__(self, host, port, info_hash, peer_id = "a"*20, is_magnet=False):

        self.host = host
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.is_magnet = is_magnet
        self.sock = None
        self.remote_peer_id = None                 
        self.bitfield = None
        self.is_choking = True
        self.is_interested = False
        self.peer_choking = True
        self.peer_interested = False
        
        
        
    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        
        handshake_type = "magnet" if self.is_magnet else "torrent"
        self.remote_peer_id = tcp_handshake(sock=self.sock,
                                            info_hash=self.info_hash,
                                            peer_id=self.peer_id,
                                            type=handshake_type)
        self.bitfield_wait()
        self.interested_send()
        self.unchoke_wait()
        
        # use a longer timeout for data transfer (peers can be slow)
        self.sock.settimeout(120)
        
        
        
    def read_message(self):
        length_prefix = read_exactly(self.sock, 4)
        message_length = int.from_bytes(length_prefix, "big")
        if message_length == 0:
            return None, None
        message_body = read_exactly(self.sock, message_length)
        return message_body[0], message_body[1:]

    def has_piece(self, piece_index):
        if self.bitfield is None:
            return False
        
        byte_index = piece_index // 8
        bit_index = 7 - (piece_index % 8)
        
        if byte_index >= len(self.bitfield):
            return False
        return bool(self.bitfield[byte_index] & (1 << bit_index))


    def disconnect(self):
        if self.sock:
            self.sock.close()
            self.sock = None
        
    def bitfield_wait(self):
        # We wait for a short time for bitfield. If we get other messages like HAVE (4), UNCHOKE (1),
        # or EXTENSION (20), we process them but we might exit the bitfield loop if it's clear 
        # the bitfield phase is over.
        self.sock.settimeout(2.0)
        try:
            while True:
                msg_id, payload = self.read_message()
                if msg_id == 5:
                    self.bitfield = payload
                    break
                elif msg_id == 20:
                    if payload and payload[0] == 0:
                        peer_ext_handshake = bencodepy.decode(payload[1:])
                        if b"m" in peer_ext_handshake and b"ut_metadata" in peer_ext_handshake[b"m"]:
                            self.peer_metadata_id = peer_ext_handshake[b"m"][b"ut_metadata"]
                elif msg_id in (1, 4):
                    # Peer sent unchoke or have, meaning they skipped bitfield (likely no pieces)
                    break
        except socket.timeout:
            # Peer didn't send bitfield in time, probably has no pieces or is silent
            pass
        finally:
            self.sock.settimeout(10.0) # restore default timeout
            
    def interested_send(self):
        msg = (1).to_bytes(4, "big") + (2).to_bytes(1, "big")
        self.sock.send(msg)
        self.is_interested = True
        
    def unchoke_wait(self):
        # We don't block forever, just wait a bit for unchoke
        self.sock.settimeout(2.0)
        try:
            while True:
                msg_id, payload = self.read_message()
                if msg_id == 1:
                    self.peer_choking = False
                    break
                elif msg_id == 20:
                    if payload and payload[0] == 0:
                        peer_ext_handshake = bencodepy.decode(payload[1:])
                        if b"m" in peer_ext_handshake and b"ut_metadata" in peer_ext_handshake[b"m"]:
                            self.peer_metadata_id = peer_ext_handshake[b"m"][b"ut_metadata"]
        except socket.timeout:
            pass
        finally:
            self.sock.settimeout(120.0)
                