# TDD Test Plan

## Requirement Map

| Area | Tests |
| --- | --- |
| Auth and sessions | password policy, bootstrap admin, Argon2-compatible hashing boundary, server-side session hashing, rotation, CSRF, login rate limit |
| Authorization | admin-only operations, user data isolation, IDOR prevention, deleted user access |
| Resume handling | extension, MIME and signature checks, unsafe filenames, path traversal, PDF text-layer detection, DOCX ZIP corruption and expansion limit |
| Profile and criteria | schema validation, JSON/YAML import-export, versioning, threshold validation |
| Scheduling and queue | minimum interval, one active search job per user, stale job recovery, idempotency |
| Sources | six fixture-backed HTML adapters, missing fields, blocked pages, changed HTML, URL normalization |
| Deduplication | conservative canonicalization, similar title alone does not merge, multiple source links |
| Scoring | 0-22 bounds, caps, thresholds, average per user/run, `prescore > average` selection |
| Codex integration | subprocess args, no shell, prompt-injection boundaries, JSON validation, one retry contract |
| UI artifacts | categories, viewed state, plain-text export, cover letter <=300 chars |
| Audit and privacy | required events, redaction of passwords, sessions, resumes, full letters |

## Initial Test Set

The first red suite covers importable public interfaces and high-risk domain behavior before production logic. It is split into unit, parser, security, and integration-style fixture tests under `tests/`.

## Red Gate Rule

Before production logic, tests must collect successfully and fail for expected `NotImplementedError` or strict assertions, not because of missing fixtures, import errors, or pytest configuration.

