---
status: accepted
---

# Reject visible definition changes across submissions

Phase 2 will compare visible computational declarations with saved definitions
for the same bound computation and reject mismatches under the same published
subpipeline version, requiring a new version instead of silently reusing or
replacing a differently defined
computation. Operational resource overrides and provenance-only changes remain
permitted. This extends Phase 1's within-plan checks at the cost of constraining
editable development under an unchanged version; it does not inspect hidden
scripts or installed tools, and immutability remains an author contract.

The comparison is scoped to repeated uses of the same bound computation. Bound
commands and paths can legitimately differ across datasets, so Phase 2 does not
introduce a project-wide registry or compare complete compiled targets across
different bindings. Cross-dataset published-version immutability remains an
author contract. Computational declarations are compared while operational
resources and provenance-only differences are excluded.

Commands are compared literally, so even a whitespace-only edit requires a new
version when the command text changes. Internal target renames also require a
new version. Normalize representation-only ordering of mappings and graph
relationships, but do not infer shell equivalence. Operational resources and
provenance remain excluded from this comparison.

This decision is accepted but not implemented. Missing or malformed saved
evidence follows automatic recovery, subject to trustworthy job tracking; it is
not itself proof of a definition-contract violation. Exact comparison fields
and their canonical representation must be documented and tested in the
implementation ticket without weakening these rules.
