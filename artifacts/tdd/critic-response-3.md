# Critic Response 3

Critic issue: TDD-QA3-001
Decision: accepted
Changes: Replaced uniform source fixtures with varied source-shaped anonymized snippets and broadened parser support for href-based source IDs.
Reason: Saved files must catch a generic marker-only parser.
Tests changed: tests/fixtures/sources, tests/test_source_fixtures_realistic.py

Critic issue: TDD-QA3-002
Decision: partially accepted
Changes: Added broader auth/IDOR checks for anon, non-admin, deleted session, audit, export and vacancy/letter cross-user access.
Reason: Route-level authorization is critical. Direct resume/profile/criteria-by-id endpoints are not exposed in this MVP.
Tests changed: tests/test_web_security_extra.py

Critic issue: TDD-QA3-003
Decision: accepted
Changes: Added SQLite-backed PersistentJobQueue with restart and concurrent enqueue tests.
Reason: Worker restart must not lose queued jobs.
Tests changed: src/jobs_catcher/queue.py, tests/test_queue_persistence.py

Critic issue: TDD-QA3-004
Decision: partially accepted
Changes: Added binary fixture files for minimal text PDF, encrypted/no-text PDFs, real DOCX zip fixture, relationship-bearing DOCX, accepted safe filename checks, and redaction assertions.
Reason: Full production-grade PDF parsing remains limited by MVP text-layer extraction.
Tests changed: tests/fixtures/documents, tests/test_document_fixtures_binary.py

Critic issue: TDD-QA3-005
Decision: accepted
Changes: Added CSRF matrix including DELETE, login rotation from existing session, forced temp-password restriction, logout invalidation, endpoint rate-limit partition. Removed dead ternary expressions.
Reason: Auth lifecycle must be explicit.
Tests changed: tests/test_web_security_extra.py
