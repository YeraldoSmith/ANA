# ANA — AI-Native Communication Protocol

[![Version](https://img.shields.io/badge/version-0.2.0-blue)](https://github.com/YeraldoSmith/ANA)
[![Tests](https://img.shields.io/badge/tests-79%20%2B%2013%20(Rust)-green)](https://github.com/YeraldoSmith/ANA)
[![License](https://img.shields.io/badge/license-AGPLv3-blue)](LICENSE)
[![Status](https://img.shields.io/badge/status-prototype-orange)](https://github.com/YeraldoSmith/ANA)

**AI-Native Communication Protocol** — replacing JSON serialization with codon-based semantic addressing for LLM Agent ↔ API communication.

ANA encodes API operations as compact binary "codons" via a pre-shared codebook, inspired by codon–anticodon pairing in protein synthesis. This eliminates the serialization/deserialization step that dominates JSON-based Agent communication.

> **Status: Prototype (v0.2.0).** Core encoding pipeline is implemented and benchmarked. LLM token claims are extrapolated, not yet measured with a real model. Native security layer (ANA-S) is specified but not yet implemented — see [Roadmap](#roadmap).

---

## Measured Performance

### Independently verified (benchmarked with real code)

| Metric | JSON | ANA | Improvement |
|--------|------|-----|-------------|
| Encode throughput (Python) | 638K ops/s | 1,653K ops/s | **2.6x** |
| Encode throughput (Rust) | — | **9,200K ops/s** | **14.4x vs Python JSON** |
| Wire bytes per call | ~535 B (HTTP+TLS) | **~146 B** | **3.7x smaller** |
| Packet header overhead | ~195 B | **14 B** | **14x smaller** |
| Full software roundtrip (Rust) | 1.6 µs | **0.94 µs** | **1.7x** |

### Token reduction (measured with tokenizer)

| Format | Avg tokens/call | Reduction |
|--------|----------------|-----------|
| JSON (OpenAI tool_call) | ~62 | — |
| JSON (compact) | ~29 | 2.1x vs OpenAI |
| ANA `<codon:>` format | ~12 | 5.2x vs OpenAI |
| ANA `@s.o.t` format | **~6** | **10x vs OpenAI** |

> Token counts measured with cl100k_base estimator (GPT-4 tokenizer, calibrated within 5%). Run `python3 benchmarks/token_format.py` to reproduce all formats. The `@1.1.0 Beijing 7` format achieves 10x token reduction over OpenAI tool_call format using only text — no model integration needed.

---

## Quick Start

```bash
# Python library
pip install pyyaml
cd examples
python3 agent_demo.py

# Rust core
cd ana-core
cargo test
cargo bench

# LAN test bench (compare JSON vs ANA from your phone)
cd testbench
python3 server.py
# Open http://<your-ip>:8080

# Minimal ANA Agent (chat-style protocol test)
cd agent
python3 server.py
# Open http://<your-ip>:5050 — try "weather in Tokyo"
```

---

## Architecture

```
┌─────────────────────────────────────┐
│         AI Agent (LLM)              │
├─────────────────────────────────────┤
│   MCP / A2A (tool discovery)        │
├─────────────────────────────────────┤
│   ★ ANA (encoding layer)            │  ← This protocol
│     - Codon codec                   │
│     - Reliability (ACK/retry/ping)  │
│     - HMAC integrity (default on)   │
│     - ANA-S (X25519+Ed25519+AEAD)   │
├─────────────────────────────────────┤
│   TCP / UDP (TLS optional)          │
├─────────────────────────────────────┤
│   TCP / UDP                         │
└─────────────────────────────────────┘
```

### Implemented (v0.2.0)

| Layer | Mechanism | Status |
|-------|-----------|--------|
| **Encoding** | Codon–anticodon lookup (3-byte semantic addressing) | ✅ |
| **Reliability** | ACK tracking, retransmission, PING/PONG heartbeat, sub-chain sync | ✅ |
| **Integrity** | HMAC-SHA256 (optional, negotiated via CAP_HMAC) | ✅ |
| **DoS Protection** | 1KB Bloom filter pre-screening | ✅ |
| **Traffic Obfuscation** | Fixed-size padding + noise codons | ✅ |
| **Fallback** | JSON-RPC 2.0 on codebook mismatch | ✅ |

### Planned

| Feature | Target | Spec |
|---------|--------|------|
| **ANA-S security layer** | v0.3.0 | X25519 + Ed25519 + ChaCha20-Poly1305 AEAD (Noise_IK), replace TLS dependency |
| **LLM token integration** | v0.4.0 | Real LLM measurement, special token / constrained decoding for codon output |
| **Codebook registry** | v0.4.0 | Distributed codebook version discovery |
| **Multi-language SDK** | v0.4.0 | TypeScript, Go |

---

## Project Structure

```
ANA/
├── README.md
├── LICENSE
├── spec/                             # Protocol specifications
│   ├── protocol-v0.2.0.md            # English (current implementation)
│   └── protocol-v0.2.0.zh.md         # Chinese
├── ana/                              # Python reference implementation
│   ├── codebook.py                   # Codebook model + HKDF + ChaCha20 PRNG
│   ├── codon.py                      # Codon codec + LEB128 varint
│   ├── packet.py                     # Packet format + CRC-16 + HMAC
│   ├── session.py                    # Session state machine + anti-replay
│   ├── negotiator.py                 # TCP negotiation handshake
│   ├── transport.py                  # UDP transport + noise injection
│   ├── reliability.py                # ACK/retransmission/heartbeat/Bloom/chain sync
│   └── fallback.py                   # JSON-RPC 2.0 fallback
├── ana-core/                         # Rust high-performance core
│   └── src/
│       ├── codon.rs                  # Codon codec + varint + param encoding
│       └── packet.rs                 # Packet serialize + CRC + HMAC
├── agent/                            # Minimal ANA-compatible Agent (web UI)
├── testbench/                        # LAN comparison dashboard (JSON vs ANA)
├── benchmarks/                       # Performance benchmarks
├── tests/                            # Python test suite (91 tests)
└── examples/                         # Demo code
```

---

## Specification

- [English spec](spec/protocol-v0.3.0.md) — v0.3.0 (includes planned ANA-S; current code implements v0.2.0)
- [Chinese spec / 中文](spec/protocol-v0.3.0.zh.md)

Key features (implemented):
- 256^3 = 16.7M operation signatures per codebook
- 12-byte packet header (vs HTTP 200+ bytes)
- Sub-chain rotation every 1000 packets
- Automatic JSON-RPC 2.0 fallback on codebook mismatch
- 91 Python tests + 13 Rust tests

---

## Roadmap

| Version | What | ETA |
|---------|------|-----|
| **v0.2.0** (current) | Codon codec, reliability, HMAC, Bloom, fallback | Done |
| **v0.2.1** | Fix code review findings, add CI, PyPI publish | ~1 week |
| **v0.3.0** | `security.py` — ANA-S native security (X25519+Ed25519+ChaCha20-Poly1305) | ~2-3 weeks |
| **v0.4.0** | Real LLM measurement, codebook registry, TypeScript SDK | ~1-2 months |

---

## Author

**Yeraldo Smith** — [@YeraldoSmith](https://github.com/YeraldoSmith)

---

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE).

This is a strong copyleft license. If you modify this software and run it as a network service, you must release your changes under the same license.
