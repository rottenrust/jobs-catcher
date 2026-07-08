from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class SuperJobAdapter(SourceAdapter):
    source = "superjob"
    base_url = "https://www.superjob.ru"
    path = "/vacancy/search/"
    query_param = "keywords"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/vakansii/[^"\']+)["\'][^>]*>(.*?)</a>',)
    def build_search_url(self, query, preferences, page=0):
        params = {"keywords": query, "page": page + 1}
        if preferences.get("locations") and not preferences.get("all_russia"):
            params["town"] = ",".join(preferences["locations"])
        if preferences.get("remote") or "remote" in preferences.get("work_formats", []):
            params["remote_work"] = "remote"
        if preferences.get("employment_types"):
            params["employment"] = ",".join(preferences["employment_types"])
        salary = preferences.get("salary") or {}
        if salary.get("minimum"):
            params["payment_from"] = str(salary["minimum"])
        return f"{self.base_url}{self.path}?{urlencode(params)}"
