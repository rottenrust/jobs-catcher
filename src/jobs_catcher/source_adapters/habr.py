from __future__ import annotations
from .base import SourceAdapter

class HabrAdapter(SourceAdapter):
    source = "habr"
    base_url = "https://career.habr.com"
    path = "/vacancies"
