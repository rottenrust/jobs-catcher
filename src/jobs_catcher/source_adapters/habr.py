from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class HabrAdapter(SourceAdapter):
    source = "habr"
    base_url = "https://career.habr.com"
    path = "/vacancies"
    query_param = "q"
    search_link_patterns = (r'<a[^>]+class=["\'][^"\']*vacancy-card__title[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    def build_search_url(self, query, preferences, page=0):
        params = {"q": query, "page": page + 1}
        if preferences.get("locations") and not preferences.get("all_russia"):
            params["locations"] = ",".join(preferences["locations"])
        if preferences.get("remote") or "remote" in preferences.get("work_formats", []):
            params["remote"] = "remote"
        if preferences.get("employment_types"):
            params["employment_type"] = ",".join(preferences["employment_types"])
        salary = preferences.get("salary") or {}
        if salary.get("minimum"):
            params["salary"] = str(salary["minimum"])
        return f"{self.base_url}{self.path}?{urlencode(params)}"
