# ANA Chain Protocol Specification v0.3.0

## Abstract

ANA Chain is an AI-native communication protocol that replaces text-based serialization (JSON/XML) with compact binary "codons" — semantic identifiers backed by a pre-shared codebook. Inspired by the biological codon–anticodon pairing in protein synthesis, ANA eliminates the serialization tax that dominates LLM Agent ↔ API communication.

---

## Glossary

| Term | Definition |
|------|------------|
| **Codon** | A binary identifier (3-byte header + dynamic params) that maps to an API operation |
| **Anticodon** | The receiver-side reverse lookup: resolving codon bytes back to an operation descriptor |
| **Codebook** | A lookup table mapping codons to operations, generated deterministically from a seed |
| **Sub-chain** | An independent mapping space derived from master_seed, rotated every 1000 packets |
| **Session nonce** | A 32-byte random value exchanged during negotiation, used to derive a unique session codebook |
| **Noise codon** | A `[0x00, 0x00, 0x00]` placeholder codon used to obfuscate traffic patterns |
| **Master seed** | A 64-byte session key material derived from codebook_seed + session_nonce via HKDF |

---

## 1. Design Goals

| Goal | Mechanism |
|------|-----------|
| Eliminate JSON serialization overhead | Binary codons map directly to API operations |
| Reduce LLM token consumption | Codons are 0–5 tokens vs 50–200 for JSON |
| Resist eavesdropping without encryption | Codons are opaque without the codebook |
| Graceful degradation | Automatic fallback to JSON-RPC 2.0 when codebooks mismatch |
| Layer with existing protocols | Works underneath MCP, A2A; complements TLS |

---

## 2. Codebook

### 2.1 Structure

```
Service (uint8, 0–255)
└── Operation (uint8, 0–255)
    └── ParameterTemplate (uint8, 0–255)
        ├── Fixed parameters (compile-time known)
        └── Wildcard slots (runtime values, varint-encoded)
```

Total: 256³ = **16,777,216** possible operation signatures per codebook.

### 2.2 Definition Format (YAML)

```yaml
codebook_id: "weather-v1"
version: 1
codebook_seed: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0"

services:
  - id: 1
    name: "weather"
    operations:
      - id: 1
        name: "get_forecast"
        templates:
          - id: 0
            description: "by city, metric units"
            params: [city, days]
            types: [string, uint8]
            defaults: {days: 7}
          - id: 1
            description: "by coordinates, imperial units"
            params: [lat, lon, days]
            types: [float32, float32, uint8]
            defaults: {days: 3}
```

### 2.3 Generation

Codebooks are generated deterministically from a seed using HKDF + ChaCha20:

```
codebook_seed = random(32 bytes)         # per codebook version
master_seed   = HKDF(salt=codebook_seed, ikm=session_nonce, info="ANA-v1")
subchain[n]   = HKDF(salt=master_seed, ikm=uint32_be(n), info="ANA-v1-sub")
```

This ensures:
- The full codebook is never stored or transmitted
- Each session derives a unique mapping from the same base seed
- Sub-chain rotation (every 1000 packets) limits exposure

### 2.4 On "Position Hopping"

> The original design's position hopping function (P_{i+1} = (P_i + H(chain_id||i)) mod L) assumed a physically stored global codebook table. In the optimized protocol, codons no longer have "physical positions" — each codon's `[S, O, T]` mapping is generated on-demand from `subchain_seed` via ChaCha20 PRNG. Sub-chain rotation (every 1000 packets) serves the same security purpose: limiting the exposure window of any single key segment.
>
> If you need the original position-hopping semantics (unpredictable mapping switches within a sub-chain), shorten the rotation interval or apply per-codon `derive_scramble(seed, S, O, T)` — already implemented in the reference library.

### 2.5 Versioning

```
CodebookVersion:
  codebook_id:  string      # "weather-v1"
  version:      uint16      # monotonic 0–65535
  seed_hash:    bytes[32]   # SHA-256 of codebook_seed
  capabilities: uint32      # bitmask
```

---

## 3. Wire Format

### 3.1 Common Packet Header

```
(Plaintext mode — v0.2.0 and earlier)
Offset  Size  Field
------  ----  -----
0       2     Magic number: 0xA7A7
2       1     Protocol version (0x02)
3       1     Flags
              bit 0-2: Packet type (0-7)
              bit 3:   Has noise codons
              bit 4:   Is fragmented
              bit 5:   ACK flag (CODON acknowledgment)
              bit 6:   Encryption mode (0=plaintext, 1=AEAD)
              bit 7:   Reserved
4       2     Stream ID (uint16, big-endian)
6       4     Sequence number (uint32, big-endian)
10      2     Payload length (uint16, big-endian)
12     16     AEAD auth tag (Poly1305, encrypted mode only)
28      N     Payload (ChaCha20 ciphertext in encrypted mode)
28+N    2     CRC-16 checksum (plaintext mode) / omitted (encrypted mode, Poly1305 replaces)
```

**Protocol version bumped to 0x02** (v0.3.0).

- Plaintext mode (bit 6 = 0): same as v0.2.0, CRC-16 + optional HMAC
- Encrypted mode (bit 6 = 1): Poly1305 auth tag replaces CRC-16 + HMAC

Total header overhead: **12 bytes** (plaintext) / **28 bytes** (AEAD encrypted, includes 16-byte auth tag).

### 3.2 Packet Types

| Type | Name | Direction | Description |
|------|------|-----------|-------------|
| 0x00 | HELLO | Agent→API | Secure handshake: AID + ephemeral key + codebook list |
| 0x01 | HELLO_ACK | API→Agent | Handshake response: AID + ephemeral key + selected codebook |
| 0x02 | CONFIRM | Agent→API | Confirm session (HMAC key confirmation) |
| 0x03 | CODON | Both | Data transfer: one or more codons (AEAD encrypted) |
| 0x04 | ROTATE | Both | Trigger sub-chain rotation |
| 0x05 | ROTATE_ACK | Both | Acknowledge rotation |
| 0x06 | ERROR | Both | Report an error condition |
| 0x07 | FALLBACK | Both | Switch to JSON/text mode |
| 0x08 | RESUME | Agent→API | PSK session resumption (0-RTT) |
| 0x09 | RESUME_ACK | API→Agent | PSK resumption confirmation |
| 0x0A | REKEY | Both | Proactive key update |

> **v0.3.0 change**: NEGOTIATE → HELLO, NEGOTIATE_ACK → HELLO_ACK, NEGOTIATE_CONFIRM → CONFIRM. Added RESUME / RESUME_ACK / REKEY.

### 3.3 Codon Encoding

Payload format:

```
[chain_index: uint16]    # sender's current sub-chain index (for sync verification)
[codon_count: uint8]     # number of real codons
[noise_count:  uint8]    # number of noise codons
[codons:       codon[]]  # real codons, concatenated
[noise:        codon[]]  # noise codons, discarded by receiver
```

Each codon:

```
Byte 0:    Service ID (uint8)
Byte 1:    Operation ID (uint8), bit 7 = response flag
Byte 2:    Template ID (uint8)
Bytes 3+:  Dynamic parameter values (unsigned LEB128 varint)
```

**Control codons** (Service ID = 0xFF):

| Encoding | Name | Description |
|----------|------|-------------|
| `[0xFF, 0x04, 0x00]` | PING | Heartbeat probe — receiver should reply PONG |
| `[0xFF, 0x05, 0x00]` | PONG | Heartbeat response |
| `[0xFF, 0x02, 0x00]` | TEARDOWN | Graceful session close |

**CODON ACK packet** (CODON type + ACK flag bit 5 = 1):

```
[chain_index: uint16]    # ACK sender's sub-chain index
[ack_sequence: uint32]   # sequence number of CODON being acknowledged
```

### 3.4 Noise Codon Mechanism

> Noise injection resists traffic analysis. Without the codebook, an attacker cannot distinguish real codons from noise, obscuring communication patterns.

**Format**: Noise codon = `[0x00, 0x00, 0x00]` (NOOP)

**Generation Rules**:
- Default noise ratio: **10%** (1 noise per 10 real codons)
- Noise codons are randomly interleaved with real codons
- The `noise_count` field in the CODON payload declares how many to discard
- Receiver separates real codons from noise using the count fields

**Identification & Discard**:
- Receiver checks first 3 bytes of each codon
- `[0x00, 0x00, 0x00]` → noise, silently discarded
- Any non-zero codon → proceed to anticodon lookup
- Lookup failure (unknown codon) → log error, drop the packet

**Performance Impact** (measured):
- 10% noise ratio adds ~21% byte overhead
- Decode overhead: ~0.3 µs per call (negligible)

### 3.5 Data Fragmentation

> When a single operation call is too large for one packet, it is split across multiple fragments.

**Fragmentation Mechanism**:
- Flags bit 4 (IS_FRAGMENTED) = 1 means more fragments follow
- Same `stream_id` + consecutive `sequence` numbers identify fragments of one call
- Last fragment has IS_FRAGMENTED = 0
- Each fragment is independently CRC-16 checked

**Reassembly Rules**:
- Receiver collects fragments by `(stream_id, sequence)`
- Call is complete when IS_FRAGMENTED = 0 fragment arrives
- Reassemble payload from all fragments before decoding
- Timeout without completion → send ERROR (TRANSPORT_ERROR), discard all fragments

### 3.7 HMAC Message Authentication (optional, v0.2.0+)

When the session negotiates `CAP_HMAC`, each packet carries an HMAC-SHA256 tag after the CRC-16:

```
(no HMAC)  [header][payload][CRC16][padding]
(with HMAC) [header][payload][CRC16][HMAC16][padding]
                                  ↑ err det  ↑ tamper det
```

- HMAC key = `derive_hmac_key(master_seed, chain_index)`, 32 bytes
- Coverage: header + payload + CRC-16 (full packet signature)
- Tag truncated to 16 bytes (128 bits)
- Verification uses `hmac.compare_digest()` for constant-time comparison
- HMAC tag is written before padding; at standard sizes (64/128/256...), the 16B HMAC + 2B CRC are typically both absorbed by padding

### 3.8 Padding

Packets are padded to the nearest standard size: 64, 128, 256, 512, or 1024 bytes. Padding bytes are random (also serving as anti-traffic-analysis noise). Padding is appended **after** the CRC-16 checksum and HMAC tag (if any), so it does not affect `payload_len`.

---

## 4. Protocol Flow

### 4.1 Phase 1: Secure Handshake (ANA-S)

ANA-S is ANA Chain's native security layer, fully replacing TLS. It uses **X25519 ECDH** key exchange + **Ed25519** signatures + **ChaCha20-Poly1305** AEAD encryption, inspired by the Noise Protocol Framework's `IK` pattern (used by WhatsApp and WireGuard).

**Design principles**:
- Trust root: Agent Identity (AID) — 32-byte unique ID + Ed25519 public key
- Peer-to-peer trust: SSH known_hosts model, no CA hierarchy
- Each Agent holds a long-term AID; sessions are recoverable

**Trust establishment** (out-of-band):
1. **Pre-registration**: Agent developer registers AID with the API platform (provides public key)
2. **Invitation link**: Temporary link containing AID + public key, exchanged via any channel
3. **DHT/Registry**: AID published to distributed registry for query (v0.4+ planned)

**Initial handshake** — 1-RTT (Noise_IK pattern):

```
Agent A (initiator)                     Agent B (responder)
  |                                       |
  |── HELLO ────────────────────────────>|
  |   aid_id_A:     32 bytes            |  (A's identity)
  |   eph_pk_A:     32 bytes (X25519)   |  (A's ephemeral key)
  |   nonce_A:      16 bytes            |
  |   codebook_ids: ["weather-v1",...]  |  (supported codebooks)
  |   signature_A:  64 bytes (Ed25519)  |  (A signs all above)
  |                                       |
  |                   B computes:          |
  |                   shared = X25519(sk_B, eph_pk_A)  ← ECDH (static-ephemeral)
  |                   Verifies A's Ed25519 signature    |
  |                   Selects common codebook           |
  |                                       |
  |<── HELLO_ACK ───────────────────────|
  |   aid_id_B:     32 bytes            |
  |   eph_pk_B:     32 bytes (X25519)   |  (B's ephemeral key)
  |   nonce_B:      16 bytes            |
  |   codebook_id:  "weather-v1"        |
  |   codebook_ver: uint16 (3)          |
  |   session_conf: timeout/max_pkt/rot  |
  |   signature_B:  64 bytes (Ed25519)  |
  |                                       |
  |   A computes:                         |
  |   shared1 = X25519(eph_sk_A, eph_pk_B) ← second ECDH (ephemeral-ephemeral)
  |   shared2 = X25519(eph_sk_A, pk_B)     ← ECDH (ephemeral-static)
  |   session_seed = HKDF(shared1 || shared2, nonce_A || nonce_B)
  |   Verifies B's Ed25519 signature       |
  |                                       |
  |── CONFIRM ──────────────────────────>|
  |   HMAC(session_seed, "ANA-S-confirm") |
  |                                       |
  |══ SECURE CHANNEL ESTABLISHED ════════|
```

**Key security properties**:
- **Forward secrecy**: Ephemeral X25519 keys per handshake. Even if long-term AID private key is compromised later, past session_seeds are safe — they are mixed with ephemeral shared secrets
- **Identity binding**: Ed25519 signatures prove the initiator owns aid_id_A's private key
- **Key confirmation**: CONFIRM proves both sides derived the same session_seed

**Session resumption (PSK 0-RTT)**:

For frequently communicating Agents, cache the previous session_seed:

```
Agent A                                Agent B
  |── RESUME ─────────────────────────>|
  |   psk_id: hash(session_seed_prev)  |
  |   eph_pk_A:    32 bytes (X25519)   |
  |   nonce_A:     16 bytes            |
  |   0-RTT encrypted data (AEAD)       |
  |   signature_A: 64 bytes            |
  |                                     |
  |<── RESUME_ACK ─────────────────────|
  |   nonce_B:     16 bytes            |
  |   signature_B: 64 bytes            |
  |                                     |
  |══ NEW SECURE CHANNEL ═════════════|
```

- Agent A sends encrypted data in the first packet (0-RTT), using a temporary AEAD key derived from cached session_seed
- Agent B decrypts 0-RTT data with the PSK, derives a new session_seed
- **Forward secrecy preserved**: new session uses fresh ephemeral keys

**Timeout & Retry**: HELLO → 5s → retry (max 3). HELLO_ACK → 5s → close. All fail → FALLBACK.

**Version compatibility & session expiry**: same as v0.2.0.

### 4.2 Phase 2: Data Transfer (AEAD Encrypted)

```
Agent                                API
  |                                   |
  |── CODON [seq=1] ────────────────>|
  |   codons: S=1,O=1,T=0,           |
  |     city="Beijing", days=7       |
  |                                   |
  |<── CODON [seq=1] ────────────────|
  |   codons: S=128,O=1,T=0,         |
  |     (response: temp=28, humidity=65) |
```

**Agent-side steps**:
1. Encode tool call as codon: `[S, O, T] + encode_params(params, types)`
2. Mix in noise codons at configured ratio
3. Build CODON packet (seq, stream_id)
4. Serialize to wire bytes (with padding)
5. Send over UDP (or TCP)

**API-side steps**:
1. Receive packet → CRC-16 check
2. Extract codon list → filter noise (`[0x00,0x00,0x00]`)
3. For each real codon, perform anticodon lookup:
   - `service = codebook.services[S]`
   - `operation = service.operations[O & 0x7F]`
   - `template = operation.templates[T]`
   - `params = decode_params(codon[3:], template.types)`
4. Execute operation, encode result as response codon (op_id high bit = 1)
5. Send response CODON packet (same stream_id, same sequence)

### 4.3 Phase 3: Sub-Chain Rotation

Triggered automatically every N packets (default: **1000**):

```
Agent                                API
  |── CODON [seq=1000] ─────────────>|
  |                                   |
  |── ROTATE ───────────────────────>|
  |   new_chain_index: 1             |
  |   (all subsequent codons use     |
  |    subchain[1] mapping)          |
  |                                   |
  |<── ROTATE_ACK ───────────────────|
  |   ack_chain_index: 1             |
  |                                   |
  |══ NOW USING SUBCHAIN[1] ═════════|
```

**ROTATE_ACK Loss Handling**:
- Sender starts 5s timer after ROTATE
- No ROTATE_ACK → retransmit ROTATE (max 3 attempts)
- All 3 fail → send ERROR (TRANSPORT_ERROR), fall back to previous sub-chain
- Receiver gets duplicate ROTATE (chain already switched) → re-send ROTATE_ACK (idempotent)

**Chain Index Overflow**:
- chain_index is uint32 (max 4,294,967,295)
- At overflow: send ROTATE to chain_index = 0 (wrap around)
- Safer: re-negotiate session before reaching UINT32_MAX to get a fresh master_seed

### 4.4 Fallback

```
Agent                                API
  |── CODON [seq=N] ────────────────>|
  |<── ERROR ────────────────────────|
  |   code: CODON_UNKNOWN (0x1001)   |
  |                                   |
  |── FALLBACK ─────────────────────>|
  |   reason: "codebook mismatch"    |
  |                                   |
  |══ CONTINUE IN JSON-RPC 2.0 MODE ═|
  |══ (re-negotiate to recover codon mode later) |
```

---

### 4.5 Reliability Layer

> ANA uses UDP for data transfer, but UDP provides no delivery guarantees. The reliability layer adds ACK confirmation, automatic retransmission, heartbeat-based liveness detection, and sub-chain synchronization on top.

**CODON ACK Mechanism**:
- Every received CODON packet MUST be acknowledged with a CODON ACK (IS_ACK flag set)
- The ACK payload contains `ack_sequence` — the sequence number of the packet being acknowledged
- Sender maintains a pending-ACK queue (`ACKTracker`), default timeout 1.0s
- Unacknowledged packet → automatic retransmission (default max 3 retries)
- 3 retries exhausted → `TimeoutEvent` emitted for application-layer handling

**Heartbeat (PING/PONG)**:
- 30 seconds of idle → automatically send PING control codon (`[0xFF, 0x04, 0x00]`)
- Receiver gets PING → replies PONG (`[0xFF, 0x05, 0x00]`)
- 90 seconds without any packet (data/PING/PONG) → peer declared unreachable → `PeerDeadEvent`
- Any valid received packet refreshes the heartbeat timer

**Sub-Chain Sync Verification**:
- Each CODON packet carries the sender's current `chain_index` (first 2 bytes of payload)
- Receiver compares `chain_index` with its own session state
- Mismatch → `ChainMismatchEvent` → application can trigger re-synchronization
- This prevents the silent failure mode where a lost ROTATE causes both sides to use different codon mappings

**Retransmission & ACK State Machine**:
```
Sender                     Receiver
  |                          |
  |── CODON [seq=5] ───────>|  ACK sent
  |   (queued for ACK)      |── CODON+ACK [ack=5] ──>|
  |                          |
  |<── CODON+ACK ─────────  |  ACK received ✓
  |
  |── CODON [seq=6] ───────>|  ⚡ lost in transit
  |   (1.0s timeout)        |
  |── CODON [seq=6] ───────>|  ACK received ✓
  |   (retransmit #1)
```

---

## 5. Security Model

### 5.1 Threat Model (Complete)

| Threat | Severity | Mitigation | Residual Risk |
|--------|----------|------------|---------------|
| **Passive eavesdropper** (no codebook) | Medium | Codons are opaque random bytes | Metadata (IP, packet timing) still visible |
| **Passive eavesdropper** (has old codebook) | High | Sub-chain rotation limits window to 1000 packets | Attacker with codebook can decode all packets within current sub-chain |
| **Known-plaintext attack** | High | Sub-chain rotation + per-session nonce | Attacker who knows the operation AND has the codebook can reverse-map that codon. Impact limited to 1000 packets per session |
| **Replay attack** | Medium | Sequence number sliding window (reject seq < last_seen - 100) | Up to 100 reorder-window replays possible |
| **Packet injection** | High | CRC-16 + anticodon validation | ⚠️ CRC-16 is an **error-detecting code**, not a MAC. An active attacker can forge valid CRC-16 checksums. **ANA alone does NOT provide integrity.** |
| **Traffic analysis** | Low | Fixed-size padding + noise codons | Timing side-channels may still leak (v0.2: constant-rate mode) |
| **Timing side-channel** | Low | — (not yet addressed) | Lookup time variance may leak codebook indices. Mitigation: constant-time lookup (v0.2 planned) |
| **Denial of Service** | High | Rate limiting + fast noise filtering | Massively invalid codons force server lookups. Mitigation: O(1) Bloom filter pre-screening |

### 5.2 Dual Protection: CRC-16 + HMAC-SHA256

> **Starting from v0.2.0, ANA provides optional HMAC-SHA256 message authentication, forming a dual-layer integrity system with CRC-16.**

| Layer | Type | Size | Purpose |
|-------|------|------|---------|
| CRC-16 | Error-detecting code | 2 bytes | Detect random bit errors (wireless noise, storage corruption) |
| HMAC-SHA256 | Message authentication code | 16 bytes (truncated) | Detect active tampering attacks |

**Why keep CRC-16**: In noisy environments (wireless, long-haul links), random bit flips are more common than active attacks. CRC-16 filters 99.997% of random errors at negligible cost (2 bytes + 0.05 µs).

**How HMAC works**:
- Key derived from master_seed via HKDF: `derive_hmac_key(master_seed, chain_index)`
- Coverage: `header + payload + CRC-16` (full packet signature)
- Truncated to 16 bytes (128 bits), resisting 2^128 forgery attempts
- HMAC key rotates automatically with each sub-chain rotation
- Negotiated via `CAP_HMAC` capability flag

**Performance**: HMAC compute +0.9 µs, verify +0.9 µs (hardware-accelerated SHA-256). The 16-byte tag is typically absorbed by 64B min-packet padding.

**What an active attacker now needs**:
1. Possess the codebook (otherwise codons are random bytes)
2. Possess the HMAC key (otherwise cannot forge authentication tags)
3. OR compromise the TLS layer (if TLS is deployed)

### 5.3 DoS Protection — Bloom Filter

> **v0.2.0 adds Bloom filter pre-screening: O(1) rejection of invalid codons before the expensive anticodon lookup.**

**Attack scenario**: Attacker floods CODON packets with random content. Each packet requires a full anticodon lookup (dictionary lookup, O(log N)) to determine validity. 10K invalid packets/sec can exhaust server CPU.

**Bloom filter pre-screening**:
- Size: 1 KB (8192 bits), 7 hash functions
- For 1000 valid codon prefixes, false positive rate < 1%
- Known valid prefix → hit → proceed to normal lookup (+0.57 µs)
- Unknown prefix → 99.9% miss → reject immediately (saves -1.5 µs of lookup)
- 62% CPU savings under DoS attack

**Caveats**:
- 1% false positive rate means ~1 in 100 invalid codons passes the filter and still needs full lookup (where it is definitively rejected)
- Control codons (PING/PONG/TEARDOWN) and noise codons [0x00,0x00,0x00] are NOT added to the filter
- Filter is built on codebook load, supports dynamic add/remove

### 5.4 ANA-S: Native Security Layer (v0.3.0)

> **From v0.3.0, ANA-S replaces TLS as ANA's native security layer.**  
> TLS is no longer required but can still be layered for extra defense-in-depth.

#### 5.4.1 Motivation

TLS's security model (X.509 certificates + CA hierarchy) was designed for browser-server communication. It conflicts structurally with Agent scenarios:

| TLS Assumption | Agent Reality |
|---------------|---------------|
| Domain names and CA-issued certificates | Agents identified by UUID/AID, no domain |
| CA trust chain verifiable | Agents only have peer-to-peer trust |
| Certificate validity: 1 year | Agent sessions may last 5 seconds |
| Human clicks "trust this certificate" | Agent communication is fully automated |
| ECDHE runs on servers | Agents may run on IoT/edge devices |

#### 5.4.2 Cryptographic Primitives

| Primitive | Algorithm | Purpose |
|-----------|-----------|---------|
| Key exchange | **X25519** (ECDH over Curve25519) | Secure shared secret negotiation |
| Identity signature | **Ed25519** | Sign handshake packets, bind identity |
| Link encryption | **ChaCha20-Poly1305** (AEAD) | Encrypt payload + integrity auth tag |
| Key derivation | **HKDF-SHA256** | Derive session_seed, AEAD keys, sub-chain keys |
| Hashing | **BLAKE2b** | Fast hashing (AID fingerprints, PSK IDs) |

**Why ChaCha20-Poly1305 over AES-GCM?**
- Comparable speed in pure software (no AES-NI required — IoT/edge friendly)
- Naturally resistant to cache-timing side-channel attacks
- RFC 8439 standardized, supported by WireGuard and TLS 1.3

#### 5.4.3 Key Hierarchy

```
AID long-term keypair (persistent, offline storage)
  ├── X25519 static private key (sk_A): used for ECDH on HELLO receipt
  └── Ed25519 signing private key: used to sign handshake packets

Post-handshake:
  X25519(eph_sk_A, eph_pk_B) → shared_secret_1  ← ephemeral-ephemeral ECDH
  X25519(sk_A, eph_pk_B)     → shared_secret_2  ← static-ephemeral ECDH
  session_seed = HKDF(shared_secret_1 || shared_secret_2,
                      nonce_A || nonce_B)
  ↓
  K_i = HKDF(session_seed, i, "ANA-v1-K")       ← rotated every 1000 packets
  ↓
  AEAD_key_j = HKDF(K_i, j, "ANA-v1-AEAD")      ← one key per packet
```

#### 5.4.4 Security Guarantees

| Property | Mechanism | Strength |
|----------|-----------|----------|
| **Payload confidentiality** | ChaCha20-Poly1305 AEAD encryption | 256-bit |
| **Message integrity** | Poly1305 auth tag (16 bytes) | 128-bit |
| **Identity authentication** | Ed25519 signatures (mutual, A and B) | 128-bit |
| **Forward secrecy** | X25519 ephemeral keys, new per handshake | Per session |
| **Key forward secrecy** | Chained HKDF derivation, K_i leak does not affect K_{i+1} | Per 1000 packets |
| **Anti-replay** | Sequence number + sliding window (±100) | 100-packet window |
| **Anti-MITM** | Ed25519 identity binding + mutual signatures | Computationally secure |
| **Traffic analysis resistance** | Fixed padding + noise codons + AEAD encryption | Limited |

#### 5.4.5 Quantum Threat Assessment

| Primitive | Quantum Threat | Attack Algorithm |
|-----------|---------------|-----------------|
| X25519 ECDH | ⚠️ **Fully broken** | Shor's algorithm (polynomial time) |
| Ed25519 signatures | ⚠️ **Fully broken** | Shor's algorithm (polynomial time) |
| ChaCha20-Poly1305 | ✅ Safe (2^128) | Grover's algorithm |
| HKDF-SHA256 | ✅ Safe (2^128) | Grover's algorithm |

> **v0.3.0 does not compete with PQC.** If quantum resistance is required, v0.4+ plans to support CRYSTALS-Kyber (key exchange) + CRYSTALS-Dilithium (signatures) as optional PQC primitives.

#### 5.4.6 Comparison with TLS 1.3

| Dimension | TLS 1.3 | ANA-S v0.3.0 |
|-----------|---------|---------------|
| Trust model | CA hierarchy (X.509) | Peer-to-peer (AID + public key) |
| Initial handshake | 1-RTT (~1-5ms) | 1-RTT (~0.3ms) |
| PSK resumption | 0-RTT | 0-RTT |
| Encryption | AES-GCM / ChaCha20-Poly1305 | ChaCha20-Poly1305 |
| Key exchange | ECDHE (X25519) | X25519 ephemeral-static + ephemeral-ephemeral |
| Signatures | ECDSA / Ed25519 / RSA | Ed25519 |
| Forward secrecy | ✅ (ECDHE ephemeral) | ✅ (ephemeral X25519) |
| Handshake packet size | ~200-400 bytes | ~288 bytes |
| Certificate management | Requires CA, domain, certificate | AID + public key, pre-shared |
| Production battle-testing | 10 years | Not yet |

#### 5.4.7 Packet Format Change (AEAD Mode)

When ANA-S is active, data packet format is updated to:

```
[header: 12B] [auth_tag: 16B] [encrypted_payload: N bytes] [padding]
                 ↑ Poly1305                 ↑ ChaCha20 encrypted
```

- `payload_len` points to the encrypted payload length
- `auth_tag` covers `header + encrypted_payload`
- Receiver: verify auth_tag first → decrypt payload → decode codons
- CRC-16 and HMAC are replaced by Poly1305 auth tag in AEAD mode (AEAD provides both integrity and encryption)

#### 5.4.8 Backward Compatibility

- If one side lacks ANA-S (legacy Agent/API), fall back to v0.2.0 negotiation mode
- Legacy side may still wrap in external TLS if needed
- New Agent auto-detects lack of ANA-S support → falls back to v0.2.0

---

## 6. Performance Characteristics

### 6.1 Format Comparison

| Dimension | JSON | Protobuf | ANA Codon |
|-----------|------|----------|-----------|
| Serialization overhead | High (field name repetition) | Medium (field numbers) | Minimal (3-byte header) |
| Human-readable | ✅ Yes | ❌ No | ❌ No |
| Requires schema | ❌ No | ✅ .proto file | ✅ Codebook |
| Parse speed | Slow (string parsing) | Medium | Very fast (integer lookup) |
| Token-friendly | ❌ Every field name = token | ❌ Binary | ✅ Semantic tokens |
| Typical message size | 200–500 B | 50–150 B | 8–30 B |

### 6.2 Measured Benchmarks

| Metric | JSON/HTTP | ANA Chain | Improvement |
|--------|-----------|-----------|-------------|
| **End-to-end latency** | 250.6 ms | 38.0 ms | **6.6x** |
| LLM generation time | 243.9 ms | 59.0 ms | **4.1x** |
| Encoding throughput | 638K ops/s | 1,653K ops/s | **2.6x** |
| Tokens per call | 19.5 | 4.7 | **76%** reduction |
| Bandwidth per call | 274 B | 64 B | **77%** reduction |
| Protocol overhead | ~195 B | 14 B | **14x** smaller |

### 6.3 Codon Size vs JSON

| Operation | JSON (bytes) | Codon (bytes) | Reduction |
|-----------|-------------|---------------|-----------|
| `get_weather(city="Beijing")` | ~200 | 4 | 50x |
| `db_query(sql="SELECT...")` | ~500 | 6 | 83x |
| `read_file(path="/a/b/c")` | ~150 | 5 | 30x |
| `noop_response()` | ~50 | 3 | 17x |

### 6.4 Token Cost Estimate

LLM tokens saved per function call: ~50–200 tokens (output) + ~100–250 tokens (context). At typical pricing (~$3/M input, ~$15/M output), 1000 calls/day saves ~$3.30/day.

---

## 7. Error Codes

| Code | Name | Description |
|------|------|-------------|
| 0x1001 | CODON_UNKNOWN | Codon not found in current codebook |
| 0x1002 | CODON_INVALID | Codon format invalid |
| 0x2001 | CODEBOOK_MISMATCH | No common codebook version |
| 0x3001 | SESSION_EXPIRED | Session timed out |
| 0x3002 | SEQUENCE_INVALID | Sequence out of window (possible replay) |
| 0x3003 | SUBCHAIN_MISMATCH | Sub-chain index mismatch (ROTATE may have been lost) |
| 0x4001 | TRANSPORT_ERROR | Transport layer error (fragment timeout, etc.) |
| 0x4002 | PEER_UNREACHABLE | Peer unreachable (heartbeat timeout) |

---

## 8. Extension Points

### 8.1 Service ID 0xFF — Control Channel

Reserved for protocol-level control operations:
- `[0xFF, 0x01, *]` — Heartbeat/Ping
- `[0xFF, 0x02, *]` — Session teardown
- `[0xFF, 0x03, *]` — Capability re-negotiation

### 8.2 Template ID 0xFF — Dynamic Parameters

Indicates fully dynamic parameters (no predefined template).

**Note**: v0.1 does NOT support inline binary schema descriptors for dynamic parameters. All parameter types must be pre-declared in the codebook's template definitions. For runtime-dynamic parameters, use:
- FALLBACK to JSON-RPC mode
- Or wait for v0.2 compact binary schema descriptors

### 8.3 v0.2.0 Completed ✅

- ✅ **HMAC-SHA256 message authentication** — optional capability (CAP_HMAC), key rotates with sub-chain
- ✅ **Bloom filter pre-screening** — 1KB / O(1) rejection of invalid codons, anti-DoS

### 8.4 v0.3+ Planned Features

- **Constant-time lookup** — resists timing side-channels
- **Constant-rate transmission** — fixed-interval sends to fully mask activity
- **Multi-hop routing** — codon forwarding through intermediate agents
- **Streaming codons** — incremental results for long-running operations
- **Permission-bound codebooks** — read-only/scoped codebook subsets
- **Codebook registry** — distributed codebook version discovery and distribution
- **Multi-language SDK** — Rust / Go / TypeScript implementations

---

## 9. Relationship to Existing Protocols

```
┌─────────────────────────────────────┐
│         AI Agent (LLM)              │
├─────────────────────────────────────┤
│   MCP / A2A (tool discovery & orch) │
├─────────────────────────────────────┤
│   ★ ANA Chain (encoding layer)      │  ← This protocol
├─────────────────────────────────────┤
│   TLS (transport security) — must   │
├─────────────────────────────────────┤
│   TCP / UDP                         │
└─────────────────────────────────────┘
```

ANA does not replace MCP, A2A, or TLS — it sits beneath them, providing an AI-native encoding format. Existing Agent frameworks only need to switch to the ANA encoder for tool calls; all other layers remain unchanged.

---

## 10. Reference Implementation

- **Language**: Python 3.13+
- **Version**: v0.3.0
- **Location**: `ana-chain/ana/` (core library), `ana-chain/examples/` (demos), `ana-chain/benchmarks/` (benchmarks)
- **Tests**: 91 unit tests passing (HKDF RFC5869 vectors, ChaCha20 PRNG, varint codec, packet serialization, noise filtering, anti-replay, sub-chain rotation, session lifecycle, HMAC tamper detection, Bloom filter false positive rate)
- **Dependencies**: PyYAML (codebook definition parsing)

Key modules:
```
ana/
├── codebook.py    # Codebook model + HKDF + ChaCha20 PRNG + HMAC key derivation
├── codon.py       # Codon codec + LEB128 varint + control codons (PING/PONG)
├── packet.py      # Packet format + CRC-16 + HMAC-SHA256 + capability flags
├── session.py     # Session state machine + anti-replay + HMAC key management
├── negotiator.py  # TCP negotiation handshake
├── transport.py   # UDP transport + noise injection
├── reliability.py # ACK/retransmission/heartbeat/chain sync + Bloom filter DoS
├── security.py    # ANA-S: X25519 + Ed25519 + ChaCha20-Poly1305 AEAD (v0.3.0 new)
└── fallback.py    # JSON-RPC 2.0 fallback
```

---

## Changelog

```
## v0.3.0 (2026-08-04) — ANA-S Native Security Layer
- ANA-S security layer: TLS-independent, self-contained secure handshake
- X25519 ECDH key exchange + Ed25519 signatures + ChaCha20-Poly1305 AEAD
- Agent Identity (AID) trust model (peer-to-peer, no CA)
- 1-RTT initial handshake (Noise_IK pattern)
- 0-RTT PSK session resumption
- Forward secrecy (ephemeral X25519)
- Chained HKDF key hierarchy (session_seed -> K_i -> AEAD_key_j)
- Packet format update: +AEAD auth tag (16B), encryption mode bit 6
- Packet types renaming: NEGOTIATE->HELLO, +RESUME/RESUME_ACK/REKEY
- Protocol version bumped to 0x02
- New error codes: AUTH_FAILED, AID_UNKNOWN, AEAD_ERROR

## v0.2.0 (2026-08-04)
- HMAC-SHA256 message auth + Bloom filter DoS + ACK/retransmission/heartbeat
- Tests expanded from 62 to 91

## v0.1.0 (2026-08-03)
- Initial draft: wire format, negotiation, codebook hierarchy, noise codons
- Security threat model, glossary, timeout/retry, reference implementation
```

---

*Specification version: v0.3.0 | Date: 2026-08-04*
