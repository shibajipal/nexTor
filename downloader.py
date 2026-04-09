# downloader.py
# this file has the helper functions to download each piece of a torrent or magnet file
from peer import read_exactly

def download_piece(peer, piece_index, length, total_length):
    print("downloading piece", piece_index)
    buffer = b""
    begin = 0
    block_length = 2 ** 14
    if (piece_index + 1) * length > total_length:
        remaining_length = total_length - piece_index * length
    else:
        remaining_length = length
    
    while remaining_length > 0:
        print("rem length", remaining_length)
        send_length = min(remaining_length, block_length)
        request = (13).to_bytes(4, "big") + (6).to_bytes(1, "big") + piece_index.to_bytes(4, "big") + begin.to_bytes(4, "big") + send_length.to_bytes(4, "big")
        peer.send(request)
        
        # Keep reading messages until we get the piece response
        while True:
            length_prefix = read_exactly(peer, 4)
            message_length = int.from_bytes(length_prefix, "big")
            
            message_body = read_exactly(peer, message_length)
            if message_body[0] == 7:
                block_data = message_body[9:]
                buffer += block_data
                remaining_length -= send_length
                begin += block_length
                break
            else:
                # Non-piece message (have, keep-alive, etc.) — skip it
                print("skipping message type", message_body[0])
                continue
    print("downloading piece", piece_index,"done")
    return buffer

