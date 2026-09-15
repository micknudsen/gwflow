---
status: accepted
---

# Export versioned planning manifests without publishing runtime state

Phase 1 provides detached in-memory manifests, a pure validator, and explicit
JSON stdout export. It does not automatically write project metadata or load
execution state. Each schema-1 record includes intended computation, identity
and definition-API interpretation revisions, plus composition/software
provenance. Strict required fields and unknown-revision rejection give future
readers a defined boundary; incompatible changes need a new schema revision.

Validation may reconstruct declared graph relationships but cannot establish
that commands succeeded, outputs exist, freshness holds, or scheduler status
permits reuse. The manifest therefore records runtime evaluation as unevaluated
and contains no attempts or receipts. Publication and compatibility of required
runtime evidence remain later-phase work. This avoids introducing shared
mutable metadata or coordination into the planning-only phase.
