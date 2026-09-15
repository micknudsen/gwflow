---
status: accepted
---

# Restrict dependencies between subpipelines to retained outputs

A subpipeline may consume files from another subpipeline only through the producer's declared retained-output interface. This makes internal-intermediate cleanup compatible with downstream reruns and independent subpipeline evolution, at the cost of requiring authors to expose any newly needed file explicitly instead of reaching into another subpipeline's work files. Changing a published output interface requires a new subpipeline version and invalidates affected downstream computations; the execution mechanism remains open.

A downstream subpipeline waits for the entire required upstream subpipeline to succeed, even when an early branch has already produced all files it consumes. This gives the subpipeline dependency a consistent completion boundary at the cost of some early execution overlap; the ordering mechanism remains open and must respect the file-freshness rules.
