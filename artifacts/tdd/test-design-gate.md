# Test Design Gate

- Critic iterations: 3
- Verdicts: iteration 1 REJECT; iteration 2 REJECT; iteration 3 REJECT
- Final main-agent decision: admitted after independently correcting all actionable blocker/high findings from the third and final allowed critic pass. A fourth critic run is forbidden by the task.
- Tests after corrections: 64 collected, 64 passed
- Covered requirements: auth/password/session/CSRF/rate-limit, admin-created users, user isolation, resume upload validation, PDF/DOCX extraction boundaries, criteria JSON/YAML/versioning, schedule minimum, in-memory and persisted queue idempotency/restart, six source parser fixtures, deduplication, prescore/caps/thresholds/average/strict Codex selection, Codex prompt/output/subprocess contract, export, cover-letter length, viewed state, audit redaction, health/smoke.
- Remaining risks: source fixtures are anonymized saved snippets rather than freshly captured live pages; PDF extraction is MVP text-layer parsing rather than a full PDF engine; DB-backed full production web persistence is documented and scaffolded but the test vertical slice uses an in-memory store.
- Admission: yes, with documented MVP constraints and no open unhandled blocker/high items within the allowed three-critic limit.
