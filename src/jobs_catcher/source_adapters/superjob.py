from __future__ import annotations
from urllib.parse import urlencode
from .base import SourceAdapter

class SuperJobAdapter(SourceAdapter):
    source = "superjob"
    base_url = "https://www.superjob.ru"
    path = "/vacancy/search/"
    query_param = "keywords"
    search_link_patterns = (r'<a[^>]+href=["\']([^"\']*/vakansii/[^"\']+)["\'][^>]*>(.*?)</a>',)
    detail_title_pattern = r'<h1[^>]+class=["\'][^"\']*_title[^"\']*["\'][^>]*>(.*?)</h1>'
    detail_company_patterns = (r'class=["\'][^"\']*f-test-text-vacancy-item-company-name[^"\']*["\'][^>]*>(.*?)</', r'class=["\'][^"\']*company[^"\']*["\'][^>]*>(.*?)</')
    detail_location_patterns = (r'class=["\'][^"\']*address[^"\']*["\'][^>]*>(.*?)</',)
    detail_description_patterns = (r'class=["\'][^"\']*vacancy-text[^"\']*["\'][^>]*>(.*?)</div>',)
    detail_salary_patterns = (r'class=["\'][^"\']*payment[^"\']*["\'][^>]*>(.*?)</',)
    detail_work_format_patterns = (r'class=["\'][^"\']*place-of-work[^"\']*["\'][^>]*>(.*?)</',)
    detail_employment_patterns = (r'class=["\'][^"\']*employment[^"\']*["\'][^>]*>(.*?)</',)
    detail_published_patterns = (r'<time[^>]+class=["\'][^"\']*date-published[^"\']*["\'][^>]+datetime=["\']([^"\']+)',)
    detail_requirements_patterns = (r'<h3>\s*Requirements\s*</h3>\s*<p[^>]*>(.*?)</p>',)
    detail_responsibilities_patterns = (r'<h3>\s*Responsibilities\s*</h3>\s*<p[^>]*>(.*?)</p>',)
    detail_conditions_patterns = (r'<h3>\s*Conditions\s*</h3>\s*<p[^>]*>(.*?)</p>',)
    detail_skills_patterns = (r'class=["\'][^"\']*catalogues[^"\']*["\'][^>]*>(.*?)</',)
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
