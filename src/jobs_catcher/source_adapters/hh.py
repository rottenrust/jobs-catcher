from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class HHAdapter(SourceAdapter):
    source = "hh"
    base_url = "https://hh.ru"
    path = "/search/vacancy"
    query_param = "text"
    search_link_patterns = (r'<a[^>]+data-qa=["\']serp-item__title["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',)
    detail_title_pattern = r'<h1[^>]+data-qa=["\']vacancy-title["\'][^>]*>(.*?)</h1>'
    detail_company_patterns = (r'data-qa=["\']vacancy-company-name["\'][^>]*>(.*?)<', r'class=["\'][^"\']*company[^"\']*["\'][^>]*>(.*?)<')
    detail_location_patterns = (r'data-qa=["\']vacancy-view-raw-address["\'][^>]*>(.*?)</',)
    detail_description_patterns = (r'data-qa=["\']vacancy-description["\'][^>]*>(.*?)</div>',)
    detail_salary_patterns = (r'data-qa=["\']vacancy-salary["\'][^>]*>(.*?)</',)
    detail_work_format_patterns = (r'data-qa=["\']vacancy-view-work-schedule["\'][^>]*>(.*?)</',)
    detail_employment_patterns = (r'data-qa=["\']vacancy-view-employment-mode["\'][^>]*>(.*?)</',)
    detail_published_patterns = (r'<time[^>]+data-qa=["\']vacancy-date["\'][^>]+datetime=["\']([^"\']+)',)
    detail_requirements_patterns = (r'<strong>\s*Requirements\s*</strong>\s*<p[^>]*>(.*?)</p>',)
    detail_responsibilities_patterns = (r'<strong>\s*Responsibilities\s*</strong>\s*<p[^>]*>(.*?)</p>',)
    detail_conditions_patterns = (r'<strong>\s*Conditions\s*</strong>\s*<p[^>]*>(.*?)</p>',)
    detail_skills_patterns = (r'data-qa=["\']skills-element["\'][^>]*>(.*?)</',)
    def build_search_url(self, query, preferences, page=0):
        params = {"text": query, "page": page}
        if preferences.get("locations") and not preferences.get("all_russia"):
            params["area"] = ",".join(preferences["locations"])
        if preferences.get("remote") or "remote" in preferences.get("work_formats", []):
            params["schedule"] = "remote"
        if preferences.get("employment_types"):
            params["employment"] = ",".join(preferences["employment_types"])
        salary = preferences.get("salary") or {}
        if salary.get("minimum"):
            params["salary"] = str(salary["minimum"])
        if salary.get("currency"):
            params["currency_code"] = salary["currency"]
        if salary.get("gross") is not None:
            params["only_with_salary"] = "true"
        return f"{self.base_url}{self.path}?{urlencode(params)}"
