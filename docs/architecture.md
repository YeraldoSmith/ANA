# ANA v0.1 architecture

## Purpose

ANA defines the boundary between a person's local agent runtime and the
reasoning services it may use.  It is intended to make user memory, task
intent, safety decisions, and provider choice portable instead of binding them
to a single model vendor.

## Design principles

1. **Memory is not model weights.** Long-lived facts, preferences, and task
   summaries use an interoperable data model and can move independently of a
   provider or device.
2. **The local runtime is the authority.** It owns identity, consent, policy,
   memory, routing, and access to local tools.
3. **Models are capability providers.** A model is selected for declared
   capabilities such as `code_generation` rather than by a hard-coded vendor
   identity.
4. **No action bypasses policy.** Model output proposes an action; the local
   runtime decides whether to allow, request confirmation, sandbox, or deny it.
5. **Adapters preserve the standard boundary.** v0.1 adapts existing APIs;
   providers do not need to change their models to participate.

## Runtime flow

```text
User request
  -> local runtime: create ANAEnvelope + retrieve relevant memory
  -> router: select a declared capability provider
  -> adapter: translate the envelope to that provider's native request
  -> provider: return a result and proposed actions
  -> policy gate: allow / confirm / sandbox / deny each action
  -> executor: perform allowed actions and append auditable events
```

## Trust boundary

The model, including an official provider, is outside the local trust boundary.
Provider trust can influence defaults, but cannot override non-negotiable local
policy.  High-impact actions (for example credential access, data exfiltration,
or destructive filesystem operations) require a stricter policy regardless of
provider trust.

## Memory migration

Devices exchange a `MigrationProfile`, not opaque agent internals.  A profile
may contain identity references, preferences, semantic memories, skill tags,
and compatible workflow state.  The target device separately discovers its own
hardware, models, permissions, and tool availability.  A resource-constrained
target can request the `portable` tier and omit caches and device-only state.
