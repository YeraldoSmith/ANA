"""Phase 5 ablation: fair selected-context baseline versus ANA Envelope."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from .run_phase3_benchmark import canonical, token_count


PARAMETERS_PATH = Path(__file__).with_name("phase5_parameters.json")
FIDELITY_PATH = Path(__file__).with_name("phase5_fidelity_cases.json")
RESULTS_DIR = Path(__file__).with_name("results")
ITERATIONS = 1_000


def _mean_encode_decode_us(packet: dict[str, Any]) -> float:
    started = perf_counter_ns()
    for _ in range(ITERATIONS):
        json.loads(canonical(packet))
    return round((perf_counter_ns() - started) / ITERATIONS / 1_000, 3)


def _metrics(packet: dict[str, Any], facts: list[str]) -> dict[str, Any]:
    wire = canonical(packet)
    tokens, method = token_count(wire)
    return {
        "utf8_bytes": len(wire.encode("utf-8")),
        "token_estimate": tokens,
        "token_method": method,
        "encode_decode_mean_us": _mean_encode_decode_us(packet),
        "required_fact_retention": f"{sum(fact in wire for fact in facts)}/{len(facts)}",
    }


def packets_for_turn(config: dict[str, Any], turn: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    """Build three representations of the same task and selected facts.

    Naive retains all prior turns. Smart and ANA receive the same selected
    Memory/State values; ANA adds only existing v0.1 Envelope metadata.
    """
    task = config["task"]
    selected_memory = config["selected_memory"]
    project_state = [{"phase": "phase_5", "continuation_turn": turn}]
    state_delta = [
        {
            "event_id": f"evt-{turn}",
            "parent_event_id": f"evt-{turn - 1}" if turn > 1 else "task-root",
            "sequence": turn,
            "kind": "project_state.upsert",
            "payload": {"status": "continued", "turn": turn},
        }
    ]
    naive_history = []
    for previous_turn in range(1, turn + 1):
        naive_history.extend(
            [
                f"User turn={previous_turn}: project=ANA; memory_owner=local_runtime; priority=security_first; language=english.",
                f"Assistant turn={previous_turn}: phase=phase_5; status=continued; provider_no_execute.",
            ]
        )
    naive = {"task": task, "history": naive_history}

    # Smart uses the exact selected content values that ANA puts in `context`.
    shared_context = {
        "memory": selected_memory,
        "project_state": project_state,
        "state_deltas": state_delta,
    }
    smart = {
        "message": {
            "text": task,
            "intent": "continue",
            "capability": "text_generation",
            "execution_mode": "sandbox_first",
        },
        "context": shared_context,
    }
    ana = {
        "version": "0.1",
        "task_id": f"phase5-continuation-{turn}",
        "intent": "continue",
        "capabilities": ["text_generation"],
        "input": {"text": task},
        "context": shared_context,
        "memory_refs": ["mem-project", "mem-priority", "pref-language"],
        "policy": {"execution_mode": "sandbox_first"},
    }
    facts = ["ANA", "local_runtime", "security_first", "english", "phase_5", "continued", str(turn)]
    return naive, smart, ana, facts


def ablate_envelope(envelope: dict[str, Any]) -> dict[str, int]:
    """Marginal byte cost of existing Envelope groups; values are non-additive."""
    full_size = len(canonical(envelope).encode("utf-8"))

    def contribution(mutator) -> int:
        variant = deepcopy(envelope)
        mutator(variant)
        return full_size - len(canonical(variant).encode("utf-8"))

    return {
        "full_envelope_bytes": full_size,
        "version_bytes": contribution(lambda value: value.pop("version")),
        "metadata_bytes": contribution(
            lambda value: [value.pop("intent"), value.pop("capabilities"), value.pop("policy")]
        ),
        "identifiers_bytes": contribution(lambda value: [value.pop("task_id"), value.pop("memory_refs")]),
        "state_fields_bytes": contribution(lambda value: value["context"].pop("project_state")),
        "causality_information_bytes": contribution(
            lambda value: [
                delta.pop("event_id")
                for delta in value["context"]["state_deltas"]
            ]
            + [
                delta.pop("parent_event_id")
                for delta in value["context"]["state_deltas"]
            ]
            + [
                delta.pop("sequence")
                for delta in value["context"]["state_deltas"]
            ]
        ),
    }


def fidelity_results() -> list[dict[str, Any]]:
    cases = json.loads(FIDELITY_PATH.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        indexed = {record["id"]: record for record in case["records"]}
        selected = [indexed[record_id] for record_id in case["selected_ids"]]
        selected_wire = canonical(selected)
        present = sum(value in selected_wire for value in case["expected_present"])
        absent = sum(value not in selected_wire for value in case["expected_absent"])
        results.append(
            {
                "case_id": case["case_id"],
                "expected_present_retention": f"{present}/{len(case['expected_present'])}",
                "expected_obsolete_or_conflicting_absence": f"{absent}/{len(case['expected_absent'])}",
                "selection_fidelity": present == len(case["expected_present"]) and absent == len(case["expected_absent"]),
            }
        )
    return results


def run_analysis() -> dict[str, Any]:
    config = json.loads(PARAMETERS_PATH.read_text(encoding="utf-8"))
    continuation = []
    ablations = []
    for turn in config["scales"]:
        naive, smart, ana, facts = packets_for_turn(config, turn)
        continuation.append(
            {
                "turn": turn,
                "naive": _metrics(naive, facts),
                "smart": _metrics(smart, facts),
                "ana": _metrics(ana, facts),
            }
        )
        ablations.append({"turn": turn, **ablate_envelope(ana)})
    result = {
        "phase": "phase-5-ablation-and-fair-baseline",
        "continuation": continuation,
        "envelope_ablations": ablations,
        "memory_fidelity": fidelity_results(),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(RESULTS_DIR.glob("phase5-ablation-run-*.json"))
    path = RESULTS_DIR / f"phase5-ablation-run-{len(existing) + 1:03}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_analysis(), indent=2, ensure_ascii=False))
