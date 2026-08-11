# Related Work and System Boundaries

ANA does not claim to invent local state ownership, agent interoperability,
tool protocols, long-term Memory, or portable agent configuration. This page
places the v0.1 Draft beside related work and explains the narrower boundary
ANA currently tests: **a Local Runtime owns selected state, Memory, and policy;
models are replaceable compute providers.**

The comparisons describe primary scopes, not compatibility guarantees or
feature rankings. ANA may compose with some of these systems in a future design,
but no such integration is specified or validated in v0.1.

## MCP

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs/learn/architecture)
defines a client/server protocol for connecting AI applications to tools,
resources, prompts, and related lifecycle/transport behavior. MCP answers how
a host accesses external capabilities and context.

ANA does not replace MCP. ANA v0.1 says that a Local Runtime—not a model or
Provider—owns its selected Memory, Project State, and Safety Policy. An ANA
runtime could use MCP as a tool/resource integration layer, but that composition
is outside this draft.

## A2A

[Agent2Agent (A2A)](https://google-a2a.github.io/A2A/specification/) targets
communication and task collaboration among independent, potentially opaque
agent systems, including capability discovery and task interaction. Its design
does not require participants to expose their internal memory or tools.

ANA does not replace A2A. A2A is aimed at agent-to-agent collaboration; ANA
v0.1 has intentionally not specified multi-agent coordination. ANA's current
focus is the local state boundary a runtime preserves when it changes compute
Provider. An implementation may use both boundaries, but v0.1 defines no
mapping between them.

## Agent Protocol

The public [Agent Protocol documentation](https://agent-protocol.gitbook.io/agent-protocol-docs)
currently presents Agent Protocol as a payment layer for AI agents. That is a
different problem from local Memory ownership and State Delta conformance.
ANA makes no payment, settlement, identity, or economic-authorization claim.

## Agent Host Protocol

[Agent Host Protocol (AHP)](https://microsoft.github.io/agent-host-protocol/)
describes synchronized multi-client state for AI agent sessions and uses
JSON-RPC types across host channels. It is a host/session protocol with its own
state model and transport choices.

ANA's minimal profile instead tests canonical task/state handoff between
independent nodes and a local model-provider boundary. It is not an AHP
replacement, and ANA does not claim AHP's session, authorization, or
multi-client feature set.

## Portable Agent Memory

“Portable Agent Memory” is a problem area rather than one universally settled
standard. A recent research proposal named
[Portable Agent Memory](https://arxiv.org/abs/2605.11032) explores structured,
cryptographically verified transfer across heterogeneous agents. Its design and
claims are independent of ANA and are not adopted here.

ANA v0.1 only defines a small, Local-Runtime-owned portable Memory boundary and
does not specify cryptographic provenance, Merkle structures, injection
resistance, full memory rehydration, or cross-device conflict resolution.

## Mem0

[Mem0](https://docs.mem0.ai/platform/overview) is a managed memory layer for AI
agents, offering memory lifecycle and retrieval infrastructure. It is a product
and service approach to keeping applications context-aware.

ANA does not replace a memory engine. Its Memory RFC says who owns and may
disclose selected records in a local architecture; it does not standardize
retrieval ranking, vector stores, graphs, or managed Memory operations. A
runtime could use a memory system such as Mem0 behind its own Local Runtime
boundary, but this repository has not implemented that integration.

## Letta

[Letta](https://docs.letta.com/) is a platform and harness for building
stateful agents. Its [AgentFile format](https://docs.letta.com/guides/core-concepts/agent-file)
packages agent configuration, memory, tools, model settings, and more for
portable stateful agents.

ANA does not replace Letta or AgentFile. Letta/AgentFile package a richer agent
and runtime configuration; ANA v0.1 tests a smaller provider-neutral Envelope
and State Delta profile. ANA does not claim equivalent portability, tool
configuration, or agent reconstruction.

## Summary

The useful distinction is a system boundary, not a claim of novelty:

```text
ANA Local Runtime: owns selected user/project state, Memory, and policy
Provider: replaceable computation behind that local boundary
```

MCP, A2A, Agent Protocol, AHP, memory engines, and stateful-agent platforms
solve adjacent or overlapping problems at different layers. ANA v0.1 is too
small and too early to be a replacement for any of them.
