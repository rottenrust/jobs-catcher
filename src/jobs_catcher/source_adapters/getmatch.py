from __future__ import annotations
from .base import SourceAdapter

class GetMatchAdapter(SourceAdapter):
    source = "getmatch"
    base_url = "https://getmatch.ru"
    path = "/vacancies"
