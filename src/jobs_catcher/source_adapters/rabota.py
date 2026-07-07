from __future__ import annotations
from .base import SourceAdapter

class RabotaAdapter(SourceAdapter):
    source = "rabota"
    base_url = "https://www.rabota.ru"
    path = "/vacancy/"
