from __future__ import annotations

import hashlib, re, zipfile
from dataclasses import dataclass
from html import unescape
from io import BytesIO
from pathlib import PurePath

@dataclass(frozen=True)
class UploadCheck:
    original_name: str
    safe_name: str
    sha256: str
    kind: str

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _safe_basename(name: str) -> str:
    if "\x00" in name or name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/"):
        raise ValueError("unsafe filename")
    base = PurePath(name.replace("\\", "/")).name
    if base != name.replace("\\", "/"):
        raise ValueError("unsafe filename")
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    if not safe:
        raise ValueError("empty filename")
    return safe


def validate_upload(name: str, content: bytes, mime: str, *, max_bytes: int = 10 * 1024 * 1024) -> UploadCheck:
    if len(content) > max_bytes:
        raise ValueError("file too large")
    safe = _safe_basename(name)
    lower = safe.lower()
    if lower.endswith(".pdf"):
        if mime != PDF_MIME or not content.startswith(b"%PDF-"):
            raise ValueError("invalid PDF")
        kind = "pdf"
    elif lower.endswith(".docx"):
        if mime != DOCX_MIME or not zipfile.is_zipfile(BytesIO(content)):
            raise ValueError("invalid DOCX")
        kind = "docx"
    else:
        raise ValueError("unsupported extension")
    return UploadCheck(name, safe, hashlib.sha256(content).hexdigest(), kind)


def extract_pdf_text(content: bytes) -> str:
    if not content.startswith(b"%PDF-"):
        raise ValueError("invalid PDF")
    if b"/Encrypt" in content:
        raise ValueError("encrypted PDF is not supported")
    decoded = content.decode("latin1", errors="ignore")
    if not re.search(rb"\([^()]{2,}\)", content):
        raise ValueError("PDF has no extractable text layer")
    strings = re.findall(r"\(([^()]{2,})\)", decoded)
    text = " ".join(strings) or " ".join(re.findall(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9 ,.;:+#/-]{4,}", decoded))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 5 or text in {"/Pages"}:
        raise ValueError("PDF has no extractable text layer")
    return text


def extract_docx_text(content: bytes, *, max_uncompressed: int = 20 * 1024 * 1024) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            total = sum(i.file_size for i in zf.infolist())
            if total > max_uncompressed:
                raise ValueError("DOCX uncompressed size too large")
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise ValueError("DOCX document body missing")
            xmls = [zf.read(n).decode("utf-8", errors="ignore") for n in names if n.startswith("word/") and n.endswith(".xml")]
    except zipfile.BadZipFile as exc:
        raise ValueError("corrupted DOCX") from exc
    text = " ".join(unescape(t) for xml in xmls for t in re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml))
    return re.sub(r"\s+", " ", text).strip()
