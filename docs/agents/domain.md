# Domain documentation

gwflow uses a single domain context.

- `CONTEXT.md` is the glossary and authoritative source for domain terms.
- `docs/design.md` records accepted requirements and decisions.
- `docs/architecture-proposal.md` records the architecture baseline.
- `docs/implementation-plan.md` records phases and acceptance scenarios.
- `docs/adr/` contains durable consequential decisions.

Read the glossary whenever a change introduces or redefines a domain noun.
Read the relevant ADRs before changing public interfaces, identity, freshness,
scheduling, retained evidence, or execution boundaries. New consequential
trade-offs belong in an ADR; implementation discoveries that do not change an
accepted decision belong in the relevant product documentation or tests.
