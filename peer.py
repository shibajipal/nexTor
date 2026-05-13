# peer.py
# this file consists of helper functions that help to find out the peer 



import bencodepy
import requests
import socket
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
    print(message)
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
    print(all_peers)
    
    return all_peers
















class PeerSession:

    def __init__(self, host, port, info_hash, peer_id = "a"*20):

        self.host = host
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.sock = None
        self.remote_peer_id = None                 
        self.bitfield = None
        self.is_choking = True
        self.is_interested = False
        self.peer_choking = True
        self.peer_interested = False
        
        
        
    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        
        self.remote_peer_id = tcp_handshake(sock=self.sock,
                                            info_hash=self.info_hash,
                                            peer_id=self.peer_id)
        self.bitfield_wait()
        self.interested_send()
        self.unchoke_wait()
        
        
        
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
        while True:
            msg_id, payload = self.read_message()
            if msg_id == 5:
                self.bitfield = payload
                break
            
            elif msg_id == 4:
                pass
            
    def interested_send(self):
        msg = (1).to_bytes(4, "big") + (2).to_bytes(1, "big")
        self.sock.send(msg)
        self.is_interested = True
        
    def unchoke_wait(self):
        while True:
            msg_id, payload = self.read_message()
            if msg_id == 1:
                self.peer_choking = False
                break
                