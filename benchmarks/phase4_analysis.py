"""Phase 4 decomposition and break-even analysis without changing ANA inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .run_phase3_benchmark import canonical, packet_pair, token_count


CASES_PATH = Path(__file__).with_name("phase3_cases.json")
PARAMETERS_PATH = Path(__file__).with_name("phase4_parameters.json")
RESULTS_DIR = Path(__file__).with_name("results")


def _bytes(value: Any) -> int:
    return len(canonical(value).encode("utf-8"))


def _logical_bytes(value: Any) -> int:
    """Count user/domain values while leaving keys and JSON syntax as metadata."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, bool):
        return len(str(value).lower())
    if isinstance(value, (int, float)):
        return len(str(value).encode("utf-8"))
    if isinstance(value, list):
        return sum(_logical_bytes(item) for item in value)
    if isinstance(value, dict):
        return sum(_logical_bytes(item) for item in value.values())
    if value is None:
        return 4
    raise TypeError(f"unsupported logical value: {type(value).__name__}")


def decompose_case(case: dict[str, Any]) -> dict[str, Any]:
    """Make the fixed and logical contributions of existing Phase 3 packets explicit."""
    baseline_packet, ana_packet = packet_pair(case)
    baseline_total = _bytes(baseline_packet)
    ana_total = _bytes(ana_packet)

    baseline_fixed = _bytes({"task": "", "history": []})
    baseline_task = _logical_bytes(case["task"])
    baseline_repeated = _logical_bytes(case["baseline_history"])
    baseline_metadata = baseline_total - baseline_fixed - baseline_task - baseline_repeated

    non_preference_memory = [
        record for record in case["ana_memory"] if record.get("kind") != "preference"
    ]
    preference_memory = [
        record for record in case["ana_memory"] if record.get("kind") == "preference"
    ]
    ana_fixed = _bytes({"task": "", "memory": [], "project_state": [], "state_deltas": []})
    ana_task = _logical_bytes(case["task"])
    ana_memory = sum(_logical_bytes(record["content"]) for record in non_preference_memory)
    ana_preference = sum(_logical_bytes(record["content"]) for record in preference_memory)
    ana_project_state = _logical_bytes(case["project_state"])
    ana_state_delta = _logical_bytes(case["state_deltas"])
    ana_metadata = (
        ana_total
        - ana_fixed
        - ana_task
        - ana_memory
        - ana_preference
        - ana_project_state
        - ana_state_delta
    )

    assert baseline_metadata >= 0 and ana_metadata >= 0
    assert baseline_fixed + baseline_task + baseline_repeated + baseline_metadata == baseline_total
    assert (
        ana_fixed
        + ana_task
        + ana_memory
        + ana_preference
        + ana_project_state
        + ana_state_delta
        + ana_metadata
        == ana_total
    )
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "baseline": {
            "total_bytes": baseline_total,
            "protocol_envelope_fixed_bytes": baseline_fixed,
            "task_content_bytes": baseline_task,
            "repeated_context_bytes": baseline_repeated,
            "metadata_bytes": baseline_metadata,
        },
        "ana": {
            "total_bytes": ana_total,
            "protocol_envelope_fixed_bytes": ana_fixed,
            "task_content_bytes": ana_task,
            "memory_bytes": ana_memory,
            "preference_bytes": ana_preference,
            "project_state_bytes": ana_project_state,
            "state_delta_bytes": ana_state_delta,
            "metadata_bytes": ana_metadata,
        },
    }


def _measure_packets(baseline: dict[str, Any], ana: dict[str, Any]) -> dict[str, Any]:
    baseline_wire = canonical(baseline)
    ana_wire = canonical(ana)
    baseline_tokens, method = token_count(baseline_wire)
    ana_tokens, ana_method = token_count(ana_wire)
    if method != ana_method:
        raise RuntimeError("tokenizer method differs within a parameter point")
    return {
        "baseline_bytes": len(baseline_wire.encode("utf-8")),
        "ana_bytes": len(ana_wire.encode("utf-8")),
        "baseline_tokens": baseline_tokens,
        "ana_tokens": ana_tokens,
        "token_method": method,
    }


def _history_packet(task: str, turns: int) -> tuple[dict[str, Any], dict[str, Any]]:
    history = [
        f"Turn {turn}: project=ANA; priority=security_first; memory_owner=local_runtime."
        for turn in range(1, turns + 1)
    ]
    history.append(f"Continuation turn={turns}.")
    return (
        {"task": task, "history": history},
        {
            "task": task,
            "memory": [
                {"kind": "semantic", "content": {"project": "ANA", "priority": "security_first", "memory_owner": "local_runtime"}}
            ],
            "project_state": [{"continuation_turn": turns}],
            "state_deltas": [],
        },
    )


def _project_state_packet(task: str, items: int) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = [(f"state_{item}", f"value_{item}") for item in range(1, items + 1)]
    return (
        {"task": task, "history": [f"{key}={value}." for key, value in facts]},
        {"task": task, "memory": [], "project_state": [{key: value} for key, value in facts], "state_deltas": []},
    )


def _preference_packet(task: str, items: int) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = [(f"preference_{item}", f"value_{item}") for item in range(1, items + 1)]
    return (
        {"task": task, "history": [f"{key}={value}." for key, value in facts]},
        {
            "task": task,
            "memory": [{"kind": "preference", "content": {key: value}} for key, value in facts],
            "project_state": [],
            "state_deltas": [],
        },
    )


def _repeated_context_packet(task: str, repetitions: int) -> tuple[dict[str, Any], dict[str, Any]]:
    repeated = "Constraint: provider_no_execute; memory_owner=local_runtime."
    return (
        {"task": task, "history": [repeated for _ in range(repetitions)]},
        {
            "task": task,
            "memory": [{"kind": "semantic", "content": {"constraint": "provider_no_execute", "memory_owner": "local_runtime"}}],
            "project_state": [],
            "state_deltas": [],
        },
    )


def _continuation_packet(task: str, turns: int) -> tuple[dict[str, Any], dict[str, Any]]:
    history = []
    for turn in range(1, turns + 1):
        history.extend(
            [
                f"User turn={turn}: continue ANA with security_first and local_runtime.",
                f"Assistant turn={turn}: retained project=ANA and provider_no_execute.",
            ]
        )
    return (
        {"task": task, "history": history},
        {
            "task": task,
            "memory": [{"kind": "semantic", "content": {"project": "ANA", "priority": "security_first", "memory_owner": "local_runtime", "constraint": "provider_no_execute"}}],
            "project_state": [{"continuation_turn": turns}],
            "state_deltas": [{"kind": "project_state.upsert", "sequence": turns, "status": "continued"}],
        },
    )


def _curve(name: str, task: str, scales: list[int], factory, fact_factory) -> dict[str, Any]:
    points = []
    for scale in scales:
        baseline, ana = factory(task, scale)
        facts = fact_factory(scale)
        baseline_wire, ana_wire = canonical(baseline), canonical(ana)
        point = {
            "scale": scale,
            **_measure_packets(baseline, ana),
            "baseline_required_fact_retention": f"{sum(fact in baseline_wire for fact in facts)}/{len(facts)}",
            "ana_required_fact_retention": f"{sum(fact in ana_wire for fact in facts)}/{len(facts)}",
        }
        points.append(point)
    break_even_search = []
    for scale in range(1, max(scales) + 1):
        baseline, ana = factory(task, scale)
        facts = fact_factory(scale)
        baseline_wire, ana_wire = canonical(baseline), canonical(ana)
        break_even_search.append(
            {
                "scale": scale,
                **_measure_packets(baseline, ana),
                "baseline_required_fact_retention": f"{sum(fact in baseline_wire for fact in facts)}/{len(facts)}",
                "ana_required_fact_retention": f"{sum(fact in ana_wire for fact in facts)}/{len(facts)}",
            }
        )
    return {
        "dimension": name,
        "points": points,
        "break_even_search_range": [1, max(scales)],
        "break_even_bytes": next(
            (p["scale"] for p in break_even_search if p["ana_bytes"] < p["baseline_bytes"]), None
        ),
        "break_even_tokens": next(
            (
                p["scale"]
                for p in break_even_search
                if p["ana_tokens"] is not None and p["ana_tokens"] < p["baseline_tokens"]
            ),
            None,
        ),
    }


def parameterized_curves() -> list[dict[str, Any]]:
    config = json.loads(PARAMETERS_PATH.read_text(encoding="utf-8"))
    task = config["task"]
    scales = config["scales"]
    return [
        _curve("conversation_history", task, scales, _history_packet, lambda scale: ["ANA", "security_first", "local_runtime", str(scale)]),
        _curve("project_state", task, scales, _project_state_packet, lambda scale: ["state_1", "value_1", f"state_{scale}", f"value_{scale}"]),
        _curve("user_preferences", task, scales, _preference_packet, lambda scale: ["preference_1", "value_1", f"preference_{scale}", f"value_{scale}"]),
        _curve("repeated_context", task, scales, _repeated_context_packet, lambda scale: ["provider_no_execute", "local_runtime"]),
        _curve("continuation_turns", task, scales, _continuation_packet, lambda scale: ["ANA", "security_first", "local_runtime", "provider_no_execute", str(scale)]),
    ]


def run_analysis() -> dict[str, Any]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    result = {
        "phase": "phase-4-break-even-analysis",
        "decomposition": [decompose_case(case) for case in cases],
        "parameterized_curves": parameterized_curves(),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(RESULTS_DIR.glob("phase4-break-even-run-*.json"))
    path = RESULTS_DIR / f"phase4-break-even-run-{len(existing) + 1:03}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_analysis(), indent=2, ensure_ascii=False))
