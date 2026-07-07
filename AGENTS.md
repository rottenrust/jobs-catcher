# Jobs Catcher Agent Rules

- Follow TDD: write or update tests before production behavior.
- Protect user data: never commit secrets, resumes, databases, uploads, run artifacts, or local env files.
- Preserve multi-user isolation: every user-facing query must be scoped by `user_id`.
- Build HTML safely: escape untrusted text and never render raw vacancy or resume HTML.
- Do not bypass CAPTCHA, rate limits, anti-bot controls, or site access restrictions.
- Run the full test suite before opening a PR.
- Keep scraping polite, sequential, bounded, and fixture-tested.

