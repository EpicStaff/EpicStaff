from pathlib import Path
from typing import Tuple
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from pypdf._page import ContentStream
from pypdf.generic import NameObject, TextStringObject


class PDFTextWritingToolSchema(BaseModel):
    pdf_path: str
    text: str
    position: Tuple[float, float]
    font_size: int = 12
    font_color: Tuple[float, float, float] = (0, 0, 0)
    font_name: str = "F1"
    page_number: int = 0
    output_pdf_path: str = "modified_output.pdf"


def main(
    pdf_path: str,
    text: str,
    position: Tuple[float, float],
    font_size: int = 12,
    font_color: Tuple[float, float, float] = (0, 0, 0),
    font_name: str = "F1",
    page_number: int = 0,
    output_pdf_path: str = "modified_output.pdf",
) -> str:
    if not Path(pdf_path).exists():
        return "PDF file does not exist."

    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    if page_number >= len(reader.pages):
        return "Page number out of range."

    # Process target page
    page = reader.pages[page_number]
    content = ContentStream(page["/Contents"].get_object(), reader)

    x, y = position
    r, g, b = font_color

    # Begin text
    content.operations.append([NameObject("BT")])
    # Set font
    content.operations.append(
        [NameObject(f"/{font_name}"), font_size, NameObject("Tf")]
    )
    # Set color
    content.operations.append([(r, g, b), NameObject("rg")])
    # Move to position
    content.operations.append([x, y, NameObject("Td")])
    # Add text
    content.operations.append([TextStringObject(text), NameObject("Tj")])
    # End text
    content.operations.append([NameObject("ET")])

    # Replace content stream
    page[NameObject("/Contents")] = content.flate_encode()
    writer.add_page(page)

    # Add remaining pages
    for i, p in enumerate(reader.pages):
        if i != page_number:
            writer.add_page(p)

    with open(output_pdf_path, "wb") as out_file:
        writer.write(out_file)

    return f"Text added to {output_pdf_path} successfully."
