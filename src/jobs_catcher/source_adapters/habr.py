from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class HabrAdapter(SourceAdapter):
    source = "habr"
    base_url = "https://career.habr.com"
    path = "/vacancies"
    query_param = "q"
    search_link_patterns = (r'<a[^>]+class=["\'][^"\']*vacancy-card__title[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    detail_title_pattern = r'<h1[^>]+class=["\'][^"\']*page-title[^"\']*["\'][^>]*>(.*?)</h1>'
    detail_company_patterns = (r'class=["\'][^"\']*company_name[^"\']*["\'][^>]*>(.*?)</', r'class=["\'][^"\']*company[^"\']*["\'][^>]*>(.*?)</')
    detail_location_patterns = (r'class=["\'][^"\']*location[^"\']*["\'][^>]*>(.*?)</',)
    detail_description_patterns = (r'class=["\'][^"\']*vacancy-description[^"\']*["\'][^>]*>(.*?)</div>',)
    detail_salary_patterns = (r'class=["\'][^"\']*salary[^"\']*["\'][^>]*>(.*?)</',)
    detail_work_format_patterns = (r'class=["\'][^"\']*remote-work[^"\']*["\'][^>]*>(.*?)</',)
    detail_employment_patterns = (r'class=["\'][^"\']*employment-type[^"\']*["\'][^>]*>(.*?)</',)
    detail_published_patterns = (r'<time[^>]+class=["\'][^"\']*published_at[^"\']*["\'][^>]+datetime=["\']([^"\']+)',)
    detail_requirements_patterns = (r'class=["\'][^"\']*requirements[^"\']*["\'][^>]*>(.*?)</',)
    detail_responsibilities_patterns = (r'class=["\'][^"\']*responsibilities[^"\']*["\'][^>]*>(.*?)</',)
    detail_conditions_patterns = (r'class=["\'][^"\']*conditions[^"\']*["\'][^>]*>(.*?)</',)
    detail_skills_patterns = (r'class=["\'][^"\']*skill[^"\']*["\'][^>]*>(.*?)</',)
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
