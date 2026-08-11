"""Versioned, provider-neutral objects for ANA v0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ANAEnvelope:
    intent: str
    capabilities: tuple[str, ...]
    input: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    memory_refs: tuple[str, ...] = ()
    policy: dict[str, Any] = field(default_factory=dict)
    version: str = "0.1"
    task_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class MemoryRecord:
    kind: str
    content: dict[str, Any]
    portability: str = "portable"
    id: str = field(default_factory=lambda: f"mem_{uuid4().hex}")
    created_at: str = field(default_factory=_utc_now)


@dataclass(frozen=True)
class ProposedAction:
    kind: str
    target: str
    content: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    provider_id: str
    output: dict[str, Any]
    proposed_actions: tuple[ProposedAction, ...] = ()
