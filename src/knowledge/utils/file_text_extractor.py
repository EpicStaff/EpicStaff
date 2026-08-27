import csv
import pdfplumber
from docx import Document
from io import BytesIO, StringIO
from bs4 import BeautifulSoup
from loguru import logger

from utils.extraction_limits import ExtractionBudget, default_budget


def extract_text_from_binary(
    binary_content: bytes, file_type: str, budget: ExtractionBudget | None = None
) -> str:
    """Universal dispatcher to extract text from binary content based on file type."""

    file_type = file_type.lower().lstrip(".")
    budget = budget or default_budget()
    budget.check_input_size(binary_content)

    try:
        if file_type in ("txt", "md", "json"):
            return extract_text(binary_content)

        elif file_type == "pdf":
            return extract_text_from_pdf(binary_content, budget=budget)

        elif file_type == "csv":
            return extract_text_from_csv(binary_content)

        elif file_type == "docx":
            return extract_text_from_docx(binary_content)

        elif file_type == "html":
            return extract_text_from_html(binary_content)

        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    except Exception as e:
        logger.error("Failed to extract text from {} file: {}", file_type, e)
        raise


def extract_text(binary_content: bytes) -> str:
    """Extract text from plain text files."""

    try:
        return binary_content.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("UTF-8 decode failed, trying latin-1")
        return binary_content.decode("latin-1")


def _is_valid_pdf(binary_content: bytes) -> bool:
    """
    Check if binary content is a valid PDF by looking for the PDF magic bytes.
    PDF files should start with '%PDF-' (possibly with leading whitespace).
    """
    # Strip leading whitespace and check for PDF signature
    content = binary_content.lstrip()
    return content.startswith(b"%PDF-")


def _extract_page_text(page) -> str:
    """
    Make pdfplumber extraction output similar to PyMuPDF output.
    """
    lines = page.extract_text_lines(
        strip=True,
        return_chars=False,
        x_tolerance=3,
        y_tolerance=3,
    )
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]["text"]

    spacings = [
        lines[i]["top"] - lines[i - 1]["top"]
        for i in range(1, len(lines))
        if lines[i]["top"] > lines[i - 1]["top"]
    ]
    if not spacings:
        return "\n".join(line["text"] + " " for line in lines).rstrip(" ")

    median_spacing = sorted(spacings)[len(spacings) // 2]
    paragraph_threshold = median_spacing * 1.5

    parts = [lines[0]["text"] + " "]
    for i in range(1, len(lines)):
        spacing = lines[i]["top"] - lines[i - 1]["top"]
        if spacing > paragraph_threshold:
            parts.append(" ")
        parts.append(lines[i]["text"] + " ")

    return "\n".join(parts).rstrip(" ")


def extract_text_from_pdf(
    binary_content: bytes, budget: ExtractionBudget | None = None
) -> str:
    """Extract text from PDF files, falling back to plain text for invalid PDFs."""

    budget = budget or default_budget()

    if not _is_valid_pdf(binary_content):
        logger.warning(
            "Content has .pdf extension but is not a valid PDF file. "
            "Attempting plain text extraction."
        )
        return extract_text(binary_content)

    text_parts = []
    try:
        with pdfplumber.open(BytesIO(binary_content)) as pdf_document:
            for page in pdf_document.pages:
                budget.count_page()
                page_text = _extract_page_text(page)
                if page_text:
                    text_parts.append(page_text)

        if not text_parts:
            logger.warning("No text extracted from PDF")
            return ""

        return "\n\n".join(text_parts)

    except Exception as e:
        logger.error("PDF text extraction failed: {}", e)
        raise


def extract_text_from_csv(binary_content: bytes) -> str:
    """Extract text from CSV files."""

    try:
        text_content = binary_content.decode("utf-8")
        csv_file = StringIO(text_content)

        delimiter = ","
        reader = csv.reader(csv_file, delimiter=delimiter)

        extracted_rows = []
        for row in reader:
            if row and len(row[0].replace(delimiter, "")) != 0:
                extracted_rows.append(",".join(row))

        return "\n".join(extracted_rows)

    except Exception as e:
        logger.error("CSV text extraction failed: {}", e)
        raise


def extract_text_from_docx(binary_content: bytes) -> str:
    """Extract text from DOCX files using python-docx."""

    try:
        docx_file = BytesIO(binary_content)
        document = Document(docx_file)

        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]

        if not paragraphs:
            logger.warning("No text extracted from DOCX")
            return ""

        return "\n".join(paragraphs)

    except Exception as e:
        logger.error("DOCX text extraction failed: {}", e)
        raise


def extract_text_from_html(binary_content: bytes) -> str:
    """Extract text from HTML files using BeautifulSoup, dropping scripts, styles and images."""

    try:
        html_content = binary_content.decode("utf-8")
        soup = BeautifulSoup(html_content, "html.parser")

        # Remove unwanted tags
        for tag in soup(["script", "style", "img"]):
            tag.decompose()

        # Return cleaned HTML
        return str(soup)

    except Exception as e:
        logger.error("HTML text extraction failed: {}", e)
        raise
