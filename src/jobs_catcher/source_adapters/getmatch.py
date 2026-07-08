from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class GetMatchAdapter(SourceAdapter):
    source = "getmatch"
    base_url = "https://getmatch.ru"
    path = "/vacancies"
    query_param = "query"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/getmatch/vacancies/[^"\']+)["\'][^>]*>(.*?)</a>',)
    defaults = {**SourceAdapter.defaults, "work_format":"remote", "salary":{"from":150000,"to":250000,"currency":"RUB","gross":True}, "skills":["agents", "rag"]}
    def build_search_url(self, query, preferences, page=0):
        return f"{self.base_url}{self.path}?{urlencode({'query': query, 'page': page + 1})}"
