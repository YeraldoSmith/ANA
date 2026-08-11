# ANA v0.1 Draft Release Notes

## v0.1 Draft — 2026-08-11

### Included

- RFC-0001 through RFC-0005: architecture, ANA Chain, Envelope, Memory System, and Local Runtime boundaries.
- `ana-core-chain` v0.1 minimal profile: canonical JSON frames, version metadata, task Envelope payloads, and `project_state.upsert` State Deltas.
- Local-first ownership boundary: Local Runtime owns Memory, Project State, routing, policy, and execution decisions; providers are compute.
- Reference Python implementation and an independent Java minimal-Core implementation.
- Fixed positive, negative, canonical-JSON, and Memory/State/Policy conformance vectors.
- Python ↔ Java bidirectional conformance suite.
- Offline OpenAI-contract ↔ Anthropic-contract state-continuity validation; Provider output remains subject to Local Runtime validation and Safety Policy.

### Clarifications made during validation

- Canonical JSON rejects duplicate object members and invalid Unicode scalar sequences.
- `sequence` is a non-negative JSON integer; the State Delta payload sequence equals its frame sequence.
- v0.1 has no implicit “unknown mandatory extension” mechanism.

### Known limitations

- Draft / experimental; not production-ready or security-audited.
- No real paired OpenAI/Anthropic live interoperability result in this repository.
- No claim of general token, cost, latency, or compression advantage.
- No Codon, compact Chain profile, multi-agent protocol, cross-device conflict resolution, or expanded Memory model.
- Generic JSON number canonicalization, detailed Memory schemas, and unified Chain error codes need future specification work.

See [STATUS.md](STATUS.md), [limitations](docs/limitations.md), and the
[Phase 7 report](docs/phase-7-independent-implementation.md) for scope.
