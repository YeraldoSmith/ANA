# RFC-0005: ANA Local Agent Runtime

[English](RFC-0005-Agent-Runtime.md) | [简体中文](RFC-0005-Agent-Runtime.zh-CN.md)

- **Status**: v0.1 Minimal Core Frozen (Draft)
- **Version**: 0.1
- **Date**: 2026-08-11
- **Author / Editor**: YeraldoSmith
- **Dependencies**: [RFC-0001](RFC-0001-Architecture.md), [RFC-0002](RFC-0002-ANA-Chain.md), [RFC-0003](RFC-0003-Envelope.md), [RFC-0004](RFC-0004-Memory-System.md)

## Abstract

The ANA Local Agent Runtime is the control plane deployed in a user-controlled environment. It translates user requests into ANA Envelopes, selects appropriate compute capabilities, maintains Memory and Project State locally, and ensures that any real tool actions pass through the Safety Policy.

The Runtime MAY invoke cloud models, local models, or specialized Agents, but these Providers only supply compute capability. They are NOT the authority for user identity, Memory, or local execution permissions.

## 1. Required Components

A minimal ANA Local Agent Runtime MUST logically contain the following components. They MAY be implemented as modules, processes, or services, but their responsibilities MUST be distinguishable.

| Component | Responsibility |
| --- | --- |
| Observer | Receives user requests, environment events, and tool results; forms processable input facts |
| Memory | Stores, retrieves, migrates, and discloses records per RFC-0004 according to policy |
| Planner | Organizes requests into task intent, capability requirements, context, and execution expectations; creates Envelopes |
| Router | Selects Providers/Adapters based on capabilities and local availability; does NOT hardcode vendor identity as task semantics |
| Executor | Only executes permitted structured actions and reports results |
| Safety Policy | Evaluates Memory disclosure and action requests; returns allow, confirm, sandbox, or deny decisions |

## 2. Execution Flow

```text
Observer
  → Planner (creates ANAEnvelope)
  → Memory (selects minimum necessary context)
  → Router (selects capability provider)
  → Adapter / Provider (computation)
  → ProviderResult + ProposedActions
  → Safety Policy (evaluates each item)
  → Executor (only executes permitted actions)
  → Observer / Memory (records results and state events)
```

The key rule of this flow: a Provider's text output and real side effects MUST be separated. A model MAY suggest writing a file, running tests, or transferring data; only the Runtime's Safety Policy and Executor can turn suggestions into actual actions.

## 3. Observer

The Observer is responsible for collecting user input, environment changes, Provider results, and Executor results. It SHOULD:

- Identify the source and owning task of each input;
- Distinguish user input from automatically observed environment facts;
- NOT autonomously send environment data, file contents, or secrets to Providers;
- Provide traceable events for the Planner, Memory, and audit records.

The Observer is NOT responsible for deciding task plans, Provider selection, or tool authorization.

## 4. Memory

The Runtime's Memory component MUST follow RFC-0004. It is responsible for:

- Supporting task-to-local-record association via `memory_refs`;
- Retrieving, summarizing, and disclosing content according to the principle of least privilege;
- Managing the lifecycle of portable, device-local, and ephemeral records;
- Exporting/importing authorized Migration Profiles;
- Treating new records proposed by a Provider as candidates, not as unverified facts.

## 5. Planner

The Planner organizes user goals into `ANAEnvelope`. It MUST:

- Select an explicit `intent`;
- Declare the `capabilities` required to complete the task;
- Place immediate non-secret information in `input` or `context`;
- Reference necessary `memory_refs` rather than default-carrying all history;
- Propose `policy` expectations but MUST NOT bypass the Runtime's hard policies.

The Planner MAY use model-assisted reasoning, but the final Envelope MUST pass the Runtime's schema validation.

## 6. Router and Adapter

The Router MUST match primarily by capability: if a task requires `code_generation`, the Router selects a Provider that declares support for that capability. The selection algorithm MAY consider local availability, latency, cost, user preferences, or trust settings, but MUST NOT thereby bypass the Safety Policy.

The Adapter's responsibility:

```text
ANAEnvelope → Provider native request
Provider native response → ProviderResult + ProposedActions
```

The Adapter MUST maintain this boundary and MUST NOT directly invoke the Executor, silently alter Local Memory, or override local policy with Provider results.

## 7. Executor

The Executor only receives structured actions that have already passed through the Safety Policy. The v0.1 reference action form:

```json
{"kind": "write_file", "target": "generated/Hello.java", "content": "..."}
```

The Executor MUST:

- Verify that the action target remains within the authorized scope;
- Return success, failure, or cancellation results after execution;
- Hand results back to the Observer to form task/state events;
- NOT accept unadjudicated free-text commands as authorization.

## 8. Safety Policy

The Safety Policy is the final behavioral gate of the Local Runtime. It SHOULD at minimum be able to return these decisions for Memory disclosure and `ProposedAction`:

- `allow`: Permitted within defined bounds;
- `confirm`: Requires explicit user confirmation;
- `sandbox`: SHOULD be verified in an isolated environment before deciding;
- `deny`: MUST NOT be executed or disclosed.

The v0.1 reference implementation allows writing files within a designated workspace and rejects path traversal; other operations MAY require confirmation. Real deployments SHOULD define stricter rules based on operation category, data sensitivity, target scope, and user preferences.

Regardless of whether the Provider is official, third-party, or a local model, the Safety Policy MUST retain veto power.

## 9. Runtime State Synchronization

The Runtime uses the ANA Chain from RFC-0002 to transmit task events, Memory deltas, policy decisions, and tool results. It SHOULD:

- Assign `event_id`, `stream_id`, and `sequence` to synchronization events;
- Only synchronize state permitted by policy;
- Preserve conflicts on cross-node events that cannot be safely merged, rather than silently overwriting;
- Explicitly report Chain negotiation failures or version incompatibilities to upper layers.

v0.1 does NOT prescribe complex negotiations between autonomous Agents or automatic conflict merging. If a Runtime delegates subtasks, it SHOULD still maintain traceability of task origin, capability scope, and result provenance.

## 10. Security and Privacy Boundaries

- The Runtime MUST NOT treat a Provider as a user identity hub;
- The Runtime MUST NOT automatically expand data disclosure or execution permissions because a model is "trusted";
- The Runtime MUST NOT use ANA Chain transformations as a substitute for TLS, authentication, or secret management;
- The Runtime SHOULD retain sufficient local audit information to explain "why a particular Provider was chosen, what Memory was disclosed, and what action was permitted";
- The Runtime SHOULD allow users to manage portable Memory and explicit high-risk authorizations.

## 11. Current v0.1 Reference Implementation Boundaries

The current code implements simple in-memory records, a capability Router, a Mock Provider, a file-write policy gate, and an Executor. It does NOT yet implement real cloud Adapters, persistent auditing, full sandboxing, cross-device session negotiation, or automatic conflict merging. These limitations do NOT alter the responsibility boundaries in this RFC but MUST be honestly disclosed in products.
