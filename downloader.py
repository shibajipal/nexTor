# downloader.py
# this file has the helper functions to download each piece of a torrent or magnet file
from peer import read_exactly, tcp_handshake, PeerSession
MAX_IN_FLIGHT = 5
def download_piece(peer, piece_index, length, total_length):
    print("downloading piece", piece_index)
    
    buffer = b""
    begin = 0
    block_length = 2 ** 14
    if (piece_index + 1) * length > total_length:
        remaining_length = total_length - piece_index * length
        piece_size = total_length - piece_index * length
    else:
        remaining_length = length
        piece_size = length
    
    
    blocks = []
    offset = 0
    while offset < piece_size:
        send_length = min(piece_size - offset, block_length)
        blocks.append((offset, send_length))
        offset += send_length
        
    in_flight = 0
    next_to_send = 0
    received = {}
    
    while next_to_send < len(blocks) and in_flight < MAX_IN_FLIGHT:
        begin, send_length = blocks[next_to_send]
        request = (13).to_bytes(4, "big") + (6).to_bytes(1, "big") + piece_index.to_bytes(4, "big") + begin.to_bytes(4, "big") + send_length.to_bytes(4, "big")
        peer.send(request)
        in_flight += 1
        next_to_send += 1
        
    received_count = 0
        
    while received_count < len(blocks):
        length_prefix = read_exactly(peer, 4)
        message_length = int.from_bytes(length_prefix, "big")
        message_body = read_exactly(peer, message_length)
    
        if message_body[0] == 7:
            block_begin = int.from_bytes(message_body[1:5], "big")
            block_offset = int.from_bytes(message_body[5:9], "big")
            
            block_data = message_body[9:]
            received[block_offset] = block_data
            received_count += 1
            in_flight -= 1
            if next_to_send < len(blocks):
                begin, send_length = blocks[next_to_send]
                request = ((13).to_bytes(4, "big") + (6).to_bytes(1, "big")  + piece_index.to_bytes(4, "big") + begin.to_bytes(4, "big") + send_length.to_bytes(4, "big"))
                peer.send(request)
                in_flight += 1
                next_to_send += 1
        else:
            # Non-piece message (have, keep-alive, etc.) — skip it
            print("skipping message type", message_body[0])
            continue
    buffer = b""
    for begin, _ in blocks:
        buffer += received[begin]
    print("downloading piece", piece_index,"done")
    return buffer

