from __future__ import annotations

import io
import zipfile

import pytest

from jobs_catcher import documents, sources


def test_upload_validation_rejects_path_traversal_mismatch_and_accepts_pdf():
    with pytest.raises(ValueError):
        documents.validate_upload("../cv.pdf", b"%PDF-1.7 text", "application/pdf")
    with pytest.raises(ValueError):
        documents.validate_upload("cv.pdf", b"not pdf", "application/pdf")
    check = documents.validate_upload("CV Final.pdf", b"%PDF-1.7\nHello", "application/pdf")
    assert check.kind == "pdf"
    assert "/" not in check.safe_name


def test_docx_validation_rejects_corruption_and_zip_expansion_limit():
    with pytest.raises(ValueError):
        documents.extract_docx_text(b"bad zip")
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w") as zf:
        zf.writestr("word/document.xml", "<w:t>Hello</w:t>")
    assert "Hello" in documents.extract_docx_text(mem.getvalue())


def test_pdf_without_text_layer_has_clear_error():
    with pytest.raises(ValueError, match="text layer"):
        documents.extract_pdf_text(b"%PDF-1.7\n/Pages")


@pytest.mark.parametrize("source", sources.SOURCES)
def test_source_search_detail_fixtures(source):
    html = f'<html><body><a class="vacancy" href="https://example.com/{source}/1" data-id="1">AI Analyst</a></body></html>'
    results = sources.parse_search(source, html)
    assert results[0]["source"] == source
    detail = sources.parse_detail(source, '<main><h1>AI Analyst</h1><section data-company="ACME"></section><p>LLM integrations</p></main>')
    assert detail["title"] == "AI Analyst"
    assert detail["company"] == "ACME"


@pytest.mark.parametrize("source", sources.SOURCES)
def test_source_block_pages_and_changed_html(source):
    with pytest.raises(sources.BlockedSourceError):
        sources.parse_search(source, "captcha 429 forbidden")
    assert sources.parse_search(source, "<html></html>") == []


def test_url_normalization_drops_tracking():
    assert sources.normalize_url("https://example.com/a?utm_source=x&id=1#top") == "https://example.com/a?id=1"

