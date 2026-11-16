"""剧本上传解析：PDF / DOCX / TXT / MD / Fountain → 纯文本。

前端只上传文件字节，解析在服务端完成（浏览器无需装 PDF 库）。
安全限制：单文件 ≤ 15 MB、解析后 ≤ 200,000 字符；不落盘、不记录内容。
"""
import io
import re

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api", tags=["script"])

MAX_BYTES = 15 * 1024 * 1024
MAX_CHARS = 200_000
ALLOWED = {".pdf", ".docx", ".txt", ".md", ".markdown", ".fountain"}


def _ext(name: str) -> str:
    idx = (name or "").rfind(".")
    return (name[idx:] if idx >= 0 else "").lower()


def _parse_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=501, detail="服务器未安装 pypdf，无法解析 PDF") from exc
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"PDF 解析失败：{exc}") from exc
    return "\n".join(pages)


def _parse_docx(raw: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=501, detail="服务器未安装 python-docx，无法解析 DOCX") from exc
    try:
        doc = Document(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"DOCX 解析失败：{exc}") from exc
    blocks = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return "\n".join(blocks)


def _parse_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@router.post("/script/parse")
async def parse_script(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件是空的")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 15 MB，请拆分或压缩后重试")

    ext = _ext(file.filename or "")
    if ext not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"不支持 {ext or '该'} 格式；请上传 PDF / DOCX / TXT / MD / Fountain")

    if ext == ".pdf":
        text = _parse_pdf(raw)
    elif ext == ".docx":
        text = _parse_docx(raw)
    else:
        text = _parse_text(raw)

    text = _normalize(text)
    if not text:
        raise HTTPException(status_code=422, detail="没有从文件里读到文字（可能是扫描版 PDF，需要先 OCR）")

    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS]

    return {
        "filename": file.filename,
        "ext": ext,
        "chars": len(text),
        "truncated": truncated,
        "text": text,
    }


# --------------------------------------------------------------------------
# 剧本导出 PDF：前端把剧本全文 POST 过来，服务端生成 PDF（中文用 CID 字体）
# --------------------------------------------------------------------------
@router.post("/script/pdf")
async def script_pdf(payload: dict = Body(...)):
    text = str(payload.get("text") or "").strip()
    title = str(payload.get("title") or "剧本").strip() or "剧本"
    if not text:
        raise HTTPException(status_code=400, detail="剧本内容是空的")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError:
        raise HTTPException(status_code=503, detail="服务端缺少 reportlab，无法导出 PDF")
    from urllib.parse import quote

    buf = io.BytesIO()
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font = "STSong-Light"
    except Exception:  # noqa: BLE001
        font = "Helvetica"
    page_w, page_h = A4
    left, top, line_h, max_chars = 52, page_h - 56, 18, 44
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setFont(font, 14)
    pdf.drawString(left, top, title[:40])
    pdf.setFont(font, 10.5)
    y = top - 30
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            y -= line_h
            if y < 60:
                pdf.showPage()
                pdf.setFont(font, 10.5)
                y = top
            continue
        while line:
            chunk, line = line[:max_chars], line[max_chars:]
            if y < 60:
                pdf.showPage()
                pdf.setFont(font, 10.5)
                y = top
            pdf.drawString(left, y, chunk)
            y -= line_h
    pdf.save()
    buf.seek(0)
    filename = quote((title if title.endswith(".pdf") else title + ".pdf"))
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

