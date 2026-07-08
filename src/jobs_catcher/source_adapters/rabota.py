from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class RabotaAdapter(SourceAdapter):
    source = "rabota"
    base_url = "https://www.rabota.ru"
    path = "/vacancy/"
    query_param = "query"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/rabota/vacancy/[^"\']+)["\'][^>]*>(.*?)</a>',)
    def build_search_url(self, query, preferences, page=0):
        params = {"query": query, "page": page + 1}
        if preferences.get("locations") and not preferences.get("all_russia"):
            params["region"] = ",".join(preferences["locations"])
        if preferences.get("remote") or "remote" in preferences.get("work_formats", []):
            params["schedule"] = "remote"
        if preferences.get("employment_types"):
            params["employment"] = ",".join(preferences["employment_types"])
        salary = preferences.get("salary") or {}
        if salary.get("minimum"):
            params["salary"] = str(salary["minimum"])
        return f"{self.base_url}{self.path}?{urlencode(params)}"
