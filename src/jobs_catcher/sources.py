from __future__ import annotations
import html, re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
SOURCES = ["hh", "habr", "superjob", "rabota", "geekjob", "getmatch"]
class BlockedSourceError(RuntimeError): pass

def normalize_url(url: str) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")]
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), urlencode(q), ""))

def _blocked(html_text):
    low = html_text.lower()
    return any(x in low for x in ["captcha", "429", "forbidden", "access denied"])

def parse_search(source: str, html_text: str) -> list[dict]:
    if source not in SOURCES: raise ValueError("unknown source")
    if _blocked(html_text): raise BlockedSourceError(source)
    out=[]
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text, re.I|re.S):
        href, raw_title = m.group(1), m.group(2)
        if source not in href and source not in html_text[:200].lower():
            continue
        title = re.sub("<.*?>", "", raw_title).strip()
        if not title:
            continue
        clean = normalize_url(href)
        vid = urlsplit(clean).path.rstrip("/").rsplit("/",1)[-1]
        out.append({"source": source, "external_id": vid, "title": html.unescape(title), "url": clean})
    return out

def parse_detail(source: str, html_text: str) -> dict:
    if source not in SOURCES: raise ValueError("unknown source")
    if _blocked(html_text): raise BlockedSourceError(source)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.I|re.S)
    company = re.search(r"data-company=[\"']([^\"']+)[\"']", html_text) or re.search(r"data-qa=[\"']vacancy-company-name[\"'][^>]*>(.*?)<", html_text, re.I|re.S) or re.search(r"class=[\"'][^\"']*company[^\"']*[\"'][^>]*>(.*?)<", html_text, re.I|re.S)
    text = re.sub(r"<[^>]+>", " ", html_text)
    return {"source": source, "title": html.unescape(re.sub("<.*?>", "", h1.group(1)).strip()) if h1 else "", "company": html.unescape(company.group(1).strip()) if company else "", "description": re.sub(r"\s+", " ", html.unescape(text)).strip()}
