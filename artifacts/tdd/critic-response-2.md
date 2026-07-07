# Critic Response 2

Critic issue: TDD-QA2-001
Decision: accepted
Changes: Added saved per-source search/detail/blocked fixtures under tests/fixtures/sources and tests that read them.
Tests changed: tests/test_source_fixtures_realistic.py

Critic issue: TDD-QA2-002
Decision: accepted
Changes: Added auth matrix for unauthenticated, non-admin, deleted user/session, cross-user vacancy/export/letter.
Tests changed: tests/test_web_security_extra.py

Critic issue: TDD-QA2-003
Decision: accepted
Changes: Enforced must-change-password before app use; added logout invalidation, route CSRF matrix, session rotation, endpoint rate-limit.
Tests changed: tests/test_web_security_extra.py, tests/test_web_e2e.py

Critic issue: TDD-QA2-004
Decision: partially accepted
Changes: Added safe-name, DOCX relationship/no-body/zip expansion and redaction tests. Real production binary fixture coverage remains a documented residual risk for v1.
Tests changed: tests/test_documents_extra.py

Critic issue: TDD-QA2-005
Decision: accepted
Changes: Added strict stdout JSON parsing and subprocess shell=False retry/timeout contract.
Tests changed: tests/test_codex_runner.py

Critic issue: TDD-QA2-006
Decision: partially accepted
Changes: Removed dead assertion, added API schedule validation and one-active job invariant. Persistence-backed race tests are documented residual risk.
Tests changed: tests/test_web_e2e.py, tests/test_core_extra.py

Critic issue: TDD-QA2-007
Decision: accepted
Changes: Added criteria unknown/missing schema and two-user isolation checks through flow.
Tests changed: tests/test_core_extra.py, tests/test_web_security_extra.py

Critic issue: TDD-QA2-008
Decision: accepted
Changes: Added nested audit redaction and event metadata checks.
Tests changed: tests/test_core_extra.py, tests/test_web_security_extra.py

Critic issue: TDD-QA2-009
Decision: partially accepted
Changes: New tests are focused; retained one broad happy-path e2e as a smoke contract.
Tests changed: tests/*.py
