# RFC-0003: ANA Envelope Layer

[English](RFC-0003-Envelope.md) | [简体中文](RFC-0003-Envelope.zh-CN.md)

- **Status**: v0.1 Minimal Core Frozen (Draft)
- **Version**: 0.1
- **Date**: 2026-08-11
- **Author / Editor**: YeraldoSmith
- **Dependencies**: [RFC-0001](RFC-0001-Architecture.md), [RFC-0002](RFC-0002-ANA-Chain.md), [RFC-0004](RFC-0004-Memory-System.md)

## Abstract

`ANAEnvelope` is a Provider-neutral task description object. It allows the Local Runtime to express task intent, required capabilities, available context, Memory references, and execution expectations in a unified format, which the Router and Adapter then use to select/invoke specific compute capabilities.

The Envelope is not a complete communication protocol, not an identity credential, and not a secret container. The Envelope is transmitted or synchronized within the ANA Chain as a canonical task event.

## 1. Data Model

The v0.1 minimal Envelope is:

```json
{
  "version": "0.1",
  "task_id": "uuid",
  "intent": "generate",
  "capabilities": ["code_generation"],
  "input": {"text": "Generate Java Hello World"},
  "context": {"language": "java"},
  "memory_refs": ["mem_xxx"],
  "policy": {"execution_mode": "sandbox_first"}
}
```

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `version` | Yes | string | Envelope schema version; `"0.1"` for v0.1 |
| `task_id` | Yes | string | Globally unique task identifier, UUID recommended |
| `intent` | Yes | string | Result-oriented short verb, e.g., `generate`, `analyze`, `plan` |
| `capabilities` | Yes | string array | Ordered set of required Provider capabilities, e.g., `code_generation` |
| `input` | Yes | object | Structured input that MUST be processed for this task |
| `context` | No | object | Non-secret, serializable auxiliary context |
| `memory_refs` | No | string array | Memory identifiers managed by the Local Runtime |
| `policy` | No | object | Execution mode expected by the caller; MUST NOT weaken local hard policies |

Unrecognized optional fields MAY be retained or ignored by the receiver; they MUST NOT alter the semantics of v0.1 required fields.

## 2. Creation and Routing

1. An Observer or Application receives the user request.
2. The Planner creates an Envelope declaring the capabilities needed to complete the task.
3. The Memory component associates only policy-permitted records via `memory_refs`.
4. The Router selects an available Provider based on `capabilities`.
5. The Adapter translates the Envelope into the Provider's native request.

`capabilities` expresses requirements, not preferred vendors. If no Provider supports all required capabilities, the Router MUST return an interpretable unroutable error and MUST NOT silently degrade task semantics.

## 3. Context and Memory Boundary

`context` and `memory_refs` have distinct roles:

- `context` is immediate, non-secret hint information for this task, e.g., language, format, project scope.
- `memory_refs` are references to local records; they do NOT equate to sending the entire Memory content to the Provider.

The Local Runtime MUST resolve, summarize, or filter Memory within the scope permitted by policy; it MUST NOT automatically send raw chat history merely because a reference exists. Passwords, access tokens, private keys, and other secrets MUST NOT be transmitted as ordinary `context`, `input`, or portable Memory content.

## 4. Policy Semantics

`policy` expresses the task requester's expectations, e.g.:

```json
{"execution_mode": "sandbox_first"}
```

It is NOT an authorization upgrade to the Local Safety Policy. The Local Runtime MUST be able to impose stricter restrictions; for example, when the caller requests automatic execution, the local policy MAY still require confirmation or deny the action.

## 5. Provider Results and Action Proposals

The Adapter SHOULD convert the Provider response into a `ProviderResult`:

```json
{
  "provider_id": "example-code-provider",
  "output": {"text": "...", "artifacts": []},
  "proposed_actions": [
    {"kind": "write_file", "target": "generated/Hello.java", "content": "..."}
  ]
}
```

`output` is the result content; `proposed_actions` are explicit, structured side-effect proposals. The Provider or Adapter MUST NOT directly execute `proposed_actions`. All actions MUST pass through the Safety Policy and Executor defined in RFC-0005.

## 6. Serialization and Versioning

The Envelope MUST be encoded as canonical JSON before entering the ANA Chain: UTF-8, object keys sorted in ascending Unicode code point order, array order preserved, no extraneous whitespace, explicit `version`. In Python, the reference encoding for this rule is `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. The Envelope version describes the task object schema only; it is distinct from the Chain version and the Codon dictionary version.

When a receiver does not support the `version`, it MUST explicitly report incompatibility; it MUST NOT guess-map unknown required fields to existing fields.

### 6.1 v0.1 Minimal Verification Profile

Envelopes used in fixed vectors MUST contain only the fields listed in Section 1, and `version` MUST be `"0.1"`. `task_id` MUST be a non-empty string, `intent` MUST be a non-empty string, `capabilities` MUST be an array containing at least one non-empty string, and `input` MUST be an object. `context`, `memory_refs`, and `policy`, if present, MUST be an object, a string array, and an object respectively.

This profile does NOT establish a global vocabulary for `intent`, `capabilities`, or `policy` beyond the test vectors; new meanings requiring cross-implementation dependency MUST first be defined through an RFC.

**Phase 7 clarification:** The required Envelope fields for this profile are only the fields listed in this section; v0.1 does not define a "required for all receivers even if unknown" marker for unknown fields. Unknown members are therefore only ignorable or retainable extensions and MUST NOT change v0.1 Core semantics. If a new field needs to be required, a new version or profile MUST be defined; receivers MUST then explicitly report incompatibility rather than guessing its meaning.

## 7. Error Boundaries

At minimum, the following failure cases SHOULD be distinguished:

- `invalid_envelope`: Missing or incorrectly typed required fields;
- `unsupported_envelope_version`: Cannot process `version`;
- `no_capable_provider`: No Provider satisfies `capabilities`;
- `memory_access_denied`: Policy prohibits resolving or disclosing a Memory entry;
- `policy_restricted`: Task expectations conflict with local mandatory policy;
- `provider_failure`: The Adapter or Provider failed to produce a valid result.

Error content MUST NOT disclose the secret content of rejected Memory or sensitive details of the local Safety Policy.
