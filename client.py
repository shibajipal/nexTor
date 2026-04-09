# client.py
# this is the main file that is run, and both downloading torrent and magnet files is supported
# usage:-  python client.py download_torrent <path> <torrent>
import sys
import socket
import math
from downloader import download_piece
from parser import calculate_info_hash, parse_magnet_link, parse_torrent
from peer import read_exactly, tcp_handshake, extension_handshake, find_peers


def main():
    command = sys.argv[1]
    if command == "download_torrent":
        download_path = sys.argv[2]
        file = sys.argv[3]
        
        content = parse_torrent(file)
        tracker, total_length, length = content[b"announce"], content[b"info"][b"length"], content[b"info"][b"piece length"]
        
        info_hash = calculate_info_hash(content)
        all_peers = find_peers(tracker=tracker, info_hash=info_hash, left=length)
        p = all_peers[0]
        HOST, PORT = p.split(":")
        peer = socket.create_connection((HOST, PORT))
        print("handshake start")
        received_peer_id = tcp_handshake(sock=peer, info_hash=info_hash)
        print("successful handshake")
        while True:
            length_prefix = read_exactly(peer, 4) 
            message_length = int.from_bytes(length_prefix, "big")
            bitfield_body = read_exactly(peer, message_length)
            print("bitfield check", bitfield_body)
            if bitfield_body[0] == 5:
                break
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
        for piece_index in range(0, math.ceil(total_length / length)):
            buffer = download_piece(peer, piece_index, length, total_length)
            total_content += buffer
            print("total content", len(total_content))
        with open(download_path, "wb") as f:
            f.write(total_content)
        
if __name__ == "__main__":
    main()