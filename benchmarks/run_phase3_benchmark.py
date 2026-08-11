"""Run the fixed Phase 3 evidence benchmark and retain raw local results."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter_ns
from typing import Any


CASES_PATH = Path(__file__).with_name("phase3_cases.json")
RESULTS_DIR = Path(__file__).with_name("results")
CACHE_DIR = Path(__file__).with_name(".tiktoken-cache")
ITERATIONS = 1_000

if CACHE_DIR.exists():
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(CACHE_DIR))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def token_count(text: str) -> tuple[int | None, str]:
    """Return a stable local estimate, never a provider billing-token claim."""
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text)), "cl100k_base_estimate"
    except Exception as error:  # Missing package or an unavailable encoding table.
        return None, f"unavailable_tokenizer:{type(error).__name__}"


def encode_decode_mean_us(packet: dict[str, Any]) -> float:
    started = perf_counter_ns()
    for _ in range(ITERATIONS):
        json.loads(canonical(packet))
    return round((perf_counter_ns() - started) / ITERATIONS / 1_000, 3)


def packet_pair(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = {"task": case["task"], "history": case["baseline_history"]}
    ana = {
        "task": case["task"],
        "memory": case["ana_memory"],
        "project_state": case["project_state"],
        "state_deltas": case["state_deltas"],
    }
    return baseline, ana


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    baseline_packet, ana_packet = packet_pair(case)
    baseline_wire = canonical(baseline_packet)
    ana_wire = canonical(ana_packet)
    baseline_tokens, token_method = token_count(baseline_wire)
    ana_tokens, ana_token_method = token_count(ana_wire)
    if token_method != ana_token_method:
        raise RuntimeError("benchmark tokenization methods differ")
    required_facts = case["required_facts"]
    baseline_facts = sum(fact in baseline_wire for fact in required_facts)
    ana_facts = sum(fact in ana_wire for fact in required_facts)
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "baseline_input_bytes": len(baseline_wire.encode("utf-8")),
        "ana_input_bytes": len(ana_wire.encode("utf-8")),
        "byte_delta_ana_minus_baseline": len(ana_wire.encode("utf-8")) - len(baseline_wire.encode("utf-8")),
        "baseline_input_tokens": baseline_tokens,
        "ana_input_tokens": ana_tokens,
        "token_delta_ana_minus_baseline": None if baseline_tokens is None else ana_tokens - baseline_tokens,
        "token_method": token_method,
        "baseline_required_fact_retention": f"{baseline_facts}/{len(required_facts)}",
        "ana_required_fact_retention": f"{ana_facts}/{len(required_facts)}",
        "baseline_task_correctness": "not_evaluated_offline",
        "ana_task_correctness": "not_evaluated_offline",
        "baseline_encode_decode_mean_us": encode_decode_mean_us(baseline_packet),
        "ana_encode_decode_mean_us": encode_decode_mean_us(ana_packet),
        "end_to_end_latency_ms": None,
    }


def run_all() -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = [run_case(case) for case in cases]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(RESULTS_DIR.glob("phase3-offline-run-*.json"))
    next_number = len(existing) + 1
    result_path = RESULTS_DIR / f"phase3-offline-run-{next_number:03}.json"
    result_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    print(json.dumps(run_all(), indent=2, ensure_ascii=False))
