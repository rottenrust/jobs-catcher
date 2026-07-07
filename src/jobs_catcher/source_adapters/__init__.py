from .base import AdapterError, BlockedSourceError, SourceAdapter, VacancyResult
from .hh import HHAdapter
from .habr import HabrAdapter
from .superjob import SuperJobAdapter
from .rabota import RabotaAdapter
from .geekjob import GeekJobAdapter
from .getmatch import GetMatchAdapter

__all__ = [
    "ADAPTERS",
    "AdapterError",
    "BlockedSourceError",
    "SourceAdapter",
    "VacancyResult",
    "HHAdapter",
    "HabrAdapter",
    "SuperJobAdapter",
    "RabotaAdapter",
    "GeekJobAdapter",
    "GetMatchAdapter",
]

ADAPTERS = {
    "hh": HHAdapter,
    "habr": HabrAdapter,
    "superjob": SuperJobAdapter,
    "rabota": RabotaAdapter,
    "geekjob": GeekJobAdapter,
    "getmatch": GetMatchAdapter,
}
