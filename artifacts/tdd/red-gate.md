# Red Gate

Command: `.venv/bin/python -m pytest`

- Collected tests: 24
- Passed: 0
- Failed: 24
- Import/config/fixture errors: 0
- Expected failure reason: public interfaces intentionally raise `NotImplementedError` before production logic.

Confirmation: pytest configuration, package imports, and parametrized source fixtures are valid. The suite is red because core business behavior is not implemented yet.
