from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class GeekJobAdapter(SourceAdapter):
    source = "geekjob"
    base_url = "https://geekjob.ru"
    path = "/vacancies"
    query_param = "q"
    search_link_patterns = (r'<a[^>]+class=["\'][^"\']*job-title[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    def build_search_url(self, query, preferences, page=0):
        params = {"q": query, "page": page + 1}
        if preferences.get("locations") and not preferences.get("all_russia"):
            params["city"] = ",".join(preferences["locations"])
        if preferences.get("remote") or "remote" in preferences.get("work_formats", []):
            params["remote"] = "remote"
        if preferences.get("employment_types"):
            params["employment"] = ",".join(preferences["employment_types"])
        salary = preferences.get("salary") or {}
        if salary.get("minimum"):
            params["salary_from"] = str(salary["minimum"])
        return f"{self.base_url}{self.path}?{urlencode(params)}"
