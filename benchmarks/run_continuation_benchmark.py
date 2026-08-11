"""Compare repeated-history baseline input with ANA selected-Memory input.

This benchmark measures only deterministic UTF-8 request payload size and the
presence of required facts.  It does not measure model quality, tokens, cost,
or latency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CASES = Path(__file__).with_name("continuation_cases.json")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    baseline = _canonical({"input": case["request"], "history": case["baseline_history"]})
    ana = _canonical({"input": case["request"], "memory": case["ana_memory"]})
    facts = case["required_facts"]
    return {
        "case_id": case["case_id"],
        "baseline_utf8_bytes": len(baseline.encode("utf-8")),
        "ana_utf8_bytes": len(ana.encode("utf-8")),
        "saved_utf8_bytes": len(baseline.encode("utf-8")) - len(ana.encode("utf-8")),
        "baseline_contains_required_facts": all(fact in baseline for fact in facts),
        "ana_contains_required_facts": all(fact in ana for fact in facts),
    }


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    print(json.dumps([run_case(case) for case in cases], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
