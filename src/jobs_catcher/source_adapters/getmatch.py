from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class GetMatchAdapter(SourceAdapter):
    source = "getmatch"
    base_url = "https://getmatch.ru"
    path = "/vacancies"
    query_param = "query"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/getmatch/vacancies/[^"\']+)["\'][^>]*>(.*?)</a>',)
    detail_title_pattern = r'<h1[^>]+class=["\'][^"\']*vacancy__title[^"\']*["\'][^>]*>(.*?)</h1>'
    detail_company_patterns = (r'class=["\'][^"\']*company[^"\']*["\'][^>]*>(.*?)</',)
    detail_location_patterns = (r'class=["\'][^"\']*location[^"\']*["\'][^>]*>(.*?)</',)
    detail_description_patterns = (r'class=["\'][^"\']*about-vacancy[^"\']*["\'][^>]*>(.*?)</section>',)
    detail_salary_patterns = (r'class=["\'][^"\']*salary[^"\']*["\'][^>]*>(.*?)</',)
    detail_work_format_patterns = (r'class=["\'][^"\']*work-format[^"\']*["\'][^>]*>(.*?)</',)
    detail_employment_patterns = (r'class=["\'][^"\']*employment-type[^"\']*["\'][^>]*>(.*?)</',)
    detail_published_patterns = (r'<time[^>]+class=["\'][^"\']*published[^"\']*["\'][^>]+datetime=["\']([^"\']+)',)
    detail_requirements_patterns = (r'<h3>\s*Requirements\s*</h3>\s*<p[^>]*>(.*?)</p>',)
    detail_responsibilities_patterns = (r'<h3>\s*Responsibilities\s*</h3>\s*<p[^>]*>(.*?)</p>',)
    detail_conditions_patterns = (r'<h3>\s*Conditions\s*</h3>\s*<p[^>]*>(.*?)</p>',)
    detail_skills_patterns = (r'class=["\'][^"\']*skill[^"\']*["\'][^>]*>(.*?)</',)
    def build_search_url(self, query, preferences, page=0):
        params = {"query": query, "page": page + 1}
        if preferences.get("locations") and not preferences.get("all_russia"):
            params["city"] = ",".join(preferences["locations"])
        if preferences.get("remote") or "remote" in preferences.get("work_formats", []):
            params["remote"] = "remote"
        if preferences.get("employment_types"):
            params["employment"] = ",".join(preferences["employment_types"])
        salary = preferences.get("salary") or {}
        if salary.get("minimum"):
            params["salary"] = str(salary["minimum"])
        if preferences.get("seniority"):
            params["grade"] = ",".join(preferences["seniority"])
        return f"{self.base_url}{self.path}?{urlencode(params)}"
