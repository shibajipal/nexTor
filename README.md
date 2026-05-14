<div align="center">

# nexTor

### A BitTorrent client built from scratch in Python.

*No libraries. No shortcuts. Just raw sockets, binary protocols, and peer-to-peer networking, the way it was meant to be understood.*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Protocol](https://img.shields.io/badge/Protocol-BitTorrent-orange?style=for-the-badge)](https://www.bittorrent.org/beps/bep_0003.html)

---

<img width="700" alt="terminal demo" src="https://github.com/user-attachments/assets/placeholder">

</div>

<br>

## What is nexTor?

**nexTor** is a from-scratch BitTorrent client that implements the core protocol stack using nothing but Python's standard library and raw TCP/UDP sockets. It's not a wrapper around `libtorrent`. Every handshake, every binary message, every piece assembly is written by hand.

The goal isn't to replace qBittorrent. It's to **understand** how decentralized file distribution actually works at the byte level.

<br>

## Features

| Feature | Details |
|---|---|
| **Single & Multi-File Torrents** | Downloads single files or reconstructs complex directory trees from multi-file torrents |
| **Magnet Link Support** | Fetches torrent metadata directly from peers using the extension protocol (BEP 10) |
| **HTTP + UDP Trackers** | Discovers peers from both HTTP (BEP 3) and UDP (BEP 15) tracker protocols |
| **Multi-Tracker Discovery** | Queries every tracker in the `announce-list` in parallel for maximum peer coverage |
| **Async Concurrent Downloads** | Distributes pieces across all connected peers simultaneously using `asyncio` |
| **Request Pipelining** | Keeps 5 block requests in-flight per peer to saturate bandwidth (no stop-and-wait) |
| **Endgame Mode** | When few pieces remain, broadcasts them to all peers to eliminate tail latency |
| **Live Progress Bar** | Real-time display with speed, ETA, percentage, and piece counter |
| **Parallel Peer Connections** | Connects to up to 250 peers simultaneously via thread pool |
| **Choke/Unchoke Handling** | Gracefully handles peer choking, re-queues pieces and waits for unchoke |
| **Bitfield Tracking** | Tracks which pieces each peer has for intelligent piece selection |
| **BEP 23 Compact Peers** | Parses both standard and compact (6-byte) peer list formats |

<br>

## Project Structure

```
nexTor/
├── client.py        # Main entry point, orchestrates the entire download lifecycle
├── peer.py          # Peer discovery, TCP/BT handshakes, PeerSession state machine
├── downloader.py    # Piece-level download engine with request pipelining
├── parser.py        # .torrent file & magnet link parsing, info hash computation
├── downloads/       # Default download output directory
└── README.md
```

<br>

## Getting Started

### Prerequisites

- **Python 3.10+**
- Install dependencies:

```bash
pip install bencodepy requests
```

### Installation

```bash
git clone https://github.com/shibajipal/nexTor.git
cd nexTor
```

### Usage

**Download from a `.torrent` file:**
```bash
python client.py download_torrent <save_path> <torrent_file>
```

**Download from a magnet link:**
```bash
python client.py magnet_download <save_path> "<magnet_link>"
```

> [!TIP]
> Wrap magnet links in quotes to prevent the shell from splitting on `&` characters.

#### Examples

```bash
# Single file torrent
python client.py download_torrent ./downloads/ubuntu.iso ubuntu-24.04.torrent

# Multi-file torrent (directory structure is auto-created)
python client.py download_torrent ./downloads/ archlinux-2024.torrent

# Magnet link
python client.py magnet_download ./downloads/file.iso "magnet:?xt=urn:btih:..."
```

<br>

## What It Looks Like

```
found 147 unique peers from 12 trackers
connected to 85.214.42.193:51413
connected to 192.168.1.45:6881
...
there are 1 files in total and total length is 4293652480
the info hash is b'\xa3\xf2...'
there will be total 16380 pieces and each piece is 262144

  [████████████████░░░░░░░░░░░░░░]  53.2%  2.1/4.0 GB  3.8 MB/s  ETA 8m42s  [8714/16380 pieces]
```

<br>

## How It Works: Protocol Deep Dive

### The Download Lifecycle

```
  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │  1. PARSE    │────▶│  2. DISCOVER │────▶│ 3. CONNECT   │────▶│ 4. DOWNLOAD  │────▶│ 5. ASSEMBLE  │
  │  Metadata    │     │  Peers       │     │  Handshake   │     │  Pieces      │     │  File(s)     │
  └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
   .torrent file       HTTP/UDP            TCP + BitTorrent     Async pipeline      SHA-1 verify
   or magnet link      tracker announce    handshake            with endgame        + write to disk
```

---

### 1 > Metadata Extraction

**From `.torrent` files:**
The file is [bencoded](https://wiki.theory.org/BitTorrentSpecification#Bencoding), a compact binary serialization format. nexTor decodes it to extract the tracker URL, piece length, piece SHA-1 hashes, and the file layout. The **info hash** is computed by re-encoding the `info` dictionary and applying SHA-1.

**From magnet links:**
Only the `info_hash` and tracker URL are available. The actual torrent metadata is fetched later from peers using the **Extension Protocol (BEP 10)**. nexTor sends an extension handshake, requests metadata pieces, and reconstructs the full `info` dictionary from the peer's response.

---

### 2 > Peer Discovery

nexTor contacts every tracker in the torrent's `announce-list` in parallel using a thread pool:

- **HTTP Trackers (BEP 3):** Standard GET request with the info hash, peer ID, and download stats. Response contains a bencoded peer list, either as a list of dictionaries or a compact binary string (BEP 23, 6 bytes per peer).

- **UDP Trackers (BEP 15):** A two-phase protocol. First a `connect` request to get a `connection_id`, then an `announce` request carrying the torrent metadata. The response contains a raw binary peer list.

All discovered peers are deduplicated into a single pool.

---

### 3 > Peer Handshake

For each peer, nexTor establishes a **TCP connection** and immediately sends the **BitTorrent handshake**:

```
[1 byte: 19] [19 bytes: "BitTorrent protocol"] [8 bytes: reserved] [20 bytes: info_hash] [20 bytes: peer_id]
```

After the handshake, the peer sends a **bitfield** message (a bitmap of which pieces it has), nexTor sends an **interested** message, and waits for the peer to **unchoke**, granting permission to request data.

For magnet links, the reserved bytes signal extension protocol support (`0x10` in byte 6), enabling the metadata exchange.

---

### 4 > Piece Download

This is where the performance engineering lives:

- **Async Workers:** Each connected peer gets its own `asyncio` coroutine pulling pieces from a shared queue.
- **Request Pipelining:** Instead of waiting for each block response before sending the next request, nexTor keeps **5 requests in-flight** simultaneously per peer, eliminating round-trip latency.
- **Choke Recovery:** If a peer chokes mid-download, the piece is re-queued for another peer, and the worker waits for an unchoke signal (with a 30-second timeout).
- **Endgame Mode:** When the number of remaining pieces drops below the active peer count, every remaining piece is broadcast to *all* peers. The first response wins; duplicates are discarded.

---

### 5 > File Assembly

Downloaded blocks are assembled into pieces, and pieces are concatenated into the final byte stream. For **multi-file torrents**, nexTor slices the stream at the correct byte offsets and writes each file to its proper path, auto-creating directories as needed.

<br>

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          client.py                                   │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ ProgressBar  │  │ EndgameMode  │  │ download_all()            │  │
│  │ (real-time)  │  │ (tail optim) │  │ async peer orchestration  │  │
│  └──────────────┘  └──────────────┘  └───────────────────────────┘  │
│                            │                       │                 │
│                            ▼                       ▼                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    peer_worker()                             │    │
│  │            one coroutine per connected peer                  │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
         │                    │                        │
         ▼                    ▼                        ▼
  ┌─────────────┐    ┌──────────────┐        ┌──────────────┐
  │  parser.py   │    │   peer.py    │        │ downloader.py│
  │              │    │              │        │              │
  │ .torrent     │    │ PeerSession  │        │ Pipelined    │
  │  parsing     │    │ HTTP tracker │        │ block I/O    │
  │ magnet links │    │ UDP tracker  │        │ choke handle │
  │ info hash    │    │ handshakes   │        │              │
  └─────────────┘    └──────────────┘        └──────────────┘
```

<br>

## Implemented BEPs

| BEP | Title | Status |
|-----|-------|--------|
| [BEP 3](https://www.bittorrent.org/beps/bep_0003.html) | The BitTorrent Protocol Specification | Implemented |
| [BEP 10](https://www.bittorrent.org/beps/bep_0010.html) | Extension Protocol | Implemented |
| [BEP 15](https://www.bittorrent.org/beps/bep_0015.html) | UDP Tracker Protocol | Implemented |
| [BEP 23](https://www.bittorrent.org/beps/bep_0023.html) | Compact Peer Lists | Implemented |

<br>

## Dependencies

| Package | Purpose |
|---------|---------|
| [`bencodepy`](https://pypi.org/project/bencodepy/) | Bencoding/decoding for torrent metadata and tracker responses |
| [`requests`](https://pypi.org/project/requests/) | HTTP tracker communication |

Everything else (TCP sockets, UDP datagrams, binary protocol parsing, async orchestration) is pure Python standard library.

<br>

## Roadmap

- [ ] DHT peer discovery (BEP 5), trackerless torrents
- [ ] Peer Exchange (PEX, BEP 11), discover peers from peers
- [ ] Seeding / upload support
- [ ] Piece SHA-1 verification with corrupt piece re-download
- [ ] Resume interrupted downloads
- [ ] TUI interface with per-peer stats

<br>

## License

This project is open source and available under the [MIT License](LICENSE).

<br>

<div align="center">

---

Built with raw sockets and curiosity.

**[shibajipal](https://github.com/shibajipal)**

</div>
