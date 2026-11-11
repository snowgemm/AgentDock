"""The only legal task status transitions the worker may perform.

API-driven commands (pause/resume/cancel) are validated in the API service; the
worker never claims a PAUSED or terminal task. Every worker transition appends an
event in the same transaction (see store.py).
"""
from __future__ import annotations

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "QUEUED": frozenset({"RUNNING", "FAILED"}),
    "RETRYING": frozenset({"RUNNING", "FAILED"}),
    "RUNNING": frozenset(
        {"SUCCEEDED", "FAILED", "RETRYING", "RECOVERING", "VERIFYING", "WAITING_APPROVAL"}
    ),
    "RECOVERING": frozenset({"RUNNING", "FAILED"}),
    "VERIFYING": frozenset({"SUCCEEDED", "FAILED"}),
    "WAITING_APPROVAL": frozenset({"RUNNING", "FAILED"}),
}

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"})
# Statuses from which the worker may take over a task after claiming its lease.
CLAIMABLE_STATUSES = frozenset({"QUEUED", "RETRYING", "RUNNING", "RECOVERING"})


class IllegalTransition(Exception):
    def __init__(self, source: str, target: str) -> None:
        super().__init__(f"Illegal task transition {source} -> {target}.")
        self.source = source
        self.target = target


def assert_legal(source: str, target: str) -> None:
    if target not in LEGAL_TRANSITIONS.get(source, frozenset()):
        raise IllegalTransition(source, target)
