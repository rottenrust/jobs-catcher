# Security

Passwords use Argon2id. Sessions are server-side and store only token hashes. Cookies are HttpOnly, SameSite=Lax, and should be Secure in production TLS. Mutating routes require CSRF. All user data access is scoped by current user or admin role. Upload names are sanitized and uploads live outside the web root. Raw vacancy HTML, full resumes, passwords, tokens, and full letters are not written to audit logs. CAPTCHA and anti-bot bypass is forbidden.
