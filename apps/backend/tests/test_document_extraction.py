"""确定性文档抽取器契约测试。"""

from __future__ import annotations

from io import BytesIO

import pytest

from app.services.document_extraction import (
    DocumentExtractionError,
    chunk_text,
    extract_document,
)


def _pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode())
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(body)


def test_extract_text_pdf_and_docx_preserve_source_order():
    pdf = extract_document(_pdf_with_text("pdf-nonce"), content_type="application/pdf", filename="a.pdf")
    assert pdf.kind == "pdf" and "pdf-nonce" in pdf.text and pdf.warning is None

    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("paragraph-before")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "table-left"
    table.cell(0, 1).text = "table-right"
    document.add_paragraph("paragraph-after")
    stream = BytesIO()
    document.save(stream)
    result = extract_document(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="a.docx",
    )
    assert result.kind == "docx"
    assert (
        result.text.index("paragraph-before")
        < result.text.index("table-left")
        < result.text.index("paragraph-after")
    )


def test_extract_text_is_bounded_and_scanned_pdf_warns():
    result = extract_document(b"x" * 50_010, content_type="text/plain", filename="large.txt")
    assert len(result.text) == 50_000 and result.truncated is True
    pypdf = pytest.importorskip("pypdf")
    from io import BytesIO

    blank_stream = BytesIO()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(blank_stream)
    blank = extract_document(blank_stream.getvalue(), content_type="application/pdf", filename="scan.pdf")
    assert blank.text == "" and "扫描件" in (blank.warning or "")


def test_doc_legacy_and_binary_are_controlled_errors():
    with pytest.raises(DocumentExtractionError):
        extract_document(b"legacy", content_type="application/msword", filename="old.doc")
    with pytest.raises(DocumentExtractionError):
        extract_document(b"\x00\x01binary", content_type="application/octet-stream", filename="data.bin")


def test_chunk_text_uses_fixed_overlap_and_is_deterministic():
    text = "a" * 2_500
    chunks = chunk_text(text)
    assert len(chunks[0]) == 1_200
    assert chunks[0][-120:] == chunks[1][:120]
    assert len(chunks[-1]) == 340
    assert chunk_text("") == ()
    assert chunk_text("x" * 1_200) == ("x" * 1_200,)
    assert chunk_text(text) == chunks
