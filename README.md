# nexTor

nexTor is a custom-built BitTorrent client that explores peer-to-peer file distribution from first principles. It is designed not merely as a downloader, but as a structured and deliberate implementation of the BitTorrent protocol stack, focusing on clarity, correctness, and an understanding of how decentralized systems coordinate data exchange.

The client currently supports **single-file torrents** and **single-file magnet links**. It implements core aspects of peer discovery and communication using **BEP 3 (BitTorrent Protocol Specification)** and **BEP 23 (Compact Peer Lists)**, allowing it to participate in real BitTorrent swarms while maintaining a minimal and focused scope.

---

## Installation

* Clone the repository

   `git clone https://github.com/your-username/nexTor.git`

* Navigate into the project directory

   `cd nexTor`

* Run the client

   `py client.py download_torrent <path to where you want to save> <path to your torrent file>`
  
   or
  
   `py client.py download_magnet <path to where you want to save> <magnet link>`

---

## Core Principles

The workflow of nexTor follows the fundamental lifecycle of a BitTorrent download, broken into clearly defined stages:

---

### 1) Metadata Extraction

* The process begins by parsing either:
  → a `.torrent` file
  → or a magnet link

* For a **torrent file**:
  → The file is **bencoded**, a compact serialization format used throughout BitTorrent
  → It is decoded to extract:

  * `announce` (tracker URL)
  * `info` dictionary (file metadata)
  * `piece length`, `pieces`, and total file length

  → The **info hash** is computed by:

  * Re-encoding the `info` dictionary using bencoding
  * Applying SHA-1 hashing to it

* For a **magnet link**:
  → No file metadata is directly available
  → The client extracts:

  * `info_hash`
  * `tracker URL` (if present)

  → Metadata will later be fetched from peers using the info hash

---

### 2) Peer Discovery via Tracker

* Using the extracted information, nexTor contacts the tracker to obtain a list of peers.

* The request payload typically follows:

```
payload = {
  "info_hash": <calculated info hash>,
  "peer_id": <peer ID of the client>,
  "port": <port of the client>,
  "uploaded": <default: 0, uploaded size>,
  "downloaded": <default: 0, downloaded size>,
  "left": <default: 2^31 - 1, how much is left>,
  "compact": <default: 1, signifies BEP 3 / BEP 23>
}
```

* Key ideas:
  → `info_hash` uniquely identifies the torrent
  → `peer_id` identifies the client instance
  → `left` indicates remaining bytes to download
  → `compact=1` requests a compact peer list (BEP 23)

* The tracker response is also **bencoded**, requiring decoding.

* Peer list formats:

  → **BEP 3 (Standard format)**

  * Peers are returned as a list of dictionaries
  * Each entry contains:

    * IP address
    * Port

  → **BEP 23 (Compact format)**

  * Peers are returned as a binary string
  * Each peer occupies 6 bytes:

    * First 4 bytes → IP address
    * Last 2 bytes → Port

* nexTor parses both formats to construct a usable list of peers.

---

### 3) Establishing Connection

* For each discovered peer:

  → A **TCP socket connection** is created using the peer’s IP and port

* The first step is the **BitTorrent handshake**, which is distinct from the TCP handshake:

  → **TCP handshake**

  * Standard 3-step process:

    * SYN
    * SYN-ACK
    * ACK
  * Establishes a reliable connection

  → **BitTorrent handshake**

  * Sent immediately after TCP connection
  * Structure includes:

    * Protocol string (`BitTorrent protocol`)
    * Reserved bytes
    * `info_hash`
    * `peer_id`

* Purpose:
  → Verifies that both peers are participating in the same torrent
  → Establishes identity and compatibility

* For **magnet links**:
  → After handshake, metadata exchange may be required
  → This typically uses extension protocols to retrieve torrent metadata

---

### 4) Peer Communication

Once the handshake is complete, structured message exchange begins.

* Initial state:

  → Peer sends a **bitfield message**

  * A bitmap indicating which pieces the peer possesses

* nexTor responds:

  → Sends an **interested message**

  * Indicates willingness to download pieces

* Peer behavior:

  → If the peer allows data transfer:

  * It sends an **unchoke message**
  * This grants permission to request pieces

* Data transfer:

  → nexTor sends **request messages** specifying:

  * Piece index
  * Offset within the piece
  * Block length

  → Peer responds with **piece messages** containing actual data

* Flow control:

  → Communication is strictly message-based
  → Each message follows a length-prefixed binary format
  → Proper sequencing is required to maintain state consistency

---

### 5) Piece Assembly and Completion

* Downloaded data arrives in **blocks**, which are parts of pieces.

* nexTor:

  → Assembles blocks into complete pieces
  → Verifies each piece using SHA-1 hash comparison

* Once all pieces are verified:

  → They are written sequentially to reconstruct the final file

* Completion condition:

  → All pieces successfully downloaded and validated

---


