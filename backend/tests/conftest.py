import fitz
import pytest


@pytest.fixture
def tiny_pdf_path(tmp_path):
    p = tmp_path / "one.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "Model risk management is important for banks.")
        doc.save(str(p))
    finally:
        doc.close()
    return str(p)
