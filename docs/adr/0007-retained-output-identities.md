---
status: accepted
---

# Encode retained-output bindings using upstream computation identity

A file input may bind to `OutputRef(occurrence, output)` in the main composition.
The descriptor stores `kind: output`, the upstream `computation` digest and the
public `output` name. The resolved physical path remains in the compiled plan.
Occurrence names do not enter identity, so equivalent producer occurrences
remain interchangeable. This additive revision-1 binding form leaves existing
file/list/data addresses intact. Consumers incorporate the producer identity
transitively without comparing output payloads or requiring them to exist.

Every connection carries a separate whole-producer completion obligation.
Actual file edges record only files a target consumes. No scheduler enforcement
or completion conclusion is part of planning.

Raw file bindings and builder-supplied input paths into another planned
computation's owned work/result trees are rejected unless the target input is
resolved through a declared retained-output connection. Even a retained file
requires the reference API, preventing loss of upstream identity and completion
obligations. Enforcement is lexical and limited to the current planned graph;
it does not resolve symlinks or police paths in unplanned computations. Exposing
an internal file requires a new producer version and declared retained output.
