# Source Adapters

Adapters share `search(query, preferences)`, `fetch_details(result)`, and `normalize(raw)` at the design level; MVP parser functions are fixture-backed for hh.ru, Habr Career, SuperJob, Работа.ру, GeekJob, and GetMatch. Requests must be sequential, delayed, bounded, and fail source-local on timeout, 403, 429, or CAPTCHA. CI never uses live sites.
