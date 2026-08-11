"""Local policy gate. Providers can propose, never execute, actions."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from .schema import ProposedAction


class Decision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class LocalPolicy:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def decide(self, action: ProposedAction) -> Decision:
        if action.kind != "write_file":
            return Decision.CONFIRM
        target = (self.workspace / action.target).resolve()
        if self.workspace not in target.parents or target == self.workspace:
            return Decision.DENY
        if action.content is None:
            return Decision.DENY
        return Decision.ALLOW
