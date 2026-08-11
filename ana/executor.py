"""Small, policy-gated action executor for the reference demo."""

from __future__ import annotations

from pathlib import Path

from .policy import Decision, LocalPolicy
from .schema import ProposedAction


class ActionExecutor:
    def __init__(self, policy: LocalPolicy) -> None:
        self.policy = policy

    def execute(self, action: ProposedAction) -> Path:
        decision = self.policy.decide(action)
        if decision is not Decision.ALLOW:
            raise PermissionError(f"action {action.kind} was {decision.value}")
        target = (self.policy.workspace / action.target).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(action.content or "", encoding="utf-8")
        return target
