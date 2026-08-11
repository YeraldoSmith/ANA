# RFC-0004: ANA Memory System

[English](RFC-0004-Memory-System.md) | [简体中文](RFC-0004-Memory-System.zh-CN.md)

- **Status**: v0.1 Minimal Core Frozen (Draft)
- **Version**: 0.1
- **Date**: 2026-08-11
- **Author / Editor**: YeraldoSmith
- **Dependencies**: [RFC-0001](RFC-0001-Architecture.md), [RFC-0003](RFC-0003-Envelope.md)

## Abstract

The ANA Memory System defines how user and project state is saved, evolved, migrated, and disclosed on demand — independently of model parameters. Its purpose is NOT to save unlimited full chat text, but to enable the Local Agent to form traceable, correctable, migratable long-term context under user authorization.

Memory belongs to the user-controlled Local Runtime. A Cloud Model MAY only receive filtered content within the policy scope of the current task; it MUST NOT inherently own or define user identity.

## 1. Core Principles

- Memory MUST be separated from model weights, Provider private caches, and device hardware state.
- Raw sources and derived conclusions MUST be distinguishable.
- Derived summaries, semantic, or preference models MUST NOT falsely claim lossless recovery of original records.
- Users SHOULD be able to view, correct, export, and delete their own portable Memory.
- The Runtime MUST follow the principle of least disclosure, rather than sending complete history to the Provider.

## 2. MemoryRecord

The v0.1 minimal record shape:

```json
{
  "id": "mem_xxx",
  "kind": "preference",
  "content": {"security_priority": "high"},
  "portability": "portable",
  "created_at": "2026-08-11T00:00:00+00:00"
}
```

| Field | Required | Description |
| --- | --- | --- |
| `id` | Yes | Stable record identifier within the Runtime |
| `kind` | Yes | Memory category defined in Section 3 of this RFC |
| `content` | Yes | Structured content matching `kind` |
| `portability` | Yes | `portable`, `device_local`, or `ephemeral` |
| `created_at` | Yes | Creation time with timezone |

Future implementations SHOULD add provenance, generator/model version, confidence, applicability scope, invalidation conditions, and revocation relationships; these fields are necessary audit metadata for Memory Evolution but are not yet implemented in the current reference code's persistence schema.

## 3. Memory Types

### 3.1 Raw Memory

Raw Memory consists of original conversations, file snippets, tool outputs, or event records. It is suitable for traceability and error correction and SHOULD NOT be re-sent in full to the model by default. Raw Memory typically contains significant privacy and context and MUST be strictly controlled by local policy.

### 3.2 Structured Memory

Structured Memory consists of explicit fields, entities, relationships, or task facts extracted from raw material — e.g., project name, language, to-do items, time ranges, or source links. It facilitates stable retrieval and cross-implementation processing.

### 3.3 Semantic Memory

Semantic Memory consists of verified or persistently reused high-level conclusions, e.g., "This project prioritizes security" or "The user primarily uses Java." It MUST retain sufficient information to trace its sources or update rationale, and MUST be correctable by the user.

### 3.4 User Preference

User Preference records the user's explicit or confirmed work preferences, e.g., explanation detail level, language choice, risk appetite. It is NOT an invisible profile; the user SHOULD be able to inspect, edit, export, and delete it.

### 3.5 Project State

Project State represents state associated with a specific project or task, e.g., current objectives, verified conclusions, to-do items, task phases, and artifact references. It MUST be separated from general user preferences to prevent one project's temporary state from incorrectly influencing another project.

## 4. Memory Evolution

To avoid infinitely re-reading all context, ANA uses the following evolution relationships:

```text
Raw Memory
  → Structured Memory / Summary Memory
  → Semantic Memory
  → User Preference or Project State reusable conclusions
```

Each evolution is an intentional abstraction and is NOT a reversible transformation of the ANA Chain. Implementations SHOULD preserve input sources, generation time, generator, applicability scope, and revocability relationships. If sources change or the user corrects conclusions, the Runtime SHOULD invalidate or regenerate related derived records.

## 5. Portability and Migration

`portability` values and rules:

- `portable`: Preferences, semantic conclusions, skill tags, or compatible project state that the user explicitly MAY carry across devices;
- `device_local`: Local paths, hardware probes, model caches, device permissions, and other non-directly-migratable state;
- `ephemeral`: Temporary context for the current session or short task.

Migration proceeds in the form of a `MigrationProfile`, not by copying the complete Agent process or model state. The receiving device MUST re-discover its own models, tools, permissions, and hardware capabilities. Target devices constrained by resources or privacy MAY receive only the minimal `portable` set.

## 6. Access and Disclosure

1. The Envelope only stores `memory_refs` and does NOT automatically include complete record content.
2. The Local Runtime MUST only resolve/filter records when the task requires it and user policy permits.
3. Before disclosing to a Provider, the Runtime SHOULD prioritize necessary structured or summary forms over raw material.
4. Secrets, tokens, and credentials MUST NOT be exported through general Memory or passed through ordinary Envelopes.
5. New Memory formed from Provider output MUST be treated as candidate records, processed by the Local Runtime and appropriate policy before being written.

## 7. Relationship to the ANA Chain

The ANA Chain MAY synchronize Memory references, events, and authorized portable deltas; it does NOT change Memory ownership. Memory summary/semantic evolution is NOT automatically reversible by virtue of using the Chain. Cross-device synchronization uses state events; the receiver MUST process them according to version, policy, and conflict handling rules.

## 8. Current v0.1 Boundaries

The current reference implementation provides only in-memory `MemoryRecord` storage and `portable` Migration Profile export. Persistent storage, retrieval ranking, encrypted storage at rest, conflict merging, automatic summarization, and user management interfaces are all outside the currently implemented scope.
