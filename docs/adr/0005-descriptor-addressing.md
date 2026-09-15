---
status: accepted
---

# Address computations with a versioned lexical descriptor

Phase 1 uses identity revision 1: SHA-256 of ASCII JSON with sorted object keys,
no whitespace (`separators=(",", ":")`), and `ensure_ascii=True`. The full lowercase
hex digest is the address. The descriptor contains `identity_version`,
`definition` (`name`, `version`), and named typed `bindings`. Strings preserve
Unicode code points without normalization. Qualified definition names consist
of at least two dot-separated ASCII Python identifiers; authors own their
package namespace. Explicit version strings are opaque and immutable.

File descriptors have `kind: file`, `scope: project|external`, and `path`.
Relative paths are anchored to the explicitly selected project; paths are
lexically normalized without resolving symlinks. Project-contained paths become
relative; other paths are absolute. Relative and equivalent absolute paths
therefore agree. Symlink aliases remain distinct, and the project root itself
is lexical. No payload, stat, size, or timestamp participates. Identity is
project-scoped, even though equivalent descriptors in other projects can have
the same digest. There is no cross-project reuse service.

One current work directory is `work/<first-two-hex>/<digest>` and one current
result slot is `results/<first-two-hex>/<digest>` under the project. Retained
files go in the result slot, other declared files in work. Planning creates
neither. Paths are not historical snapshots.

Commands, parameters and environments are fixed by the explicit definition
version; their compiled descriptions are provenance, not hidden-code hashes.
Main, gwflow, gwf and definition-package releases do not salt the descriptor.
Attempts and scheduler jobs are absent. An incompatible identity encoding
requires a new identity revision; ordinary compatible software updates do not.
This selects the architecture's candidate addressing mechanism without changing
the accepted freshness or upstream invalidation requirements.
