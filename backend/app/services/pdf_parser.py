from typing import Any

import fitz


def parse_pdf(file_path: str) -> list[dict[str, Any]]:
    """Extract text from PDF with page numbers."""
    doc = fitz.open(file_path)
    pages: list[dict[str, Any]] = []
    try:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            pages.append({"page": page_num, "content": text})
    finally:
        doc.close()
    return pages
