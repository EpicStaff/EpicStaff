"""Builds minimal, valid PDF files with real extractable text for tests.

pypdfium2 (this version) doesn't expose a convenient high-level API for
authoring text objects, so we hand-craft a tiny PDF instead of pulling in a
heavyweight PDF-writer dependency just for test fixtures.
"""


def build_minimal_pdf(page_texts: list[str]) -> bytes:
    """Build a minimal valid PDF with one page per entry in page_texts.

    Each page contains the given text drawn with the standard Helvetica font,
    extractable via pypdfium2's text page API.
    """
    n_pages = len(page_texts)
    page_obj_start = 4
    content_obj_start = page_obj_start + n_pages

    objects = []

    kids = " ".join(f"{page_obj_start + i} 0 R" for i in range(n_pages))

    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for i in range(n_pages):
        content_obj_num = content_obj_start + i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_num} 0 R >>"
        )

    for text in page_texts:
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 10 100 Td ({escaped}) Tj ET"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")

    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode()
        out += obj.encode("latin-1")
        out += b"\nendobj\n"

    xref_offset = len(out)
    total_objs = len(objects) + 1
    out += f"xref\n0 {total_objs}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()

    out += b"trailer\n"
    out += f"<< /Size {total_objs} /Root 1 0 R >>\n".encode()
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode()
    out += b"%%EOF"

    return bytes(out)
