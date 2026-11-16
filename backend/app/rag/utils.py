"""Safe text extraction utilities for PDF, Word and plain-text files."""

from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile


MAX_ARCHIVE_UNCOMPRESSED = 200 * 1024 * 1024
MAX_PDF_PAGES = 300
_OCR_ENGINE = None
_OCR_LOCK = threading.Lock()


def _decode_text(data: bytes) -> str:
    """Decode common Chinese text encodings without silently returning garbage."""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("TXT 文档编码无法识别，请保存为 UTF-8 或 GB18030")


def _extract_docx(data: bytes) -> str:
    # Limit decompressed size to reduce ZIP-bomb risk before python-docx opens it.
    with zipfile.ZipFile(BytesIO(data)) as archive:
        total = sum(item.file_size for item in archive.infolist())
        if total > MAX_ARCHIVE_UNCOMPRESSED:
            raise ValueError("Word 文档解压后过大，无法安全处理")
        if "word/document.xml" not in archive.namelist():
            raise ValueError("Word 文件结构不完整")
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = DocxDocument(BytesIO(data))

    def paragraph_markdown(paragraph: Paragraph) -> str:
        style_name = str(getattr(paragraph.style, "name", "") or "")
        style_id = str(getattr(paragraph.style, "style_id", "") or "")
        formatted_runs: list[str] = []
        for run in paragraph.runs:
            value = run.text.replace("\r", "").replace("\n", "  \n")
            if not value:
                continue
            if run.bold and value.strip():
                value = f"**{value}**"
            if run.italic and value.strip():
                value = f"*{value}*"
            formatted_runs.append(value)
        text = "".join(formatted_runs).strip()
        # Hyperlink text is not exposed as a normal run by older python-docx.
        if paragraph.text.strip() and not text:
            text = paragraph.text.strip()
        if not text:
            return ""

        heading = re.search(r"(?:Heading|标题)\s*([1-6])", f"{style_name} {style_id}", re.I)
        if heading:
            return f"{'#' * int(heading.group(1))} {paragraph.text.strip()}"
        if style_name.lower() in {"title", "标题"}:
            return f"# {paragraph.text.strip()}"

        has_numbering = bool(
            paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None
        )
        style_lower = f"{style_name} {style_id}".lower()
        if has_numbering or "list" in style_lower or "列表" in style_name:
            marker = "1." if "number" in style_lower or "编号" in style_name else "-"
            return f"{marker} {text}"
        if "quote" in style_lower or "引用" in style_name:
            return f"> {text}"
        return text

    def table_markdown(table: Table) -> str:
        rows = [
            [
                re.sub(r"\s*\n\s*", "<br>", cell.text.strip()).replace("|", r"\|")
                for cell in row.cells
            ]
            for row in table.rows
        ]
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        header = rows[0]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines)

    parts: list[str] = []
    # Iterate the OOXML body so paragraphs and tables keep their source order.
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            value = paragraph_markdown(Paragraph(child, document))
        elif child.tag.endswith("}tbl"):
            value = table_markdown(Table(child, document))
        else:
            continue
        if value:
            parts.append(value)
    return "\n\n".join(parts)


def _extract_legacy_doc(data: bytes) -> str:
    """Read RTF or binary .doc through an installed, sandboxed converter."""
    if data.lstrip().startswith(b"{\\rtf"):
        raw = data.decode("latin-1", errors="ignore")
        raw = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), raw)
        raw = re.sub(r"\\'[0-9a-fA-F]{2}", "", raw)
        raw = re.sub(r"\\[a-zA-Z]+-?\d* ?|[{}]", "", raw)
        return re.sub(r"\n{3,}", "\n\n", raw)

    antiword = shutil.which("antiword")
    if antiword:
        with tempfile.NamedTemporaryFile(suffix=".doc") as source:
            source.write(data)
            source.flush()
            result = subprocess.run(
                [antiword, source.name], capture_output=True, timeout=60, check=True
            )
        return _decode_text(result.stdout)

    raise ValueError("当前环境缺少旧版 DOC 转换器，请将文件另存为 DOCX 后上传")


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _ocr_pdf_pages(data: bytes, page_indexes: list[int]) -> dict[int, str]:
    """Render and OCR only PDF pages that have no usable text layer."""
    import cv2
    import fitz
    import numpy as np

    results: dict[int, str] = {}
    document = fitz.open(stream=data, filetype="pdf")
    try:
        with _OCR_LOCK:
            engine = _get_ocr_engine()
            for page_index in page_indexes:
                page = document.load_page(page_index)
                # 144 DPI is accurate enough for Chinese text without excessive RAM.
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                if pixmap.width * pixmap.height > 20_000_000:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                if pixmap.n == 3:
                    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                ocr_result, _ = engine(image)
                lines = [str(item[1]).strip() for item in (ocr_result or []) if str(item[1]).strip()]
                results[page_index] = "\n".join(lines)
    finally:
        document.close()
    return results


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"PDF 页数不能超过 {MAX_PDF_PAGES} 页")

    page_texts: list[str] = []
    ocr_indexes: list[int] = []
    for index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").replace("\x00", "").strip()
        page_texts.append(text)
        if len(re.sub(r"\s+", "", text)) < 6:
            ocr_indexes.append(index)

    if ocr_indexes:
        try:
            ocr_texts = _ocr_pdf_pages(data, ocr_indexes)
        except Exception as exc:
            if len(ocr_indexes) == len(page_texts):
                raise ValueError(f"扫描版 PDF OCR 失败：{exc}") from exc
            ocr_texts = {}
        for index, text in ocr_texts.items():
            if text.strip():
                page_texts[index] = text.strip()

    usable_pages = [text for text in page_texts if len(re.sub(r"\s+", "", text)) >= 2]
    if not usable_pages:
        raise ValueError("PDF 未识别到文字，请确认扫描图像清晰且方向正确")
    return "\n\n".join(
        f"## 第 {index} 页\n\n{text}"
        for index, text in enumerate(page_texts, 1)
        if text.strip()
    )


def extract_text(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        text = _decode_text(data)
    if suffix == ".pdf":
        text = _extract_pdf(data)
    if suffix == ".docx":
        text = _extract_docx(data)
    if suffix == ".doc":
        # Some files are OOXML documents saved with the wrong extension.
        text = _extract_docx(data) if data.startswith(b"PK") else _extract_legacy_doc(data)
    if suffix not in {".txt", ".md", ".pdf", ".doc", ".docx"}:
        raise ValueError(f"不支持的文件类型：{suffix or '无扩展名'}")
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("文档未提取到有效文本；扫描版 PDF 请先进行 OCR")
    return text
