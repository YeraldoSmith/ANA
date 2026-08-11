"""Fixed Phase 6 contract demo: provider changes, local ANA state remains.

This is deliberately a deterministic protocol-level experiment.  Contract
providers are not model-quality simulators and cannot mutate local state.  The
local validation functions below accept only the one expected state transition;
all other provider claims are recorded and rejected.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ana.memory import MemoryStore
from ana.policy import Decision, LocalPolicy
from ana.schema import ANAEnvelope, MemoryRecord, ProposedAction, ProviderResult


@dataclass(frozen=True)
class ContractContinuationProvider:
    """A deterministic stand-in for a Provider API boundary in offline tests."""

    provider_id: str
    behavior: str = "normal"
    capabilities: frozenset[str] = frozenset({"text_generation"})

    def run(self, envelope: ANAEnvelope) -> ProviderResult:
        context = envelope.context
        memory = context["memory"]
        state = context["project_state"]
        current_ids = [record["id"] for record in memory]
        preference = next(record["content"]["priority"] for record in memory if record["kind"] == "preference")
        language = next(record["content"]["language"] for record in memory if record["kind"] == "semantic")
        delta: dict[str, Any] = {
            "event_id": "evt-5-validate-scaffold",
            "parent_event_id": state["last_event_id"],
            "sequence": state["sequence"] + 1,
            "kind": "project_state.upsert",
            "payload": {"phase": "implementation", "completed_task": "validate_scaffold"},
        }
        output: dict[str, Any] = {
            "text": "Contract continuation accepted.",
            "continuity": {
                "language": language,
                "priority": preference,
                "phase_seen": state["phase"],
                "completed_tasks_seen": list(state["completed_tasks"]),
                "memory_ids_referenced": current_ids,
                "candidate_delta": delta,
            },
        }
        actions: tuple[ProposedAction, ...] = ()
        if self.behavior == "conflicting_state":
            output["continuity"]["candidate_delta"]["payload"]["phase"] = "discovery"
        elif self.behavior == "ignore_preference":
            output["continuity"]["priority"] = "speed_first"
        elif self.behavior == "unsafe_action":
            actions = (ProposedAction(kind="write_file", target="../outside.txt", content="unsafe"),)
        elif self.behavior == "sequence_rollback":
            output["continuity"]["candidate_delta"]["sequence"] = state["sequence"]
        elif self.behavior == "stale_memory":
            output["continuity"]["memory_ids_referenced"] = ["mem-old-phase"]
        return ProviderResult(provider_id=self.provider_id, output=output, proposed_actions=actions)


def _records_as_context(memory: MemoryStore, record_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {"id": record.id, "kind": record.kind, "content": record.content}
        for record_id in record_ids
        if (record := memory.get(record_id)).portability == "portable"
    ]


def build_fixed_local_context() -> tuple[MemoryStore, tuple[str, ...], dict[str, Any]]:
    """Create fixed Java-project state with old conflict deliberately unselected."""
    memory = MemoryStore()
    project = MemoryRecord(id="mem-project-java", kind="semantic", content={"language": "java", "project": "ANA"})
    preference = MemoryRecord(id="pref-security", kind="preference", content={"priority": "security_first"})
    long_term = MemoryRecord(id="mem-local-owner", kind="semantic", content={"memory_owner": "local_runtime"})
    old_phase = MemoryRecord(id="mem-old-phase", kind="project_state", content={"phase": "discovery"})
    for record in (project, preference, long_term, old_phase):
        memory.add(record)
    selected_ids = (project.id, preference.id, long_term.id)
    state = {
        "phase": "scaffolded",
        "sequence": 4,
        "last_event_id": "evt-4-scaffold",
        "completed_tasks": ["create_basic_structure"],
        "files": ["src/main/java/ana/App.java"],
    }
    return memory, selected_ids, state


def build_handoff_envelope(
    memory: MemoryStore,
    selected_ids: tuple[str, ...],
    state: dict[str, Any],
    *,
    task_id: str,
    request: str,
) -> ANAEnvelope:
    """Fresh provider input: selected local state, never provider chat history."""
    return ANAEnvelope(
        intent="continue",
        capabilities=("text_generation",),
        input={"text": request},
        context={
            "memory": _records_as_context(memory, selected_ids),
            "project_state": deepcopy(state),
            "state_deltas": [],
        },
        memory_refs=selected_ids,
        policy={"execution_mode": "sandbox_first", "priority": "security_first"},
        task_id=task_id,
    )


def _validate_provider_result(
    result: ProviderResult,
    envelope: ANAEnvelope,
    policy: LocalPolicy,
) -> tuple[bool, str]:
    """Accept only an expected local transition; never trust provider output directly."""
    continuity = result.output.get("continuity", {})
    state = envelope.context["project_state"]
    selected_ids = {record["id"] for record in envelope.context["memory"]}
    if continuity.get("priority") != "security_first":
        return False, "preference_not_preserved"
    if not set(continuity.get("memory_ids_referenced", [])).issubset(selected_ids):
        return False, "stale_or_unselected_memory_referenced"
    for action in result.proposed_actions:
        if policy.decide(action) == Decision.DENY:
            return False, "unsafe_action_denied_by_local_policy"
    delta = continuity.get("candidate_delta", {})
    if delta.get("sequence") != state["sequence"] + 1:
        return False, "state_sequence_not_monotonic"
    if delta.get("parent_event_id") != state["last_event_id"]:
        return False, "state_parent_mismatch"
    payload = delta.get("payload", {})
    if payload.get("phase") != "implementation":
        return False, "state_conflicts_with_current_project"
    if payload.get("completed_task") != "validate_scaffold":
        return False, "unexpected_state_transition"
    if payload["completed_task"] in state["completed_tasks"]:
        return False, "completed_task_would_repeat"
    return True, "accepted"


def _apply_validated_delta(state: dict[str, Any], result: ProviderResult) -> dict[str, Any]:
    """The Local Runtime, not the provider, owns the committed State update."""
    next_state = deepcopy(state)
    delta = result.output["continuity"]["candidate_delta"]
    next_state["phase"] = delta["payload"]["phase"]
    next_state["completed_tasks"].append(delta["payload"]["completed_task"])
    next_state["sequence"] = delta["sequence"]
    next_state["last_event_id"] = delta["event_id"]
    return next_state


def run_offline_handoff(provider_a: str, provider_b: str) -> dict[str, Any]:
    """Execute Provider A → local commit → Provider B with no Provider A history."""
    memory, selected_ids, initial_state = build_fixed_local_context()
    workspace_policy = LocalPolicy(Path.cwd())
    first_envelope = build_handoff_envelope(
        memory,
        selected_ids,
        initial_state,
        task_id=f"phase6-{provider_a}-first",
        request="Validate the existing Java scaffold; do not recreate it.",
    )
    first = ContractContinuationProvider(provider_a).run(first_envelope)
    accepted, reason = _validate_provider_result(first, first_envelope, workspace_policy)
    if not accepted:
        raise AssertionError(f"normal contract provider unexpectedly rejected: {reason}")
    after_a = _apply_validated_delta(initial_state, first)

    second_envelope = build_handoff_envelope(
        memory,
        selected_ids,
        after_a,
        task_id=f"phase6-{provider_b}-second",
        request="Continue the Java project after scaffold validation; do not redo completed tasks.",
    )
    second = ContractContinuationProvider(provider_b).run(second_envelope)
    second_seen = second.output["continuity"]
    checks = {
        "preference_retained": second_seen["priority"] == "security_first",
        "project_phase_continuous": second_seen["phase_seen"] == "implementation",
        "completed_task_not_repeated": "validate_scaffold" in second_seen["completed_tasks_seen"],
        "latest_state_overrides_old_state": "mem-old-phase" not in second_seen["memory_ids_referenced"],
        "no_provider_a_history_sent_to_b": "history" not in second_envelope.context,
        "provider_memory_is_neutral": all(
            "openai" not in str(record).lower() and "anthropic" not in str(record).lower()
            for record in second_envelope.context["memory"]
        ),
        "safety_policy_retained": second_envelope.policy["execution_mode"] == "sandbox_first",
    }
    return {
        "mode": "offline_contract_validation",
        "migration": f"{provider_a} -> {provider_b}",
        "provider_a": first.provider_id,
        "provider_b": second.provider_id,
        "initial_state": initial_state,
        "state_after_provider_a": after_a,
        "state_diff": {
            "phase": [initial_state["phase"], after_a["phase"]],
            "sequence": [initial_state["sequence"], after_a["sequence"]],
            "completed_tasks_added": ["validate_scaffold"],
        },
        "provider_b_received": {
            "memory": second_envelope.context["memory"],
            "project_state": second_envelope.context["project_state"],
            "policy": second_envelope.policy,
        },
        "continuity_assertions": checks,
    }


def run_failure_cases() -> list[dict[str, Any]]:
    """Show local detection/blocking for invalid Provider B suggestions."""
    memory, selected_ids, state = build_fixed_local_context()
    envelope = build_handoff_envelope(
        memory, selected_ids, state, task_id="phase6-failure", request="Continue safely."
    )
    policy = LocalPolicy(Path.cwd())
    expected = {
        "conflicting_state": "state_conflicts_with_current_project",
        "ignore_preference": "preference_not_preserved",
        "unsafe_action": "unsafe_action_denied_by_local_policy",
        "sequence_rollback": "state_sequence_not_monotonic",
        "stale_memory": "stale_or_unselected_memory_referenced",
    }
    cases = []
    for behavior, reason in expected.items():
        result = ContractContinuationProvider("provider-b-contract", behavior).run(envelope)
        accepted, detected = _validate_provider_result(result, envelope, policy)
        cases.append(
            {
                "case": behavior,
                "accepted": accepted,
                "detected": detected,
                "expected": reason,
                "local_state_unchanged": state == envelope.context["project_state"],
            }
        )
    return cases


def run_offline_demo() -> dict[str, Any]:
    """Return both directions and failures in a compact, human-readable artifact."""
    return {
        "phase": "phase-6-cross-provider-continuity",
        "migrations": [
            run_offline_handoff("openai-contract", "anthropic-contract"),
            run_offline_handoff("anthropic-contract", "openai-contract"),
        ],
        "failure_cases": run_failure_cases(),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_offline_demo(), ensure_ascii=False, indent=2))
