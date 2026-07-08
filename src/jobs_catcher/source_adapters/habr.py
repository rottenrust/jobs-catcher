from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class HabrAdapter(SourceAdapter):
    source = "habr"
    base_url = "https://career.habr.com"
    path = "/vacancies"
    query_param = "q"
    search_link_patterns = (r'<a[^>]+class=["\'][^"\']*vacancy-card__title[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    defaults = {**SourceAdapter.defaults, "work_format":"remote", "skills":["rag", "integrations"]}
    def build_search_url(self, query, preferences, page=0):
        return f"{self.base_url}{self.path}?{urlencode({'q': query, 'page': page + 1})}"
