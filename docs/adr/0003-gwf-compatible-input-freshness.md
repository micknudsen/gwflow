---
status: accepted
---

# Preserve gwf-compatible input-file checking

gwflow will not match input-file checksums before submission or make input-file checking stricter than standard gwf. This preserves gwf's inexpensive existence/timestamp behavior and its limits on detecting edits, rather than adding content scans or strict metadata-snapshot equality. Work-directory addressing is a separate decision: this requirement does not choose a digest scheme for a small computation description, and applying freshness after intermediate cleanup must respect the actual dependency relationships.
