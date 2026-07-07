from __future__ import annotations
import re
from urllib.parse import urlsplit, urlunsplit

def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wА-Яа-я ]+", " ", value.lower())).strip()

def _key(v):
    url = v.get("canonical_url") or v.get("url") or ""
    if url: return ("url", urlunsplit(urlsplit(url)._replace(query="", fragment="")))
    if v.get("content_hash"): return ("hash", v["content_hash"])
    return ("compound", normalize_title(v.get("title", "")), (v.get("company") or "").lower(), (v.get("location") or "").lower())

def deduplicate(vacancies: list[dict]) -> list[dict]:
    merged = {}
    for v in vacancies:
        k = _key(v)
        if k not in merged:
            item = dict(v); item["source_links"] = list(v.get("source_links") or [v.get("url") or v.get("canonical_url")])
            merged[k] = item
        else:
            links = merged[k].setdefault("source_links", [])
            for link in v.get("source_links") or [v.get("url") or v.get("canonical_url")]:
                if link and link not in links: links.append(link)
    return list(merged.values())
