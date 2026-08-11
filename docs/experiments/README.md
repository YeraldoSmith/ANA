# ANA Validation Evidence

These reports are preserved historical evidence, not performance marketing.
They retain adverse and excluded raw runs where noted, and none establishes a
general token, cost, latency, or model-quality claim.

| Phase | Report | What it established |
| --- | --- | --- |
| 2 | [Reference implementation experiments](../phase-2-experiments.md) | Replaceable Provider boundary and a bounded continuation demo |
| 3 | [Evidence](../phase-3-evidence.md) | Fixed-vector Adapter contracts and an honest baseline comparison |
| 4 | [Break-even analysis](../phase-4-break-even-analysis.md) | Current benefits arise primarily from avoiding repeated context |
| 5 | [Ablation and fair baseline](../phase-5-ablation-fair-baseline.md) | Smart state selection, not the ANA Envelope, accounts for observed savings |
| 6 | [Cross-provider continuity](../phase-6-cross-provider-continuity.md) | Offline contract continuity and Local Safety Policy preservation |
| 7 | [Independent implementation](../phase-7-independent-implementation.md) | Python ↔ Java minimal-Core conformance |

Phase 6 live validation was skipped with zero requests because paired provider
credentials were unavailable. It must not be represented as real-provider live
interoperability evidence.
