"""Portable, model-independent semantic memory."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import MemoryRecord


@dataclass(frozen=True)
class MigrationProfile:
    tier: str
    records: tuple[MemoryRecord, ...]


class MemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def add(self, record: MemoryRecord) -> None:
        self._records[record.id] = record

    def get(self, record_id: str) -> MemoryRecord:
        return self._records[record_id]

    def export_profile(self, tier: str = "portable") -> MigrationProfile:
        if tier != "portable":
            raise ValueError("v0.1 supports only the portable migration tier")
        return MigrationProfile(
            tier=tier,
            records=tuple(r for r in self._records.values() if r.portability == "portable"),
        )
