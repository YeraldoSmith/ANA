"""Optional live Phase 6 adapter validation; never runs without both API keys."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from adapters.anthropic_messages import AnthropicMessagesProvider, AnthropicProviderError
from adapters.openai_responses import OpenAIProviderError, OpenAIResponsesProvider
from examples.cross_provider_continuity import (
    build_fixed_local_context,
    build_handoff_envelope,
)


RESULTS_DIR = Path("benchmarks/results")


def _write_result(result: dict[str, Any]) -> dict[str, Any]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    runs = sorted(RESULTS_DIR.glob("phase6-live-run-*.json"))
    (RESULTS_DIR / f"phase6-live-run-{len(runs) + 1:03}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return result


def _run_direction(
    first_name: str, second_name: str, *, on_request: Callable[[], None]
) -> dict[str, Any]:
    """Call two providers with a local-only state handoff between calls.

    No model text is interpreted as an action or State Delta.  The recorded
    state change is a fixed local test fixture, making this a live adapter-path
    check rather than a claim about model quality.
    """
    memory, selected_ids, state = build_fixed_local_context()
    openai_model = os.environ.get("ANA_OPENAI_MODEL", "gpt-5.6-luna")
    anthropic_model = os.environ.get("ANA_ANTHROPIC_MODEL", "claude-sonnet-4-5")
    providers = {
        "openai": OpenAIResponsesProvider(openai_model),
        "anthropic": AnthropicMessagesProvider(anthropic_model),
    }
    calls = []
    for sequence, (name, current_state, request) in enumerate(
        (
            (first_name, state, "Reply exactly: ANA Phase 6 first handoff acknowledged."),
            (
                second_name,
                {
                    **state,
                    "phase": "implementation",
                    "sequence": 5,
                    "last_event_id": "evt-5-local-handoff",
                    "completed_tasks": ["create_basic_structure", "validate_scaffold"],
                },
                "Reply exactly: ANA Phase 6 second handoff acknowledged.",
            ),
        ),
        start=1,
    ):
        envelope = build_handoff_envelope(
            memory,
            selected_ids,
            current_state,
            task_id=f"phase6-live-{first_name}-{second_name}-{sequence}",
            request=request,
        )
        started = perf_counter()
        on_request()
        result = providers[name].run(envelope)
        calls.append(
            {
                "provider": result.provider_id,
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "response_received": bool(str(result.output.get("text", "")).strip()),
                "proposed_action_count": len(result.proposed_actions),
                "history_sent": "history" in envelope.context,
                "memory_provider_neutral": all(
                    "openai" not in str(record).lower() and "anthropic" not in str(record).lower()
                    for record in envelope.context["memory"]
                ),
                "project_phase_sent": envelope.context["project_state"]["phase"],
            }
        )
    return {"migration": f"{first_name} -> {second_name}", "calls": calls}


def run_live_cross_provider_validation() -> dict[str, Any]:
    """Run both directions only with both configured keys; never reveal either key."""
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        return _write_result(
            {
                "experiment": "phase-6-live-cross-provider-validation",
                "status": "skipped_missing_required_provider_key",
                "request_count": 0,
            }
        )
    request_count = 0

    def counted_request() -> None:
        nonlocal request_count
        request_count += 1

    try:
        migrations = [
            _run_direction("openai", "anthropic", on_request=counted_request),
            _run_direction("anthropic", "openai", on_request=counted_request),
        ]
    except (OpenAIProviderError, AnthropicProviderError) as error:
        return _write_result(
            {
                "experiment": "phase-6-live-cross-provider-validation",
                "status": "failed_provider_error",
                "request_count": request_count,
                "error": str(error),
            }
        )
    return _write_result(
        {
            "experiment": "phase-6-live-cross-provider-validation",
            "status": "completed_adapter_path_only",
            "request_count": 4,
            "migrations": migrations,
            "model_quality_validated": False,
        }
    )


if __name__ == "__main__":
    run_live_cross_provider_validation()
