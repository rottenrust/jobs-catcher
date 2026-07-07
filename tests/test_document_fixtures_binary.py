from pathlib import Path
import pytest
from jobs_catcher import documents, audit
FIX=Path(__file__).parent/'fixtures'/'documents'
DOCX_MIME='application/vnd.openxmlformats-officedocument.wordprocessingml.document'

def test_minimal_binary_pdf_and_docx_fixtures_extract_text():
    assert 'Resume AI' in documents.extract_pdf_text((FIX/'minimal-text.pdf').read_bytes())
    assert 'Resume AI' in documents.extract_docx_text((FIX/'minimal.docx').read_bytes())
    check=documents.validate_upload('CV Final 2026.docx', (FIX/'minimal.docx').read_bytes(), DOCX_MIME)
    assert check.safe_name == 'CV Final 2026.docx'

def test_pdf_encrypted_no_text_and_docx_relationship_are_safe():
    with pytest.raises(ValueError, match='encrypted'):
        documents.extract_pdf_text((FIX/'encrypted.pdf').read_bytes())
    with pytest.raises(ValueError, match='text layer'):
        documents.extract_pdf_text((FIX/'no-text.pdf').read_bytes())
    text=documents.extract_docx_text((FIX/'relationships.docx').read_bytes())
    assert 'Safe text only' in text and 'passwd' not in text
    redacted=audit.redact_event({'action':'resume_uploaded','resume_text':'Resume AI integrations'})
    assert redacted['resume_text']=='[REDACTED]'
