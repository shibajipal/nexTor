# client.py
# this is the main file that is run, and both downloading torrent and magnet files is supported
# usage:-  python client.py download_torrent <path> <torrent>
import sys
import socket
import math
import bencodepy
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
    main()