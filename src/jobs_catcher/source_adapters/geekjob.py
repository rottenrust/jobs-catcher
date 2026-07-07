from __future__ import annotations
from .base import SourceAdapter

class GeekJobAdapter(SourceAdapter):
    source = "geekjob"
    base_url = "https://geekjob.ru"
    path = "/vacancies"
