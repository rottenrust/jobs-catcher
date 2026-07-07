from __future__ import annotations
from .base import SourceAdapter

class HHAdapter(SourceAdapter):
    source = "hh"
    base_url = "https://hh.ru"
    path = "/search/vacancy"
