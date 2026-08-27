"""Text extraction is bounded in input size and page count.

The extractor runs on the knowledge worker's ThreadPoolExecutor behind
`indexing_semaphore = 3` (main.py), so three files that never finish extracting
stall ingestion for every tenant. A PDF can declare thousands of pages, and
pdfplumber walks all of them synchronously with no way to interrupt.

Each cap is asserted through the public extract_* entry points rather than
against ExtractionBudget alone -- a budget nothing consults would satisfy a
unit test of the budget itself while leaving the worker just as pinnable.
"""

from io import BytesIO

import pytest
from docx import Document

from utils.extraction_limits import (
    ExtractionBudget,
    ExtractionLimitExceeded,
    default_budget,
)
from utils.file_text_extractor import (
    extract_text_from_binary,
    extract_text_from_csv,
    extract_text_from_docx,
    extract_text_from_pdf,
)


def build_pdf(page_texts: list[str]) -> bytes:
    """Build a minimal single-font PDF carrying one text line per entry."""
    objects: dict[int, bytes] = {}
    n_pages = len(page_texts)
    page_ids = [3 + 2 * i for i in range(n_pages)]
    content_ids = [4 + 2 * i for i in range(n_pages)]
    font_id = 3 + 2 * n_pages

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
    objects[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n_pages)

    for index, text in enumerate(page_texts):
        objects[page_ids[index]] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
            b"/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>"
            % (content_ids[index], font_id)
        )
        stream = b"BT /F1 12 Tf 20 200 Td (%s) Tj ET" % text.encode("ascii")
        objects[content_ids[index]] = b"<< /Length %d >>\nstream\n%s\nendstream" % (
            len(stream),
            stream,
        )

    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    body = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(body)
        body += b"%d 0 obj\n%s\nendobj\n" % (number, objects[number])

    xref_offset = len(body)
    last = max(objects)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (last + 1)
    for number in range(1, last + 1):
        body += b"%010d 00000 n \n" % offsets.get(number, 0)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        last + 1,
        xref_offset,
    )
    return bytes(body)


def build_docx(paragraphs: list[str]) -> bytes:
    """Build an in-memory DOCX carrying one paragraph per entry."""
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def permissive_budget(**overrides) -> ExtractionBudget:
    """Build a budget whose caps are all effectively unlimited unless overridden."""
    limits = {
        "max_input_bytes": 10_000_000,
        "max_pages": 10_000,
    }
    limits.update(overrides)
    return ExtractionBudget(**limits)


# --- page cap ---


def test_pdf_extraction_rejects_more_pages_than_cap():
    pdf_bytes = build_pdf([f"Page number {i}" for i in range(5)])

    with pytest.raises(ExtractionLimitExceeded, match="page"):
        extract_text_from_pdf(pdf_bytes, budget=permissive_budget(max_pages=2))


def test_pdf_extraction_accepts_page_count_at_the_cap():
    pdf_bytes = build_pdf([f"Page number {i}" for i in range(5)])

    text = extract_text_from_pdf(pdf_bytes, budget=permissive_budget(max_pages=5))

    assert "Page number 0" in text
    assert "Page number 4" in text


def test_pdf_page_cap_trips_before_every_page_is_parsed():
    """The cap must bound work done, not just reject after walking the whole file."""
    pdf_bytes = build_pdf([f"Page number {i}" for i in range(200)])
    budget = permissive_budget(max_pages=3)

    with pytest.raises(ExtractionLimitExceeded):
        extract_text_from_pdf(pdf_bytes, budget=budget)

    assert budget.pages_seen == 4


# --- extraction still works ---


def test_docx_extraction_returns_every_paragraph():
    """The DOCX loop was rewritten when the char cap went; it still reads all text."""
    docx_bytes = build_docx(["first paragraph", "second paragraph"])

    assert extract_text_from_docx(docx_bytes) == "first paragraph\nsecond paragraph"


def test_csv_extraction_returns_every_row():
    csv_bytes = b"a,b,c\nd,e,f"

    assert extract_text_from_csv(csv_bytes) == "a,b,c\nd,e,f"


# --- input byte cap ---


def test_extraction_rejects_input_over_byte_cap_before_parsing():
    html_bytes = b"<html><body>" + b"x" * 5000 + b"</body></html>"

    with pytest.raises(ExtractionLimitExceeded, match="bytes"):
        extract_text_from_binary(
            html_bytes, "html", budget=permissive_budget(max_input_bytes=1000)
        )


def test_input_byte_cap_applies_to_every_file_type():
    payload = b"z" * 5000

    with pytest.raises(ExtractionLimitExceeded, match="bytes"):
        extract_text_from_binary(
            payload, "txt", budget=permissive_budget(max_input_bytes=1000)
        )


# --- integration with the dispatcher and defaults ---


def test_dispatcher_threads_budget_through_to_pdf_extraction():
    pdf_bytes = build_pdf([f"Page number {i}" for i in range(5)])

    with pytest.raises(ExtractionLimitExceeded, match="page"):
        extract_text_from_binary(
            pdf_bytes, "pdf", budget=permissive_budget(max_pages=2)
        )


def test_default_budget_extracts_an_ordinary_document_unchanged():
    pdf_bytes = build_pdf(["Ordinary content", "Second page"])

    text = extract_text_from_binary(pdf_bytes, "pdf")

    assert "Ordinary content" in text
    assert "Second page" in text


def test_default_budget_caps_are_finite():
    budget = default_budget()

    assert 0 < budget.max_pages < 1_000_000
    assert 0 < budget.max_input_bytes < 1_000_000_000


def test_limit_error_is_a_value_error_so_existing_handlers_still_catch_it():
    """execute_preview_chunking reports ValueError as a `failed` job, not a crash."""
    assert issubclass(ExtractionLimitExceeded, ValueError)
