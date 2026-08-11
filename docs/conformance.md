# ANA v0.1 Core Conformance

## Claim

An implementation may claim:

```text
ANA v0.1 Core Conformant (minimal profile)
```

only when it is an independent implementation and passes the complete fixed
conformance suite for `ana-core-chain` v0.1. This is a narrow claim; it does
not assert production readiness or support for experimental ANA concepts.

## MUST support

A conformant minimal-profile node MUST:

1. Parse and emit UTF-8 canonical JSON frames with deterministic Unicode code-point object-key ordering, unchanged array order, and no insignificant whitespace.
2. Reject duplicate object members, invalid Unicode scalar sequences, and non-canonical frames/payloads.
3. Accept only `protocol_version: "0.1"`, `chain_id: "ana-core-chain"`, `chain_version: "0.1"`, `dictionary_id: null`, `dictionary_version: null`, and an empty `transforms` array.
4. Parse a canonical `envelope` payload containing a valid RFC-0003 v0.1 Envelope: non-empty `task_id` and `intent`, at least one non-empty capability string, and object `input`; validate optional `context`, `memory_refs`, and `policy` types when present.
5. Parse and validate a `state_delta` payload of kind `project_state.upsert`, including non-empty event identity, matching stream/task, a causal parent, and a non-negative integer sequence that advances past its parent.
6. Require the State Delta payload `sequence` to equal the enclosing frame `sequence`.
7. Preserve provider-neutral MemoryRecord, Project State, and Safety-related policy structures as structured JSON; Provider text is not execution authority.

## MUST reject

A node MUST reject, before treating the payload as valid state, at least:

- an unsupported protocol/Chain/Envelope version;
- malformed or non-canonical Envelope/frame JSON;
- a frame with an unsupported required `payload_type` value;
- an invalid, non-advancing, or frame/payload-mismatched State Delta sequence;
- a State Delta whose stream, task ID, or causal parent does not match the validated predecessor;
- an unsupported State Delta kind or malformed payload.

The v0.1 RFCs require explicit rejection. Cross-language machine-readable
error-code strings are not standardized yet, so conformance compares rejection
outcomes rather than exact message text.

## Test vectors and suite

| Vector | Coverage |
| --- | --- |
| [`ana-v0.1-minimal.json`](test-vectors/ana-v0.1-minimal.json) | Positive canonical Envelope and deterministic `project_state.upsert` handoff |
| [`ana-v0.1-negative.json`](test-vectors/ana-v0.1-negative.json) | Version, schema, sequence, causality, required-semantics, and State Delta rejections |
| [`ana-v0.1-canonical.json`](test-vectors/ana-v0.1-canonical.json) | Unicode key ordering |
| [`ana-v0.1-memory-state.json`](test-vectors/ana-v0.1-memory-state.json) | Provider-neutral Memory/Project State/Policy import |

From a clean checkout with Python 3 and a JDK:

```bash
python3 -m conformance.run_phase7_suite
```

The suite compiles `conformance/independent-java/AnaV01Node.java` to a temporary
directory and runs both Python ↔ Java directions. A third-party implementation
should add itself as another independently implemented node and run the same
vectors; it must not reuse the reference node's codec, reducer, or Memory Store.

## Not included in this claim

This conformance level does not cover Codon, compact encoding, byte transforms,
Provider API integration, model quality, tool execution, encryption,
authentication, multi-agent behavior, cross-device synchronization, conflict
resolution, or complete Memory schemas. See [limitations](limitations.md).
