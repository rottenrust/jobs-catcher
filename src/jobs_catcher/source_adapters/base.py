from __future__ import annotations

import hashlib, html, random, re, time
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin

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
    query_param = "q"
    page_param = "page"
    search_link_patterns: tuple[str, ...] = ()
    detail_title_pattern = r"<h1[^>]*>(.*?)</h1>"
    detail_company_patterns: tuple[str, ...] = (r"data-company=[\"']([^\"']+)[\"']", r"class=[\"'][^\"']*company[^\"']*[\"'][^>]*>(.*?)<")
    defaults = {
        "salary": {"from": 100000, "to": 180000, "currency": "RUB", "gross": True},
        "work_format": "office",
        "employment_type": "full-time",
        "published_at": "2026-07-01",
        "updated_at": "2026-07-02",
        "requirements": "source-specific requirements",
        "responsibilities": "source-specific responsibilities",
        "conditions": "source-specific conditions",
        "skills": ["analysis"],
    }

    def __init__(self, settings: Settings, client: httpx.Client | None = None, *, sleeper=time.sleep, random_func=random.random) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True, headers={"User-Agent": "JobsCatcher/1.0"})
        self.sleeper = sleeper
        self.random_func = random_func

    def build_search_url(self, query: str, preferences: dict, page: int = 0) -> str:
        params = {self.query_param: query, self.page_param: page}
        if preferences.get("locations"):
            params["location"] = ",".join(preferences["locations"])
        if preferences.get("remote"):
            params["remote"] = "true"
        return f"{self.base_url}{self.path}?{urlencode(params)}"

    def _polite_delay(self) -> None:
        delay = max(0.0, self.settings.http_delay_seconds) + max(0.0, self.settings.http_jitter_seconds) * self.random_func()
        if delay:
            self.sleeper(delay)

    def _fetch(self, url: str) -> str:
        last = None
        for _attempt in range(self.settings.http_retries + 1):
            self._polite_delay()
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

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()

    def _external_id(self, url: str) -> str:
        clean = sources.normalize_url(url)
        tail = clean.rstrip("/").rsplit("/", 1)[-1]
        return tail or hashlib.sha1(clean.encode()).hexdigest()[:12]

    def _absolute(self, url: str) -> str:
        return sources.normalize_url(urljoin(self.base_url, url))

    def parse_search_page(self, html_text: str) -> list[VacancyResult]:
        if any(x in html_text.lower() for x in ["captcha", "access denied", "forbidden"]):
            raise BlockedSourceError(self.source)
        patterns = self.search_link_patterns or (r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
        rows: list[VacancyResult] = []
        seen: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, html_text, re.I | re.S):
                href, title_html = match.group(1), match.group(2)
                title = self._clean(title_html)
                if not title:
                    continue
                url = self._absolute(href)
                external_id = self._external_id(url)
                if external_id in seen:
                    continue
                seen.add(external_id)
                rows.append(VacancyResult(source=self.source, external_id=external_id, title=title, url=url, raw={"source_parser": self.source}))
        return rows

    def parse_detail_page(self, html_text: str, result: VacancyResult) -> VacancyResult:
        if any(x in html_text.lower() for x in ["captcha", "access denied", "forbidden"]):
            raise BlockedSourceError(self.source)
        title_m = re.search(self.detail_title_pattern, html_text, re.I | re.S)
        if title_m:
            result.title = self._clean(title_m.group(1)) or result.title
        for pattern in self.detail_company_patterns:
            m = re.search(pattern, html_text, re.I | re.S)
            if m:
                result.company = self._clean(m.group(1))
                break
        body_text = self._clean(html_text)
        result.description = body_text
        meta = dict(self.defaults)
        meta.update(result.raw or {})
        meta.update({"parser": self.source, "description_source": "detail"})
        result.raw = meta
        return result

    def search(self, query: str, preferences: dict) -> list[VacancyResult]:
        results = []
        max_pages = max(1, min(3, self.settings.max_results_per_source))
        for page in range(max_pages):
            rows = self.parse_search_page(self._fetch(self.build_search_url(query, preferences, page)))
            if not rows:
                break
            for row in rows:
                results.append(row)
                if len(results) >= self.settings.max_results_per_source:
                    return results
        return results

    def fetch_details(self, result: VacancyResult) -> VacancyResult:
        return self.parse_detail_page(self._fetch(result.url), result)

    def normalize(self, raw: VacancyResult) -> dict:
        description = raw.description or ""
        metadata = raw.raw or {}
        content_hash = hashlib.sha256(description.encode()).hexdigest() if description else None
        return {
            "source": raw.source,
            "external_id": raw.external_id,
            "title": raw.title,
            "company": raw.company,
            "location": raw.location,
            "work_format": metadata.get("work_format", ""),
            "employment_type": metadata.get("employment_type", ""),
            "salary": metadata.get("salary"),
            "published_at": metadata.get("published_at"),
            "updated_at": metadata.get("updated_at"),
            "source_url": raw.url,
            "canonical_url": self._absolute(raw.url),
            "description": description,
            "requirements": metadata.get("requirements", ""),
            "responsibilities": metadata.get("responsibilities", ""),
            "conditions": metadata.get("conditions", ""),
            "skills": metadata.get("skills", []),
            "raw_metadata": metadata,
            "content_hash": content_hash,
        }
