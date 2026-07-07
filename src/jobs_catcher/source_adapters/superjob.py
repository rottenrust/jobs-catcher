from __future__ import annotations
from .base import SourceAdapter

class SuperJobAdapter(SourceAdapter):
    source = "superjob"
    base_url = "https://www.superjob.ru"
    path = "/vacancy/search/"
