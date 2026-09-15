---
status: accepted
---

# Require a statically planned job graph

The first release requires every job and dependency to be known before initial submission. The submission command exits without a controller or orchestration jobs. This excludes runtime expansion into newly discovered scheduler jobs; computation that discovers data within an already planned job remains possible. The concrete gwf integration is still open.
