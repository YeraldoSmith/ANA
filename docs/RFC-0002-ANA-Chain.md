# RFC-0002: ANA Chain Layer

[English](RFC-0002-ANA-Chain.md) | [简体中文](RFC-0002-ANA-Chain.zh-CN.md)

- **Status**: v0.1 Minimal Core Frozen (Draft)
- **Version**: 0.1
- **Date**: 2026-08-11
- **Author / Editor**: YeraldoSmith
- **Dependencies**: [RFC-0001](RFC-0001-Architecture.md), [RFC-0003](RFC-0003-Envelope.md)

## Abstract

The ANA Chain Layer is the information representation, semantic mapping, and state synchronization layer between ANA nodes. It defines how canonical task/state events are organized into streams according to a fixed, versioned, verifiable processing chain and recovered to the same canonical representation at the receiver.

The ANA Chain does NOT provide encryption, authentication, or transport security. These are the responsibility of TLS, HTTPS, WebSocket security configurations, and the deployment environment's authentication mechanisms.

## 1. Scope and Responsibilities

The ANA Envelope addresses "how tasks are described"; the ANA Chain addresses "how tasks, Memory deltas, and Agent state are represented, transmitted, and synchronized between nodes." Its responsibilities are:

1. **Stream transformation**: Canonicalization, framing, and fixed-rule transformation of data streams;
2. **Semantic Codon mapping**: Expressing recurring structured concepts using a versioned dictionary;
3. **State Synchronization**: Transmitting incremental events for tasks, Memory, and collaborative state;
4. **Reversible transformation**: For chains declared reversible, recovering the same canonical input.

The ANA Chain does NOT require that natural language be encoded as Codons, nor does it claim that all tasks will thereby save tokens or improve model intelligence.

## 2. Canonical Stream

Before entering the Chain, the sender MUST convert the input to canonical representation:

- Using the protocol-defined schema;
- Using UTF-8;
- Applying deterministic ordering to object keys;
- Preserving protocol version, Chain identifier, and dictionary version;
- Not implicitly depending on local language, object addresses, or undeclared Provider behavior.

The v0.1 canonical payload uses JSON text: UTF-8, object keys sorted in ascending Unicode code point order, array order preserved, no extraneous whitespace. In Python, the reference encoding for this rule is `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. The receiver MUST be able to parse the result into the same JSON value after dechaining.

**Phase 7 clarification:** Canonical JSON objects MUST NOT contain duplicate member names; strings MUST consist of valid Unicode scalar value sequences. Receivers MUST reject JSON that fails either condition before canonical comparison and MUST NOT continue processing according to local parser behaviors such as "last duplicate key wins."

## 3. Fixed Chain

A Chain consists of a `chain_id`, `chain_version`, and a Chain Instruction Set (CIS) executed in order.

```json
{
  "chain_id": "ana-core-chain",
  "chain_version": "0.1",
  "instructions": ["CANONICALIZE", "MAP_CODONS", "FRAME", "TRANSFORM", "EMIT"]
}
```

"Fixed" carries the following normative meaning:

- The sender MUST NOT dynamically define new operations or change operation order from model output;
- Instruction semantics are uniquely determined by the corresponding `chain_id` and version;
- The same input, same Chain, and same dictionary MUST produce the same output;
- A receiver that does not support the Chain MUST request or use the canonical fallback, or explicitly reject;
- The sender MUST NOT assume that a receiver without declared support can understand private transformations.

## 4. Chain Instruction Set (CIS)

v0.1 defines the following conceptual instructions. They define processing order and do not mandate any specific programming language implementation.

| Instruction | Input | Output | Requirement |
| --- | --- | --- | --- |
| `CANONICALIZE` | Protocol object | canonical JSON | Required; processed per Section 2 rules |
| `MAP_CODONS` | canonical JSON | Dictionary-identified structured representation | Optional; MUST record dictionary ID/version |
| `FRAME` | Representation stream | Bounded frame sequence | Required; each frame MUST identify its stream |
| `TRANSFORM` | Frame payload | Transformed payload | Optional; operations MUST be fixed-defined by the Chain |
| `EMIT` | Frame | Transport-sendable data | Required; includes version metadata |

The receiver executes in reverse: `PARSE`, `INVERSE_TRANSFORM` (if applicable), `UNMAP_CODONS` (if applicable), and canonical JSON parsing.

### 4.1 v0.1 Reference Transformations

The reference implementation provides three byte transformations — `reverse`, `rotate_left`, and `xor_a5` — for testing determinism and reversibility. They are not security algorithms, not mandatory for production implementations, and do not represent ANA's final optimization approach.

Any new `TRANSFORM` MUST define its input/output, determinism, inverse operation (if declared reversible), version range, and test vectors.

## 5. Codon

A Codon is a short, stable, versioned, dictionary-lookup protocol semantic identifier. It is used for recurring, structured, cross-language concepts and is NOT a replacement for free text or a mechanism to hide semantics.

The v0.1 Codon dictionary SHOULD have the following structure:

```json
{
  "dictionary_id": "ana-core",
  "dictionary_version": "0.1",
  "entries": [
    {"id": "C:001", "meaning": "capability.code_generation"},
    {"id": "A:010", "meaning": "action.write_file"},
    {"id": "M:020", "meaning": "memory.preference"}
  ]
}
```

Codon rules:

- `id` MUST be unique within the dictionary version;
- `meaning` MUST point to a publicly readable specification entry;
- Unknown Codons MUST be preserved as unknown or fall back to canonical text; they MUST NOT be guessed by the receiver;
- Codons only optimize/standardize structured fields; user text, long text, and unknown concepts MUST be preserved as payload;
- Display language MAY be localized, but the protocol meaning is determined by the dictionary entry.

## 6. State Synchronization

State synchronization is accomplished through ordered event frames, not by retransmitting the entire conversation or complete Agent internal state each round. v0.1 defines the following minimal event shape:

```json
{
  "event_id": "uuid",
  "stream_id": "task-or-device-stream-id",
  "parent_event_id": "optional-causal-parent",
  "sequence": 42,
  "kind": "memory.upsert",
  "payload": {"record_ref": "mem_xxx"},
  "chain_id": "ana-core-chain",
  "chain_version": "0.1"
}
```

- `event_id` MUST be unique within its producing node;
- `stream_id` identifies the same task or synchronization stream;
- `sequence` MUST be monotonically increasing within the same stream of a single sender;
- `parent_event_id` MAY express explicit causal relationships;
- `kind` expresses the event category, e.g., task progress, Memory update, policy decision, or tool result;
- `payload` MUST conform to the schema corresponding to `kind` and MUST NOT contain unauthorized secrets.

v0.1 defines event encapsulation and ordering semantics but does NOT define offline conflict merging, global clocks, cross-node deletion conflicts, or distributed consensus. Implementations encountering events that cannot be safely ordered or merged MUST preserve the conflict and hand it to the Local Runtime/user for handling, rather than silently overwriting.

## 7. Session Negotiation and Version Control

Nodes SHOULD exchange capability declarations before first transmission:

```json
{
  "protocol_versions": ["0.1"],
  "supported_chains": [{"id": "ana-core-chain", "versions": ["0.1"]}],
  "dictionaries": [{"id": "ana-core", "versions": ["0.1"]}],
  "max_frame_bytes": 65536
}
```

Negotiation rules:

1. Select the highest protocol, Chain, and dictionary version supported by both sides;
2. When no common Chain or dictionary exists, use unmapped, untransformed canonical JSON event stream;
3. When no common protocol version exists, terminate the session and report incompatibility;
4. Each frame MUST be labeled with the actually selected `chain_id` and `chain_version`;
5. The receiver MUST NOT assume compatibility based on identically-named private Chains.

### 7.1 `ana-core-chain` v0.1 Minimal Interoperability Profile

Phase 1 freezes the following minimal profile. It is used to verify two independent nodes and does NOT require implementation of Codons or byte transformations.

```json
{
  "protocol_version": "0.1",
  "chain_id": "ana-core-chain",
  "chain_version": "0.1",
  "dictionary_id": null,
  "dictionary_version": null,
  "message_id": "unique-message-id",
  "stream_id": "task-or-device-stream-id",
  "sequence": 0,
  "payload_type": "envelope",
  "payload": "canonical JSON text",
  "transforms": []
}
```

This profile is the canonical fallback for the ANA Chain and the minimum interoperability requirement for v0.1. Codons and `TRANSFORM` remain defined Chain mechanisms but are NOT required implementations for this profile.

## 8. Reversible Transformation Principle

If a Chain or an instruction within it declares itself "reversible," the receiver at the same version MUST be able to recover the same canonical input from that output. Reversibility applies to representational transformations, not to intentional abstraction.

In particular, Summary Memory, Semantic Memory, and User Preference derived conclusions MAY lose original details; they MUST record provenance and abstraction relationships and MUST NOT be labeled as the product of a reversible Chain.

### 8.1 v0.1 State Delta

Phase 1 uses `payload_type: "state_delta"` to express State Deltas. Its canonical payload MUST include the `project_state.upsert` kind with the required fields specified in this section.

## 9. Security Considerations

The ANA Chain does NOT encrypt data. When confidentiality, integrity, node authentication, or anti-replay protection is required, the deployment MUST use TLS, authenticated sessions, signatures, or other audited security mechanisms. Codons, transformations, short IDs, or byte XOR operations are NOT security controls.

## 10. Interoperability Test Requirements

A Chain implementation SHOULD at minimum test:

- Same encoding result from the same canonical input across independent implementations;
- Round-trip recovery of a reversible Chain;
- Canonical fallback for unknown Chains/dictionaries;
- Unknown Codons not being misinterpreted;
- Event sequence order preserved within the same stream;
- Conflicts that cannot be safely handled being explicitly reported.

Fixed inputs and expected outputs are located at [`test-vectors/ana-v0.1-minimal.json`](test-vectors/ana-v0.1-minimal.json), with execution rules at [`test-vectors/README.md`](test-vectors/README.md).
