"""Run exactly one live ANA → OpenAI validation only when a key is configured."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from adapters.openai_responses import OpenAIProviderError, OpenAIResponsesProvider
from ana.continuation import build_continuation_envelope, continue_with_provider
from ana.memory import MemoryStore
from ana.schema import MemoryRecord


RESULTS_DIR = Path("benchmarks/results")


def _write_result(result: dict[str, Any]) -> dict[str, Any]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(RESULTS_DIR.glob("live-openai-run-*.json"))
    result_path = RESULTS_DIR / f"live-openai-run-{len(existing) + 1:03}.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return result


def run_live_validation() -> dict[str, Any]:
    """Use one minimal request, or safely record a skip with no configured key."""
    if not os.environ.get("OPENAI_API_KEY"):
        return _write_result(
            {
                "experiment": "live-provider-validation",
                "provider": "openai.responses",
                "status": "skipped_missing_openai_api_key",
                "request_count": 0,
            }
        )

    memory = MemoryStore()
    preference = MemoryRecord(kind="preference", content={"language": "english"})
    semantic = MemoryRecord(kind="semantic", content={"memory_owner": "local_runtime"})
    memory.add(preference)
    memory.add(semantic)
    envelope = build_continuation_envelope(
        memory,
        request="Reply with exactly: ANA live validation passed.",
        memory_refs=(preference.id, semantic.id),
        task_id="live-openai-validation",
    )
    model = os.environ.get("ANA_OPENAI_MODEL", "gpt-5.6-luna")
    started = perf_counter()
    try:
        result = continue_with_provider(OpenAIResponsesProvider(model), envelope)
    except OpenAIProviderError as error:
        return _write_result(
            {
                "experiment": "live-provider-validation",
                "provider": "openai.responses",
                "model": model,
                "status": "failed_provider_error",
                "request_count": 1,
                "error": str(error),
            }
        )
    latency_ms = round((perf_counter() - started) * 1000, 3)
    text = str(result.output["text"]).strip()
    return _write_result(
        {
            "experiment": "live-provider-validation",
            "provider": result.provider_id,
            "model": model,
            "status": "completed",
            "request_count": 1,
            "latency_ms": latency_ms,
            "task_correct": text == "ANA live validation passed.",
            "proposed_action_count": len(result.proposed_actions),
            "response_text": text,
        }
    )


if __name__ == "__main__":
    run_live_validation()
