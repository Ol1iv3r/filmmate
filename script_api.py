"""剧本上传解析：PDF / DOCX / TXT / MD / Fountain → 纯文本。

前端只上传文件字节，解析在服务端完成（浏览器无需装 PDF 库）。
安全限制：单文件 ≤ 15 MB、解析后 ≤ 200,000 字符；不落盘、不记录内容。
"""
import io
import re

from fastapi import APIRouter, File, HTTPException, UploadFile

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
