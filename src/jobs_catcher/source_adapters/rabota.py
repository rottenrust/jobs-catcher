from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class RabotaAdapter(SourceAdapter):
    source = "rabota"
    base_url = "https://www.rabota.ru"
    path = "/vacancy/"
    query_param = "query"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/rabota/vacancy/[^"\']+)["\'][^>]*>(.*?)</a>',)
    detail_title_pattern = r'<h1[^>]+class=["\'][^"\']*vacancy-title[^"\']*["\'][^>]*>(.*?)</h1>'
    detail_company_patterns = (r'class=["\'][^"\']*company-name[^"\']*["\'][^>]*>(.*?)</', r'class=["\'][^"\']*company[^"\']*["\'][^>]*>(.*?)</')
    detail_location_patterns = (r'class=["\'][^"\']*vacancy-location[^"\']*["\'][^>]*>(.*?)</',)
    detail_description_patterns = (r'class=["\'][^"\']*vacancy-description[^"\']*["\'][^>]*>(.*?)</div>',)
    detail_salary_patterns = (r'class=["\'][^"\']*vacancy-salary[^"\']*["\'][^>]*>(.*?)</',)
    detail_work_format_patterns = (r'class=["\'][^"\']*work-format[^"\']*["\'][^>]*>(.*?)</',)
    detail_employment_patterns = (r'class=["\'][^"\']*employment[^"\']*["\'][^>]*>(.*?)</',)
    detail_published_patterns = (r'<time[^>]+class=["\'][^"\']*published[^"\']*["\'][^>]+datetime=["\']([^"\']+)',)
    detail_requirements_patterns = (r'<b>\s*Requirements\s*</b>\s*<p[^>]*>(.*?)</p>',)
    detail_responsibilities_patterns = (r'<b>\s*Responsibilities\s*</b>\s*<p[^>]*>(.*?)</p>',)
    detail_conditions_patterns = (r'<b>\s*Conditions\s*</b>\s*<p[^>]*>(.*?)</p>',)
    detail_skills_patterns = (r'class=["\'][^"\']*skill-item[^"\']*["\'][^>]*>(.*?)</',)
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
