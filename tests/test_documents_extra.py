from __future__ import annotations
import io, zipfile, pytest
from jobs_catcher import documents, sources

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def docx_with(entries):
    bio=io.BytesIO()
    with zipfile.ZipFile(bio,"w") as z:
        for name,data in entries.items(): z.writestr(name,data)
    return bio.getvalue()

@pytest.mark.parametrize("name,content,mime", [
    ("..\\cv.pdf", b"%PDF-1.7 (x)", "application/pdf"),
    ("/tmp/cv.pdf", b"%PDF-1.7 (x)", "application/pdf"),
    ("cv.pdf\x00.docx", b"%PDF-1.7 (x)", "application/pdf"),
    ("cv.pdf", b"%PDF-1.7 (x)", DOCX_MIME),
    ("cv.docx", b"%PDF-1.7 (x)", "application/pdf"),
    ("cv.exe", b"MZ", "application/octet-stream"),
])
def test_upload_rejects_unsafe_names_and_mismatches(name, content, mime):
    with pytest.raises(ValueError): documents.validate_upload(name, content, mime)

def test_upload_rejects_oversize_and_docx_zip_bomb_missing_body():
    with pytest.raises(ValueError): documents.validate_upload("cv.pdf", b"%PDF-" + b"x"*20, "application/pdf", max_bytes=10)
    bomb=docx_with({"word/document.xml":"<w:t>x</w:t>", "word/big.xml":"x"*100})
    with pytest.raises(ValueError): documents.extract_docx_text(bomb, max_uncompressed=50)
    missing=docx_with({"word/styles.xml":"<w:t>x</w:t>"})
    with pytest.raises(ValueError): documents.extract_docx_text(missing)

@pytest.mark.parametrize("source", sources.SOURCES)
def test_source_specific_fixture_markers(source):
    search=f'<div data-provider="{source}"><a data-source="{source}" href="https://jobs.example/{source}/42?utm_campaign=x">{source} AI Analyst</a></div>'
    rows=sources.parse_search(source, search)
    assert rows == [{"source":source,"external_id":"42","title":f"{source} AI Analyst","url":f"https://jobs.example/{source}/42"}]
    detail=f'<main class="{source}-detail"><h1>{source} AI Analyst</h1><span class="company">ACME {source}</span><p>No salary. No date. LLM API work.</p></main>'
    parsed=sources.parse_detail(source, detail)
    assert parsed["title"] == f"{source} AI Analyst" and parsed["company"] == f"ACME {source}"
