from __future__ import annotations

import hashlib, random, time
from dataclasses import dataclass
from urllib.parse import quote_plus
import httpx
from jobs_catcher import sources
from jobs_catcher.settings import Settings

class AdapterError(RuntimeError):
    pass

class BlockedSourceError(AdapterError):
    pass

@dataclass
class VacancyResult:
    source: str
    external_id: str
    title: str
    url: str
    company: str = ""
    location: str = ""
    description: str = ""
    raw: dict | None = None

class SourceAdapter:
    source = "base"
    base_url = ""
    path = "/search"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True, headers={"User-Agent": "JobsCatcher/1.0"})

    def build_search_url(self, query: str, preferences: dict, page: int = 0) -> str:
        return f"{self.base_url}{self.path}?q={quote_plus(query)}&page={page}"

    def _fetch(self, url: str) -> str:
        last = None
        for attempt in range(self.settings.http_retries + 1):
            if attempt:
                time.sleep(self.settings.http_delay_seconds + random.random() * self.settings.http_jitter_seconds)
            try:
                response = self.client.get(url)
                if response.status_code in {403, 429}:
                    raise BlockedSourceError(f"{self.source} blocked with {response.status_code}")
                response.raise_for_status()
                text = response.text
                if any(x in text.lower() for x in ["captcha", "access denied", "forbidden"]):
                    raise BlockedSourceError(f"{self.source} blocked")
                return text
            except BlockedSourceError:
                raise
            except Exception as exc:
                last = exc
        raise AdapterError(f"{self.source} fetch failed: {last}")

    def search(self, query: str, preferences: dict) -> list[VacancyResult]:
        results = []
        max_pages = max(1, min(3, self.settings.max_results_per_source))
        for page in range(max_pages):
            html = self._fetch(self.build_search_url(query, preferences, page))
            rows = sources.parse_search(self.source, html)
            if not rows:
                break
            for row in rows:
                results.append(VacancyResult(source=self.source, external_id=row["external_id"], title=row["title"], url=row["url"], raw=row))
                if len(results) >= self.settings.max_results_per_source:
                    return results
        return results

    def fetch_details(self, result: VacancyResult) -> VacancyResult:
        html = self._fetch(result.url)
        detail = sources.parse_detail(self.source, html)
        result.company = detail.get("company", "")
        result.description = detail.get("description", "")
        result.title = detail.get("title") or result.title
        result.raw = {**(result.raw or {}), **detail}
        return result

    def normalize(self, raw: VacancyResult) -> dict:
        description = raw.description or ""
        content_hash = hashlib.sha256(description.encode()).hexdigest() if description else None
        return {"source": raw.source, "external_id": raw.external_id, "title": raw.title, "company": raw.company, "location": raw.location, "source_url": raw.url, "canonical_url": sources.normalize_url(raw.url), "description": description, "requirements": "", "responsibilities": "", "conditions": "", "skills": [], "raw_metadata": raw.raw or {}, "content_hash": content_hash}
