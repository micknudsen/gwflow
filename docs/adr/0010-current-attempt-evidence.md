---
status: accepted
---

# Separate current-attempt authority from execution history

Phase 2 will require a computation manifest, a durable per-target record selecting
the current attempt, and that attempt's success receipt. The compute job publishes
its receipt only after successful command execution and required output checks;
completion is derived from those records together with scheduler status and
freshness. A receipt's existence or recency cannot select the current attempt.
This explicit separation prevents late historical evidence from certifying a
replacement attempt, at the cost of maintaining an additional required record.

Retained logs, superseded receipts, and derived summaries are diagnostic history;
losing them alone does not require recomputation. Missing current indispensable
evidence follows the accepted automatic recovery rules, including active-job
precedence. Lost authoritative job associations or uncertain scheduler
acceptance are different: submission remains blocked until the manual recovery
procedure establishes quiescence and reconciles tracking. Success receipts
cannot establish that no untracked active job exists. This decision is accepted
but unimplemented; concrete record schemas remain implementation-ticket work.
Quiescence is not a prerequisite for ordinary missing-evidence recovery with
trustworthy tracking, which continues to preserve known active jobs.
