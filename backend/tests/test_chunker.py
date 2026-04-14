from app.services.chunker import chunk_document
from app.services.pdf_parser import parse_pdf


def test_parse_pdf_pages(tiny_pdf_path):
    pages = parse_pdf(tiny_pdf_path)
    assert len(pages) >= 1
    assert pages[0]["page"] == 1
    assert "Model risk" in pages[0]["content"]


def test_chunk_document_overlap(tiny_pdf_path):
    pages = parse_pdf(tiny_pdf_path)
    chunks = chunk_document(pages, "doc-1")
    assert len(chunks) >= 1
    assert chunks[0]["doc_id"] == "doc-1"
    assert "chunk_id" in chunks[0]
    assert "[Page 1]" in chunks[0]["content"]
