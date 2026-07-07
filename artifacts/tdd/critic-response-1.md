# Critic Response 1

Critic issue: TDD-QA-001
Decision: accepted
Changes: Added FastAPI TestClient closed-flow and isolation tests.
Reason: Route-level security must be covered.
Tests changed: tests/test_web_e2e.py

Critic issue: TDD-QA-002
Decision: accepted
Changes: Added endpoint password-change, session cookie and CSRF tests plus unit CSRF/session checks.
Reason: Auth invariants are security-critical.
Tests changed: tests/test_core.py, tests/test_web_e2e.py

Critic issue: TDD-QA-003
Decision: accepted
Changes: Added upload negative table and DOCX expansion/missing document cases.
Reason: Upload parser must fail closed.
Tests changed: tests/test_documents_sources_security.py

Critic issue: TDD-QA-004
Decision: accepted
Changes: Added per-source fixture generator with source-specific DOM markers.
Reason: Generic parser fixtures were too weak.
Tests changed: tests/test_documents_sources_security.py

Critic issue: TDD-QA-005
Decision: accepted
Changes: Added queue idempotency and stale recovery tests.
Reason: Worker restart and duplicate search prevention are MVP requirements.
Tests changed: tests/test_core.py

Critic issue: TDD-QA-006
Decision: accepted
Changes: Added YAML, threshold validation, and flow-level criteria version checks.
Reason: Criteria is user-editable and versioned.
Tests changed: tests/test_core.py, tests/test_web_e2e.py

Critic issue: TDD-QA-007
Decision: accepted
Changes: Added caps, equality exclusion, empty average and deterministic evidence tests.
Reason: Candidate selection must be exact.
Tests changed: tests/test_core.py

Critic issue: TDD-QA-008
Decision: accepted
Changes: Added negative Codex result validation and command-list assertion.
Reason: External tool boundary must fail closed.
Tests changed: tests/test_core.py

Critic issue: TDD-QA-009
Decision: accepted
Changes: Added positive dedup/link aggregation tests.
Reason: Never-merge implementation would be insufficient.
Tests changed: tests/test_core.py

Critic issue: TDD-QA-010
Decision: accepted
Changes: Added e2e category, viewed, export and letter tests.
Reason: UI behavior is part of MVP.
Tests changed: tests/test_web_e2e.py

Critic issue: TDD-QA-011
Decision: accepted
Changes: Added audit redaction for token/session/resume/letter and flow audit checks.
Reason: Privacy leakage must be prevented.
Tests changed: tests/test_core.py, tests/test_web_e2e.py

Critic issue: TDD-QA-012
Decision: partially accepted
Changes: Split new high-risk tests; kept a few compact smoke-style tests for readability.
Reason: The suite should be focused but still fast for MVP.
Tests changed: tests/*.py

Critic issue: TDD-QA-013
Decision: accepted
Changes: Added fixture-backed end-to-end flow and adversarial isolation check.
Reason: Vertical slice must be proven.
Tests changed: tests/test_web_e2e.py
