# ANA v0.1 Draft Status

**Maturity: Draft / Experimental (2026-08-11).**

ANA v0.1 is a protocol draft with a reference implementation and an independent
Java conformance implementation. It is suitable for review, experimentation,
and third-party minimal-profile implementations. It is not a production
standard, a finalized standard, or a security-audited protocol.

## Evidence available

- Frozen RFC-0001 through RFC-0005 and canonical test vectors.
- Python ↔ Java `ana-core-chain` v0.1 minimal-profile conformance.
- Offline provider-switch continuity contract tests.
- Local Safety Policy boundary tests: Provider output remains a proposal.

## Evidence not available

- Live OpenAI ↔ Anthropic interoperability: no paired keys were configured, so the live validation entry made zero requests.
- Model-quality equivalence after a provider switch.
- General performance, token, cost, or latency advantages.
- Security audit, interoperability governance process, or multi-vendor adoption.

Read [limitations](docs/limitations.md) before using this draft outside a test
environment.
