from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class GeekJobAdapter(SourceAdapter):
    source = "geekjob"
    base_url = "https://geekjob.ru"
    path = "/vacancies"
    query_param = "q"
    search_link_patterns = (r'<a[^>]+class=["\'][^"\']*job-title[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    defaults = {**SourceAdapter.defaults, "employment_type":"contract", "skills":["product", "chatbot"]}
    def build_search_url(self, query, preferences, page=0):
        return f"{self.base_url}{self.path}?{urlencode({'q': query, 'page': page + 1})}"
