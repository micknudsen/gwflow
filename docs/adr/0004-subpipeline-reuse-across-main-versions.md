---
status: accepted
---

# Preserve subpipeline reuse across main-pipeline versions

A main-pipeline version describes composition and belongs in provenance, but changing that version alone does not invalidate otherwise unchanged, reusable subpipelines. Invalidation follows relevant upstream computation changes even when new output bytes happen to match, preserving independent subpipeline reuse while retaining conservative provenance dependencies. The exact computation identity representation remains open.
