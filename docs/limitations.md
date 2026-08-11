# ANA v0.1 Draft Limitations

ANA v0.1 is deliberately a narrow, experimental minimal profile. It should not
be used as evidence of production-grade interoperability or security.

## Not implemented or not validated

- No Codon dictionary interoperability, compact Chain encoding, or general compression benefit.
- No multi-agent delegation, discovery, negotiation, or collaboration protocol.
- No cross-device synchronization, distributed conflict resolution, deletion semantics, or consensus.
- No real paired OpenAI ↔ Anthropic live interoperability result in this repository; only Adapter boundary contracts and offline deterministic continuity tests.
- No model-quality equivalence, long-horizon task success, cost, latency, or token-saving claim.
- No security audit, cryptographic identity, signatures, replay defense, or authorization scheme.
- No persistent Memory database, retrieval ranking, automatic summaries, complete Memory kind schemas, or user-management UI.
- No generic cross-language canonicalization profile for all JSON fractional/exponent numbers.
- No standardized Chain error-code taxonomy; the current suite checks matched rejection behavior.

## Evidence scope

The Phase 4–5 experiments specifically found that current input-size reductions
come from Local Runtime state selection and repeated-context removal, not from
the ANA Envelope encoding itself. A smart ordinary JSON implementation can be
as efficient or more efficient than the current Envelope. Therefore ANA v0.1
should be evaluated for state ownership and interoperability boundaries, not
advertised as a compression technology.

## Maturity

The minimal profile has an independent Java implementation and fixed
Python ↔ Java conformance tests. This is enough to invite external review and
additional independent implementations; it is not enough to call ANA a
finalized or industry standard. See [STATUS.md](../STATUS.md).
