# Issue tracker

Track specifications and implementation tickets in GitHub Issues in
`micknudsen/gwflow`.

- A multi-session phase begins with one parent specification issue.
- Implementation tickets are narrow tracer bullets with an observable demo,
  acceptance criteria, and explicit blockers.
- Prefer native GitHub sub-issue and blocking relationships; verify those
  relationships after publishing tickets.
- Link each implementation pull request to the ticket it closes.
- Pull requests are delivery artifacts, not an intake surface for issue triage.

The specification records the phase-level decisions. Durable terminology and
architectural decisions remain in `CONTEXT.md` and `docs/adr/` rather than being
maintained in a completed specification issue.
