from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class HHAdapter(SourceAdapter):
    source = "hh"
    base_url = "https://hh.ru"
    path = "/search/vacancy"
    query_param = "text"
    search_link_patterns = (r'<a[^>]+data-qa=["\']serp-item__title["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    detail_company_patterns = (r'data-qa=["\']vacancy-company-name["\'][^>]*>(.*?)<',)
    defaults = {**SourceAdapter.defaults, "work_format":"hybrid", "skills":["analytics", "api"]}
    def build_search_url(self, query, preferences, page=0):
        params = {"text": query, "page": page}
        if preferences.get("locations"): params["area"] = ",".join(preferences["locations"])
        if preferences.get("remote"): params["schedule"] = "remote"
        return f"{self.base_url}{self.path}?{urlencode(params)}"
