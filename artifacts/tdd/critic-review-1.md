Verdict: REJECT

ID: TDD-QA-001
Severity: blocker
Requirement: Multi-user closed FastAPI service, admin-created users, no self-registration, authorization, user isolation, IDOR prevention.
Location: docs/tdd-test-plan.md, tests/test_core.py
Problem: No API/integration tests exercise route-level access and isolation.
Why test can miss a defect: IDOR or public signup could pass unit-only checks.
Required correction: Add TestClient closed-flow and cross-user tests.

ID: TDD-QA-002
Severity: blocker
Requirement: Auth/session/CSRF/rate limit/password flow.
Location: tests/test_core.py
Problem: Auth tests are shallow and miss cookie/session/password-flow behavior.
Why test can miss a defect: Missing CSRF/cookie flags/session rotation could pass.
Required correction: Add endpoint and unit negatives for session and CSRF.

ID: TDD-QA-003
Severity: high
Requirement: Resume upload security.
Location: tests/test_documents_sources_security.py
Problem: ZIP expansion, path variants, MIME mismatch and malformed docs are undercovered.
Why test can miss a defect: Unsafe upload parser could pass.
Required correction: Add upload negative table and DOCX size test.

ID: TDD-QA-004
Severity: blocker
Requirement: Six HTML source adapters with realistic parser fixtures.
Location: tests/test_documents_sources_security.py
Problem: Same generic fixture for all sources.
Why test can miss a defect: Adapters can ignore source-specific shapes.
Required correction: Add per-source fixtures.

ID: TDD-QA-005
Severity: high
Requirement: Queue and scheduling.
Location: src/jobs_catcher/queue.py
Problem: Queue behavior untested.
Why test can miss a defect: Duplicate active jobs and stale recovery bugs could pass.
Required correction: Add in-memory queue tests.

ID: TDD-QA-006
Severity: high
Requirement: Profile/onboarding/criteria versioning.
Location: tests/test_core.py
Problem: YAML and invalid schema/version history undercovered.
Required correction: Add YAML, invalid threshold, old-version immutability and flow tests.

ID: TDD-QA-007
Severity: high
Requirement: Prescore, caps, average and strict candidate selection.
Problem: Caps/equality/empty runs/full-description checks missing.
Required correction: Add table tests.

ID: TDD-QA-008
Severity: high
Requirement: Codex validation and subprocess safety.
Problem: Negative validation and shell safety missing.
Required correction: Add schema, wrong id, score bounds, threshold consistency and command tests.

ID: TDD-QA-009
Severity: high
Requirement: Deduplication and source link aggregation.
Problem: No positive merge case.
Required correction: Add canonical/content-hash merge and conservative negative cases.

ID: TDD-QA-010
Severity: high
Requirement: UI categories/export/letters/viewed state.
Problem: No endpoint/e2e UI tests.
Required correction: Add fixture-backed flow tests.

ID: TDD-QA-011
Severity: high
Requirement: Audit and privacy.
Problem: Only password redaction tested.
Required correction: Add required metadata and broader redaction.

ID: TDD-QA-012
Severity: medium
Requirement: Maintainable tests.
Problem: Some compound tests are broad.
Required correction: Split high-risk tests where practical.

ID: TDD-QA-013
Severity: blocker
Requirement: End-to-end fixture workflow.
Problem: No full flow.
Required correction: Add admin/user/resume/onboarding/criteria/schedule/search/UI/letter/isolation flow.
