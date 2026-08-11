# ANA roadmap

## v0.1 — reference boundary (current)

- Publish the envelope, memory record, migration profile, provider, and policy
  concepts.
- Provide one deterministic adapter and a safe write-file demo.
- Prove codec reversibility with tests.

## v0.2 — interoperability experiment

- Add one real provider adapter behind an explicit user-supplied credential.
- Define structured error and capability-discovery formats.
- Add signed/exportable portable migration profiles.
- Collect feedback in an RFC issue process.

## v0.3 — multi-agent coordination

- Define delegation, result provenance, cancellation, and event records.
- Add sandbox runner interfaces and policy profiles.
- Test interoperation between independently written runtimes.

## Standardization criteria

ANA should not claim to be a standard until multiple independent implementations
can exchange envelopes and portable memories without vendor-specific behaviour.
