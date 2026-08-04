# ANA Chain Protocol Specification v0.2.0

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

### 3.1 Common Packet Header (12 bytes)

```
Offset  Size  Field
------  ----  -----
0       2     Magic number: 0xA7A7
2       1     Protocol version (0x01)
3       1     Flags
              bit 0-2: Packet type (0-7)
              bit 3:   Has noise codons
              bit 4:   Is fragmented
              bit 5-7: Reserved
4       2     Stream ID (uint16, big-endian)
6       4     Sequence number (uint32, big-endian)
10      2     Payload length (uint16, big-endian)
12      N     Payload
12+N    2     CRC-16 checksum (of bytes 0 through 12+N-1)
```

Total header overhead: **12 bytes** (vs HTTP's typical 200–800 bytes).

### 3.2 Packet Types

| Type | Name | Direction | Description |
|------|------|-----------|-------------|
| 0x00 | NEGOTIATE | Agent→API | Initial handshake: supported codebook IDs |
| 0x01 | NEGOTIATE_ACK | API→Agent | Handshake response: selected codebook + session nonce |
| 0x02 | NEGOTIATE_CONFIRM | Agent→API | Agent confirms session establishment |
| 0x03 | CODON | Both | Data transfer: one or more codons |
| 0x04 | ROTATE | Both | Trigger sub-chain rotation |
| 0x05 | ROTATE_ACK | Both | Acknowledge rotation |
| 0x06 | ERROR | Both | Report an error condition |
| 0x07 | FALLBACK | Both | Switch to JSON/text mode |

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

### 4.1 Phase 1: Negotiation

```
Agent                                API
  |                                   |
  |── NEGOTIATE ────────────────────>|
  |   codebook_ids: ["weather-v1",   |
  |     "db-v2", "file-v1"]          |
  |                                   |
  |<── NEGOTIATE_ACK ───────────────|
  |   selected: "weather-v1"         |
  |   version: 3                     |
  |   session_nonce: <random 32B>    |
  |   session_timeout: 3600s         |
  |   max_packet_size: 1024          |
  |   rotation_interval: 1000        |
  |                                   |
  |── NEGOTIATE_CONFIRM ───────────>|
  |                                   |
  |══ SESSION ESTABLISHED ═══════════|
```

**Timeout & Retry**:
- NEGOTIATE sent → 10s timeout waiting for NEGOTIATE_ACK → retry (max 3)
- NEGOTIATE_ACK sent → 10s timeout waiting for NEGOTIATE_CONFIRM → close connection
- All 3 retries fail → switch to FALLBACK (JSON-RPC 2.0)

**Version Compatibility**:
- Each side lists supported codebook IDs
- API selects the first codebook that appears in both lists (highest priority wins)
- No common codebook → API sends ERROR (CODEBOOK_MISMATCH) → Agent falls back to JSON
- Agent may cache incompatible APIs to skip repeated negotiation failures

**Session Expiry**:
- Default timeout: 3600 seconds (1 hour)
- `last_active` refreshed on each valid received packet
- Expired → either side sends ERROR (SESSION_EXPIRED), peer closes connection
- A new negotiation is required to re-establish

### 4.2 Phase 2: Data Transfer

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

### 5.4 Relationship to TLS

> **ANA is NOT a replacement for TLS. Initial negotiation MUST occur over TLS.**

| Security Function | ANA | TLS | Recommendation |
|-------------------|-----|-----|----------------|
| Payload confidentiality | ✅ (codebook seed = key) | ✅ (AES-GCM) | Layer both |
| Message integrity | ✅ (HMAC-SHA256, v0.2.0+) | ✅ (GCM auth tag) | Layer both |
| Anti-replay | ⚠️ (seq window) | ✅ (TLS 1.3 built-in) | Rely on TLS |
| Authentication | ❌ | ✅ (certificate chain) | Rely on TLS |
| Key exchange | ❌ | ✅ (ECDHE) | Rely on TLS |
| Traffic analysis resistance | ⚠️ (padding + noise) | ❌ | ANA unique |

**Recommended production deployment**: `TLS (security) + ANA (performance + traffic analysis resistance)`

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
- **Version**: v0.2.0
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
└── fallback.py    # JSON-RPC 2.0 fallback
```

---

## Changelog

```
## v0.2.0 (2026-08-04)
- HMAC-SHA256 message authentication (optional capability CAP_HMAC)
- Bloom filter DoS pre-screening (1KB, <1% false positive rate)
- CRC-16 + HMAC dual-layer integrity architecture
- CODON ACK + timeout retransmission (ACKTracker)
- PING/PONG heartbeat liveness detection
- Sub-chain sync verification (chain_index in CODON packets)
- Control codons: PING/PONG/TEARDOWN
- CODON ACK flag (bit 5) and chain_index in payload
- New error codes: SUBCHAIN_MISMATCH, PEER_UNREACHABLE
- Tests expanded from 62 to 91

## v0.1.0 (2026-08-03)
- Initial draft
- Core wire format + negotiation flow
- Codebook hierarchical structure (Service -> Operation -> Template)
- Noise codon mechanism + data fragmentation
- Security threat model + JSON/Protobuf/ANA comparison
- Glossary + timeout/retry + reference implementation
```

---

*Specification version: v0.2.0 | Date: 2026-08-04*
