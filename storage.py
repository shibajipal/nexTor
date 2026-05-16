import os
import threading

class TorrentStorage:
    def __init__(self, root, files, piece_length):
        
        self.root_path = root
        self.piece_length = piece_length
        self.lock = threading.Lock() #i think this somehow made it work!
        
        self.files = []
        self.completed = set()
        
        torrent_offset = 0
        for rel_path, length in files:
            full_path = os.path.join(self.root_path, rel_path)
            # create parent directory if it exists
            parent_dir = os.path.dirname(full_path)
            if parent_dir:  # only create if parent_dir is not empty
                os.makedirs(parent_dir, exist_ok=True)
            f = open(full_path, "w+b")
            f.truncate(length)
            self.files.append({"path": full_path,
                              "length": length,
                              "start": torrent_offset,
                              "end": torrent_offset + length,
                              "file": f})
            
            torrent_offset += length
        
        
    def calc_offset(self, piece_index, begin):
        return self.piece_length * piece_index + begin
    
    def write_block(self, piece_index, begin, data):
        offset = self.calc_offset(piece_index, begin)

        remaining = len(data)
        data_offset = 0
        with self.lock:
            for file_info in self.files:
                file_start = file_info["start"]
                file_end = file_info["end"]
                
                if offset >= file_end:
                    continue
                if remaining <= 0:
                    break
                
                #this might be enough for multi file
                overlap_start = max(offset, file_start)
                overlap_end = min(offset + remaining, file_end)
                
                bytes_to_write = overlap_end - overlap_start
                
                file_relative_offset = overlap_start - file_start
                
                chunk = data[data_offset : data_offset + bytes_to_write]
                f = file_info["file"]
                f.seek(file_relative_offset)
                f.write(chunk)
                f.flush()  # ensure data written to disk
                
                # updating da offset and remaining for next file
                offset += bytes_to_write
                remaining -= bytes_to_write
                data_offset += bytes_to_write
            
    def read_block(self, piece_index, begin, length):
        offset = self.calc_offset(piece_index, begin)
        remaining = length
        result = b""
        
        with self.lock:
            for file_info in self.files:
                file_start = file_info["start"]
                file_end = file_info["end"]
                if offset >= file_end:
                    continue
                if remaining <= 0:
                    break
                
                overlap_start = max(offset, file_start)
                overlap_end = min(offset + remaining, file_end)
                
                bytes_to_read = overlap_end - overlap_start
                file_relative_offset = overlap_start - file_start
                f = file_info["file"]
                f.seek(file_relative_offset)
                result += f.read(bytes_to_read)
                
                
                offset += bytes_to_read
                remaining -= bytes_to_read
        return result
    
    def mark_completed(self, piece_index):
        self.completed.add(piece_index)
    
    def flush_all(self):
        """Flush all file buffers to disk."""
        for file_info in self.files:
            file_info["file"].flush()
    
    def close_all(self):
        """Close all file handles."""
        for file_info in self.files:
            file_info["file"].close()