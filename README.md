# ANA — AI-Native Communication Protocol

[![Version](https://img.shields.io/badge/version-0.3.0-blue)](https://github.com/YeraldoSmith/ANA)
[![Tests](https://img.shields.io/badge/tests-91%20%2B%2013%20(Rust)-green)](https://github.com/YeraldoSmith/ANA)
[![License](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)

**AI-Native Communication Protocol** — replacing JSON serialization with biological codon-based semantic addressing.

ANA Chain eliminates the serialization bottleneck in LLM Agent ↔ API communication by mapping API operations directly to compact binary "codons" via a pre-shared codebook. Inspired by the codon–anticodon pairing in protein synthesis.

---

## Performance

| Metric | JSON/HTTP | ANA Chain | Improvement |
|--------|-----------|-----------|-------------|
| End-to-end latency (+LLM) | 775 ms | **37.5 ms** | **20.7x** |
| Token consumption | 62 | **3** | **20.7x** |
| Wire bytes | 535 B | **146 B** | **3.7x** |
| Software encode (Rust) | 1.6 µs | **0.18 µs** | **8.9x** |
| Software roundtrip (Rust) | 1.6 µs | **0.94 µs** | **1.7x** |

---

## Quick Start

### Python (reference implementation)

```bash
pip install pyyaml
cd python
python3 examples/agent_demo.py
```

### Rust (high-performance core)

```bash
cd ana-core
cargo test
cargo bench
```

### LAN Test Bench

```bash
cd testbench
python3 server.py
# Open http://<your-ip>:8080 on your phone
```

---

## Architecture

```
┌─────────────────────────────────────┐
│         AI Agent (LLM)              │
├─────────────────────────────────────┤
│   MCP / A2A (tool discovery)        │
├─────────────────────────────────────┤
│   ★ ANA Chain (encoding layer)      │  ← This protocol
├─────────────────────────────────────┤
│   ANA-S (native security, v0.3.0)   │
├─────────────────────────────────────┤
│   TCP / UDP                         │
└─────────────────────────────────────┘
```

### Protocol Layers

| Layer | Mechanism |
|-------|-----------|
| **Encoding** | Codon–anticodon lookup (3-byte semantic addressing) |
| **Reliability** | ACK tracking, retransmission, PING/PONG heartbeat |
| **Security (v0.3.0)** | ANA-S: X25519 ECDH + Ed25519 + ChaCha20-Poly1305 AEAD |
| **DoS Protection** | 1KB Bloom filter pre-screening |
| **Traffic Obfuscation** | Fixed-size padding + noise codons |

---

## Project Structure

```
ana-chain/
├── README.md
├── spec/
│   ├── protocol-v0.3.0.md          # English specification
│   └── protocol-v0.3.0.zh.md       # Chinese specification
├── ana/                             # Python reference implementation
│   ├── codebook.py                  # Codebook model + HKDF + ChaCha20
│   ├── codon.py                     # Codon codec + LEB128 varint
│   ├── packet.py                    # Packet format + CRC-16 + HMAC
│   ├── session.py                   # Session state machine
│   ├── negotiator.py                # TCP negotiation handshake
│   ├── transport.py                 # UDP transport + noise injection
│   ├── reliability.py               # ACK/retransmission/heartbeat/Bloom
│   └── fallback.py                  # JSON-RPC 2.0 fallback
├── ana-core/                        # Rust high-performance core
│   ├── src/
│   │   ├── lib.rs
│   │   ├── codon.rs                 # Codon codec + varint
│   │   └── packet.rs                # Packet serialize + CRC + HMAC
│   └── benches/
├── testbench/                       # LAN comparison dashboard
│   └── server.py
├── benchmarks/                      # Performance benchmarks
├── tests/                           # Python test suite (91 tests)
└── examples/                        # Demo code
```

---

## Specification

Full protocol specifications available in:
- [English](spec/protocol-v0.3.0.md)
- [Chinese / 中文](spec/protocol-v0.3.0.zh.md)

Key features:
- 256^3 = 16.7M operation signatures per codebook
- 12-byte packet header (vs HTTP 200+ bytes)
- 1-RTT secure handshake (Noise_IK pattern)
- Sub-chain rotation every 1000 packets (forward secrecy)
- Automatic JSON-RPC 2.0 fallback on codebook mismatch

---

## Author

**Yeraldo Smith** — [@YeraldoSmith](https://github.com/YeraldoSmith)

---

## License

MIT
