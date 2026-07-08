from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class GeekJobAdapter(SourceAdapter):
    source = "geekjob"
    base_url = "https://geekjob.ru"
    path = "/vacancies"
    query_param = "q"
    search_link_patterns = (r'<a[^>]+class=["\'][^"\']*job-title[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    detail_title_pattern = r'<h1[^>]+class=["\'][^"\']*job-title[^"\']*["\'][^>]*>(.*?)</h1>'
    detail_company_patterns = (r'class=["\'][^"\']*company[^"\']*["\'][^>]*>(.*?)</',)
    detail_location_patterns = (r'class=["\'][^"\']*city[^"\']*["\'][^>]*>(.*?)</',)
    detail_description_patterns = (r'class=["\'][^"\']*description[^"\']*["\'][^>]*>(.*?)</div>',)
    detail_salary_patterns = (r'class=["\'][^"\']*salary[^"\']*["\'][^>]*>(.*?)</',)
    detail_work_format_patterns = (r'class=["\'][^"\']*format[^"\']*["\'][^>]*>(.*?)</',)
    detail_employment_patterns = (r'class=["\'][^"\']*employment[^"\']*["\'][^>]*>(.*?)</',)
    detail_published_patterns = (r'<time[^>]+class=["\'][^"\']*date[^"\']*["\'][^>]+datetime=["\']([^"\']+)',)
    detail_requirements_patterns = (r'<h4>\s*Requirements\s*</h4>\s*<p[^>]*>(.*?)</p>',)
    detail_responsibilities_patterns = (r'<h4>\s*Responsibilities\s*</h4>\s*<p[^>]*>(.*?)</p>',)
    detail_conditions_patterns = (r'<h4>\s*Conditions\s*</h4>\s*<p[^>]*>(.*?)</p>',)
    detail_skills_patterns = (r'class=["\'][^"\']*tag[^"\']*["\'][^>]*>(.*?)</',)
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
