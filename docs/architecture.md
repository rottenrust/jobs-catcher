# Architecture

FastAPI renders server-side HTML and exposes small JSON endpoints. The code is separated into auth, documents, criteria, source adapters, deduplication, scoring, Codex integration, queue, export, audit, worker, and web routes. SQLite WAL is the intended persistent store on VPS; tests use an in-memory store for deterministic vertical slices. Web and worker run as separate systemd processes. HTTP calls and Codex calls must happen outside open SQLite transactions.
