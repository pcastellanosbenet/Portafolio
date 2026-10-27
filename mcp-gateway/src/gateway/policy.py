"""Policy decisions for tool calls."""

from __future__ import annotations

from dataclasses import dataclass

from src.models import RiskLevel, ToolDescriptor


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of evaluating one tool call against policy."""

    allowed: bool
    approval_required: bool
    reason: str


class PolicyEngine:
    """Least-privilege policy: allowlist, scopes plus risk-based approvals."""

    def __init__(
        self,
        mode: str = "risk",
        allowlist: set[str] | None = None,
        required_scope: str | None = None,
        granted_scopes: set[str] | None = None,
    ) -> None:
        if mode not in {"auto", "always", "risk"}:
            raise ValueError(f"unknown approval mode: {mode}")
        self.mode = mode
        self.allowlist = allowlist or set()
        self.required_scope = required_scope or None
        self.granted_scopes = granted_scopes or set()

    def evaluate(self, descriptor: ToolDescriptor) -> PolicyDecision:
        """Decide whether a tool may run, needs approval, or is denied."""
        if self.allowlist and descriptor.name not in self.allowlist:
            return PolicyDecision(False, False, "tool is not in the allowlist")
        if self.required_scope and self.required_scope not in self.granted_scopes:
            return PolicyDecision(
                False, False, f"missing required scope: {self.required_scope}"
            )

        if self.mode == "always":
            return PolicyDecision(True, True, "approval mode is 'always'")
        if self.mode == "risk" and descriptor.risk is RiskLevel.DESTRUCTIVE:
            return PolicyDecision(True, True, "destructive tool requires approval")
        return PolicyDecision(True, False, "allowed by policy")
