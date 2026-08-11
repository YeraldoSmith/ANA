"""Persist the deterministic Phase 6 cross-provider contract demo result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from examples.cross_provider_continuity import run_offline_demo


RESULTS_DIR = Path(__file__).with_name("results")


def run() -> dict[str, Any]:
    result = run_offline_demo()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(RESULTS_DIR.glob("phase6-offline-contract-run-*.json"))
    path = RESULTS_DIR / f"phase6-offline-contract-run-{len(existing) + 1:03}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
