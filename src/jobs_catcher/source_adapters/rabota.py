from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class RabotaAdapter(SourceAdapter):
    source = "rabota"
    base_url = "https://www.rabota.ru"
    path = "/vacancy/"
    query_param = "query"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/rabota/vacancy/[^"\']+)["\'][^>]*>(.*?)</a>',)
    defaults = {**SourceAdapter.defaults, "work_format":"office", "skills":["requirements", "api"]}
    def build_search_url(self, query, preferences, page=0):
        return f"{self.base_url}{self.path}?{urlencode({'query': query, 'page': page + 1})}"
