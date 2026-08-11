# RFC-0001: ANA v0.1 Architecture

[English](RFC-0001-Architecture.md) | [简体中文](RFC-0001-Architecture.zh-CN.md)

- **Status**: v0.1 Minimal Core Frozen (Draft)
- **Version**: 0.1
- **Date**: 2026-08-11
- **Author / Editor**: YeraldoSmith
- **Related RFCs**: [RFC-0002](RFC-0002-ANA-Chain.md), [RFC-0003](RFC-0003-Envelope.md), [RFC-0004](RFC-0004-Memory-System.md), [RFC-0005](RFC-0005-Agent-Runtime.md)

## Abstract

ANA (Agent Network Architecture) defines an architecture and protocol family centered on a local Agent as the hub of user state. It enables different Agents, devices, and model providers to collaborate through a unified task representation, semantic mapping, and state synchronization mechanism.

ANA does not train models, hold user identity, or replace HTTPS, WebSocket, TLS, or authentication. Cloud or local models are replaceable compute providers; the user's Memory, preferences, permissions, task state, and final execution authority belong to the local ANA Runtime.

## 1. Terminology and Conventions

The key words "MUST", "MUST NOT", "SHOULD", and "MAY" in this document describe implementation requirements for ANA v0.1.

- **Local Agent / Local Runtime**: The ANA control plane running in a user-controlled environment.
- **Provider**: A cloud model, local model, or specialized Agent service that provides inference, generation, analysis, or other capabilities.
- **Adapter**: A component that translates between ANA representation and a Provider's native interface.
- **Node**: A Runtime, Agent, or compatible service that can send or receive ANA Chain streams.
- **Canonical representation**: A standard representation encoded according to ANA schema, UTF-8, and deterministic field ordering.
- **Memory**: User or project state stored independently of model parameters; see RFC-0004.

## 2. Design Goals

ANA v0.1 aims for the following:

1. **Local state sovereignty**: The Local Agent is the final arbiter of user state, authorization, and policy.
2. **Separation of model and memory**: Model weights, context caches, and user long-term Memory are distinct objects and MUST NOT be forcibly coupled.
3. **Capability-oriented interchange**: Upper-layer tasks request capabilities (e.g., `code_generation`) rather than being locked to a specific vendor.
4. **AI Node communication and synchronization**: Tasks, structured semantics, and State Deltas can be transmitted and recovered between compatible nodes.
5. **Least privilege**: Only the minimum context and permissions required to complete the current task are provided to the Provider.
6. **Independently implementable**: The protocol MUST NOT depend on any proprietary Runtime, model, or service to be interpreted.

## 3. Non-Goals

ANA v0.1 does NOT define or guarantee:

- Foundation model training, model hosting, or model capability ratings;
- General-purpose chat products or complete personal assistant products;
- Encryption, key management, transport authentication, or access token formats;
- Any reversible transformation used as a secrecy mechanism;
- Proven universal token compression or a "model universal language";
- Autonomous multi-Agent societies, blockchains, tokens, or economic systems.

## 4. Layered Model

ANA implementations MUST understand the following logical layers. Adjacent layers MAY be implemented in the same process, but their responsibilities MUST NOT be conflated.

```text
┌─────────────────────────────────────────────────────────────┐
│ Application Layer                                            │
│ User tasks, tool results, Provider Adapters, app rendering   │
├─────────────────────────────────────────────────────────────┤
│ ANA Envelope Layer                                           │
│ intent, capabilities, context, memory_refs, policy           │
├─────────────────────────────────────────────────────────────┤
│ ANA Chain Layer                                              │
│ Fixed Chain, instructions, Codons, state events, versioning, │
│ reversible recovery                                          │
├─────────────────────────────────────────────────────────────┤
│ Transport Layer                                              │
│ HTTPS / WebSocket / local IPC                                │
└─────────────────────────────────────────────────────────────┘
```

### 4.1 Application Layer

The Application Layer creates user-visible tasks, consumes results, and connects to specific Providers through Adapters. It MAY use natural language, GUI, CLI, or other product forms; these forms are not part of the ANA protocol.

### 4.2 ANA Envelope Layer

The Envelope is a Provider-neutral task description. It expresses "what to do, what capabilities are needed, which context references are available, and how execution is expected," without prescribing how bytes are transmitted or state is synchronized. The specific format is defined in RFC-0003.

### 4.3 ANA Chain Layer

The Chain is the communication and state synchronization core of ANA. It organizes canonical task and state events into versioned streams, and defines fixed processing chains, semantic Codons, State Deltas, and reversible recovery. The specific format is defined in RFC-0002.

### 4.4 Transport Layer

The Transport Layer is responsible for actual delivery between nodes. v0.1 MAY be built on HTTPS, WebSocket, or local IPC. TLS, server authentication, user authentication, session management, and network access control are the responsibility of the Transport or deployment environment; they are NOT provided by the ANA Chain.

## 5. Trust and Control Boundary

```text
User
  │ authorization, preferences, control
  ▼
Local Agent / Runtime ──────── ANA Envelope / Chain ───────► Provider
  │ selects context, evaluates actions, records state      │ inference/generation
  ▼                                                         ▼
Safety Policy → Executor → Local tools              ProviderResult
```

The Local Agent MUST retain the following powers:

- Decide which Memory is available for a given task;
- Decide which Provider is selected;
- Separate the Provider's output from `ProposedAction`;
- Allow, require confirmation, sandbox, or reject real actions;
- Maintain a local record of tasks and state events.

Providers MUST NOT bypass these boundaries by virtue of being "official" or "high-trust." A Cloud Model is a compute capability, NOT the owner of user identity, Memory, or the direct controller of local tools.

## 6. Interoperability Principles

Compatible implementations SHOULD:

1. Support or explicitly reject specific protocol, Chain, and dictionary versions;
2. When no common Chain/Codon dictionary exists, fall back to canonical representation rather than guessing meaning;
3. Maintain separation of Provider Adapter and Executor;
4. Allow portable Memory to be exported, imported, and audited within the scope of user authorization;
5. Provide clear errors for version incompatibility, policy rejection, and unresolvable state events.

## 7. Security Considerations

ANA is responsible for information representation, state synchronization, and semantic mapping; it is NOT an encryption protocol. When deploying ANA:

- Cross-network transport SHOULD use mature transport protection such as TLS;
- Node and user identity SHOULD use authentication mechanisms provided by the deployment environment;
- Secrets, passwords, and access tokens MUST NOT be placed in ordinary Envelopes or portable Memory;
- Any side-effect requests returned by a Provider MUST first pass through the Local Runtime's Safety Policy;
- Reversible Chain transformations MUST NOT be treated as obfuscation, encryption, or privacy guarantees.

## 8. Versioning Policy

ANA's protocol version, Chain version, and Codon dictionary version are independent of each other. An implementation MAY only send the corresponding representation when both sides have a commonly supported version. Unknown versions MUST fall back to a common canonical representation or explicitly fail.

Changes that break field semantics, remove required fields, or alter Chain instruction meanings MUST be published as new compatibility-boundary versions; new optional fields and new optional Codons MAY be published as minor versions under compatibility rules.

### 8.1 v0.1 Minimal Core Freeze Scope

To complete Phase 1 interoperability verification, the following are frozen within v0.1:

- Layered responsibilities and the Local Runtime's local authority over user state, Memory, policy, and execution;
- Required fields of `ANAEnvelope` and the proposal-execution separation of `ProviderResult`/`ProposedAction`;
- The canonical JSON fallback frame for `ana-core-chain` version `0.1`;
- Chain behavior without Codons and without byte transformations;
- Minimal semantics of the `project_state.upsert` State Delta;
- Fixed test vectors and pass conditions for this profile.

Compatible implementations MUST NOT assume cross-implementation semantics for behaviors not explicitly specified within this freeze scope. Implementations MAY use additional behaviors locally, but MUST NOT send them to other nodes under v0.1 interoperability claims; such behaviors require additional RFCs before they can be shared.

## 9. Implementation Roadmap

### Phase 1: Minimal Protocol Verification

- Freeze minimal terminology, Envelope, Chain, and Memory data boundaries from the v0.1 RFCs.
- Provide canonical representation, fixed Chain fallback, and State Delta test vectors; the Codon dictionary is reserved as a defined but optional object for subsequent verification.
- Verify that two minimal nodes can exchange a task event and a State Delta, and can recover the canonical representation.
- Verify that a Provider can only propose actions and cannot bypass the local Safety Policy.

### Phase 2: Reference Implementation

- Implement a persistable Local Runtime, Memory Store, Router, Policy, and Executor interfaces.
- Implement v0.1 Chain encoding/decoding, session negotiation, event logging, and portable Memory import/export.
- Verify boundaries with one real Provider Adapter and one deterministic Mock Adapter.
- Establish interoperability tests for cross-device migration, path out-of-bounds rejection, version rollback, and reversibility.

### Phase 3: Ecosystem Adapters

- Provide an Adapter development guide, capability declaration format, test suite, and compatibility samples.
- Support model vendors, local model communities, and independent teams in maintaining their own Adapters.
- Use interoperability between at least two independent Runtimes and at least two independent Adapters as the ecosystem validation threshold.
- Based on measurement results, decide which parts of the Codon and Chain mechanisms become core and which remain optional extensions.
