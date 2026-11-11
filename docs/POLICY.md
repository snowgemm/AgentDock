# Tool policy, approvals and audit

**Status:** the framework is implemented and tested with **test-only tools**. The only production tool is the read-only `get_task_context`; no production side-effect tool exists, so nothing in AgentDock can yet take a consequential action.

## Typed tools

`ToolDefinition` (`app/agent/tools.py`) carries a name, a pydantic argument model (also the source of the JSON Schema sent to the model), resource scopes, timeout, output limit, an `enabled` flag, a risk class (`read_only` / `reversible` / `consequential`), an `idempotent` flag and a `describe` hook that yields the target resource, expected effect and display-safe key arguments. The model only proposes calls; the registry resolves names and validates arguments server-side.

## PDP and PEP

`PolicyEngine.decide` (`app/policy/pdp.py`) is a pure function. Immediately before **every** execution the `PolicyEnforcingExecutor` (`app/policy/executor.py`) re-reads identity and task facts from PostgreSQL under RLS (task exists in the tenant, creator's membership and `is_active`, task is `RUNNING`/`WAITING_APPROVAL`), then decides: `DENY` (disabled/denylisted tool, revoked membership, inactive user, task not running, target outside the tool's resource scopes), `ALLOW` (read-only, reversible), or `REQUIRE_APPROVAL` (consequential). The model cannot grant or override anything, and an approval flag can never override a hard denial. Every decision and every execution is written to `audit_events`.

## Approvals

* An approval is bound to a SHA-256 digest of the canonical action: tenant, task, tool, validated arguments, target, risk class and policy version. Any change — including a policy version bump — produces a different digest, so the old approval does not match.
* The approver is shown tool, target, redacted key arguments, risk, expected effect and expiry, and the decision request must echo the digest it displayed (`POST /api/v1/approvals/{id}/decision` → 409 `digest_mismatch` otherwise). Approvals expire (default 15 minutes) and can be revoked before use.
* Execution spends the approval atomically (`UPDATE … WHERE status='APPROVED' AND expires_at > now()`) in the **same transaction** that records the STARTED receipt, so an approval is never spent without proof the action began and an action never begins without an approval. Replays are rejected (`approval_replayed`), as are expired, denied, revoked, missing or cross-tenant approvals. A step with a STARTED receipt but no completion is never re-run (`UncertainSideEffect`); a completed step returns its stored result.
* While waiting the task is `WAITING_APPROVAL` and the worker keeps its lease heartbeat. The single user of a personal workspace may approve their own task's action; multi-user separation-of-duties rules are not implemented.

## Redaction and audit

Secrets are masked by key name and by value pattern (`app/policy/redact.py`) in audit details, approval displays and tool output. This is best-effort pattern matching, not a guarantee. `audit_events` is append-only for the application roles (INSERT/SELECT only). Rejected approval *attempts* at the API (wrong digest, expired) are returned to the caller but not audited.
