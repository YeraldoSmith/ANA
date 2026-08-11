# ANA Protocol v0.1 draft

## Status and terminology

This is an exploratory, non-normative draft.  The key words **MUST**,
**SHOULD**, and **MAY** are used in their usual RFC sense only when this draft
becomes normative.

## Envelope

Every routed task is represented by a versioned envelope.

```json
{
  "version": "0.1",
  "task_id": "a UUID",
  "intent": "generate",
  "capabilities": ["code_generation"],
  "input": {"text": "Generate a Java hello-world program"},
  "context": {"language": "java"},
  "memory_refs": ["mem_123"],
  "policy": {"execution_mode": "sandbox_first"}
}
```

- `version` identifies the envelope grammar.
- `intent` is a short verb describing the requested outcome.
- `capabilities` is an ordered list of required provider capabilities.
- `input` is task-specific, serializable input.
- `context` contains non-secret hints; secrets are passed only through a
  local secret-handling mechanism, never a normal envelope.
- `memory_refs` references local records. An adapter receives only the records
  selected for this task, subject to policy.
- `policy` declares the caller's desired mode; the local policy engine may
  enforce a stricter one.

## Provider contract

A provider adapter accepts an envelope and returns a `ProviderResult`:

```json
{
  "provider_id": "example-code-provider",
  "output": {"text": "...", "artifacts": []},
  "proposed_actions": [
    {"kind": "write_file", "target": "Hello.java", "content": "..."}
  ]
}
```

An adapter MUST NOT directly execute an action.  The local runtime owns action
approval and execution.

## Memory record

```json
{
  "id": "mem_123",
  "kind": "preference",
  "content": {"security_priority": "high"},
  "portability": "portable",
  "created_at": "2026-08-11T00:00:00+00:00"
}
```

`portability` is one of `portable`, `device_local`, or `ephemeral`.

## ANA Chain Layer

ANA Chain is the protocol layer below `ANAEnvelope`: it carries canonical task
events, semantic codons, and state deltas between ANA nodes. A Chain is fixed,
versioned, deterministic, and either mutually supported by both peers or
replaced by a canonical fallback representation. Its responsibilities are:

1. stream transformation;
2. semantic codon mapping;
3. state synchronization;
4. reversible restoration when the selected transform declares reversibility.

The v0.1 implementation provides only a demonstrably reversible byte-stream
reference codec. It is not encryption or a semantic-compression claim. The
full protocol proposal is in [ANA Chain Layer](ana-chain.md).
