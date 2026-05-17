#torrent.py
#i put all the helper functions related to parsing torrent file and magent link metadata here

import bencodepy
import hashlib
import pathlib
import os
from urllib.parse import unquote


def parse_torrent(file):
    # Strip trailing slashes/backslashes from user input
    file = file.rstrip('\\/')
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
    parts = magnet_link.split("&tr=")
    trackers = [unquote(t.split("&")[0]) for t in parts[1:]]
    return (info_hash, trackers)

def parse_file_info(info):
    if b"files" in info:
        files = []
        total_length = 0
        root_name = info[b"name"].decode()
        
        for f in info[b"files"]:
            path_parts = [p.decode() for p in f[b"path"]]
            full_path = os.path.join(root_name, *path_parts)
            file_length = f[b"length"]
            files.append((full_path, file_length))
            
            total_length += file_length
        return files, total_length
    
    else:
        name = info[b"name"].decode()
        length = info[b"length"]
        return [(name, length)], length