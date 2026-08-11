# Security Considerations

ANA v0.1 is not a security protocol and has not received a security audit.
Canonical JSON, Chain metadata, Codon concepts, and reversible transforms do
not provide encryption, authentication, authorization, integrity protection, or
replay protection.

## Boundaries in the draft

- **Transport security:** deployments need TLS and appropriate session/authentication controls. ANA does not replace them.
- **Memory disclosure:** Memory belongs to the Local Runtime. `memory_refs` do not authorize automatic disclosure, and secrets, credentials, and private keys must not be placed in ordinary Envelope `input`, `context`, or portable Memory.
- **Provider output:** a Provider can return text or structured proposed actions; it does not receive authority to execute them or overwrite local state.
- **Safety Policy:** the Local Runtime retains final allow/confirm/sandbox/deny authority. A task policy cannot weaken a stricter local rule.
- **State synchronization:** an accepted State Delta is a state proposal subject to local validation and policy. The minimal profile validates sequence/causality but does not solve distributed consensus or cross-device conflict merging.

## What the repository tested

The tests show local rejection of a workspace-escaping write proposal and
offline rejection of invalid provider state claims, stale Memory references,
sequence rollback, and policy-violating proposals. These are narrow behavioral
tests, not an audit or proof that an application is secure.

## Deployment guidance

Do not expose an ANA Runtime to untrusted networks without independently
designed authentication, authorization, rate limiting, logging, secret
management, input validation, and incident response. Treat Provider responses,
tool metadata, and retrieved Memory as untrusted until the Local Runtime has
validated them. Review the RFCs and [limitations](limitations.md) before any
real-world deployment.
