# Runtime evidence compatibility

Execution records intentionally exclude gwflow and gwf release provenance from
completion authority. Compatible software upgrades therefore do not invalidate
otherwise valid retained evidence.

An unreadable or unsupported indispensable execution-computation record is
never interpreted as success. With trustworthy job associations it enters the
ordinary recovery path. In contrast, unreadable or unsupported authoritative
`job-tracking` cannot establish that no active job exists, so `run --dry-run`
returns a blocked JSON preview and exit 1. It does not fabricate completion from
surviving result files.
