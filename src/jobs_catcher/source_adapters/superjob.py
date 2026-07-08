from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class SuperJobAdapter(SourceAdapter):
    source = "superjob"
    base_url = "https://www.superjob.ru"
    path = "/vacancy/search/"
    query_param = "keywords"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/vakansii/[^"\']+)["\'][^>]*>(.*?)</a>',)
    defaults = {**SourceAdapter.defaults, "salary":{"from":120000,"to":200000,"currency":"RUB","gross":False}, "skills":["systems", "analysis"]}
    def build_search_url(self, query, preferences, page=0):
        return f"{self.base_url}{self.path}?{urlencode({'keywords': query, 'page': page + 1})}"
