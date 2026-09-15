---
status: accepted
---

# Separate composition occurrences from computation nodes

A main pipeline names each use of an explicit subpipeline definition and its
bindings. Occurrences with equivalent descriptors point to one computation
node and current result slot. Occurrence names, main versions, and package
provenance do not enter reusable identity. This avoids multiple result owners
for the same computation while preserving every use in composition provenance.

Python exports may be selected with an explicit expected definition name and
version. Within one plan, a published name/version must agree on input/output
interfaces, parameters, and builder callable identity. Equivalent bindings must
also agree on their compiled target description. This deliberately conservative
check can reject separately constructed wrappers that happen to compute the
same thing; authors should export and reuse their canonical builder. Hidden
code inspection and comparisons against historical saved definitions remain
outside this check. Published-version immutability is still an author contract.
