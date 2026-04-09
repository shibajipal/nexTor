#torrent.py
#i put all the helper functions related to parsing torrent file and magent link metadata here

import bencodepy
import hashlib
import pathlib
import os
from urllib.parse import unquote


def parse_torrent(file):
    local_file_path = pathlib.Path(os.getcwd(), file)
    if local_file_path:
        # print("file found!")
        with open(local_file_path, "rb") as f:
            content = f.read()
            
            content = bencodepy.decode(content)
            return content


def calculate_info_hash(content):
    info_hash = hashlib.sha1(bencodepy.encode(content[b"info"])).digest()
    return info_hash


def parse_magnet_link(magnet_link):
    info_hash = magnet_link[20:60]
    # print(magnet_link.split("&tr="))
    tracker = magnet_link.split("&tr=")[-1]
    tracker = unquote(tracker)
    return (info_hash, tracker)