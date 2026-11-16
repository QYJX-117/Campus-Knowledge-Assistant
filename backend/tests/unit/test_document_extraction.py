from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.rag import utils


def _blank_pdf() -> bytes:
    target = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(target)
    return target.getvalue()


def test_scanned_pdf_uses_ocr(monkeypatch):
    monkeypatch.setattr(utils, "_ocr_pdf_pages", lambda data, pages: {0: "OCR 识别出的校园通知"})
    text = utils.extract_text(_blank_pdf(), "scan.pdf")
    assert "## 第 1 页" in text
    assert "OCR 识别出的校园通知" in text


def test_unreadable_scanned_pdf_does_not_return_page_marker(monkeypatch):
    monkeypatch.setattr(utils, "_ocr_pdf_pages", lambda data, pages: {0: ""})
    with pytest.raises(ValueError, match="未识别到文字"):
        utils.extract_text(_blank_pdf(), "scan.pdf")


def test_docx_preserves_headings_lists_emphasis_and_tables():
    from docx import Document

    document = Document()
    document.add_heading("校园服务指南", level=1)
    paragraph = document.add_paragraph()
    paragraph.add_run("重要说明").bold = True
    document.add_paragraph("携带学生证", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "事项"
    table.cell(0, 1).text = "地点"
    table.cell(1, 0).text = "校园卡补办"
    table.cell(1, 1).text = "服务大厅"
    target = BytesIO()
    document.save(target)

    text = utils.extract_text(target.getvalue(), "guide.docx")

    assert "# 校园服务指南" in text
    assert "**重要说明**" in text
    assert "- 携带学生证" in text
    assert "| 事项 | 地点 |" in text
    assert "| 校园卡补办 | 服务大厅 |" in text
