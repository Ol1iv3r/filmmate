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
# Screenplay PDF export
# --------------------------------------------------------------------------
_SCENE_RE = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(?:INT\.?|EXT\.?|INT\.?/EXT\.?|I/E\.?|内景|外景|内外景)(?:\s|$)", re.I
)
_INLINE_CUE_RE = re.compile(r"^([A-Z][A-Z0-9 .'’()/\\-]{0,31}):\s*(.+)$")
_TRANSITION_RE = re.compile(
    r"^(?:CUT TO:|FADE (?:IN|OUT)\.?:?|DISSOLVE TO:|SMASH CUT TO:|MATCH CUT TO:|"
    r"WIPE TO:|IRIS (?:IN|OUT)\.?|TO BLACK\.?)$",
    re.I,
)
_CHARACTER_RE = re.compile(r"^[A-Z][A-Z0-9 .'’()/\\-]{1,32}$")


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _wrap_text(text: str, font: str, size: float, width: float) -> list[str]:
    """Wrap on word boundaries, with a character fallback for CJK/long tokens."""
    from reportlab.pdfbase import pdfmetrics
    text = " ".join(text.split())
    if not text:
        return [""]
    words = text.split(" ") if " " in text else list(text)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if pdfmetrics.stringWidth(word, font, size) <= width:
            current = word
            continue
        # Break a long token (or a Chinese run) character by character.
        for ch in word:
            candidate = ch if not current else current + ch
            if pdfmetrics.stringWidth(candidate, font, size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = ch
    if current:
        lines.append(current)
    return lines or [""]


def _is_character_cue(line: str, previous_blank: bool, next_line: str) -> bool:
    if not previous_blank or not line or len(line) > 32:
        return False
    if not line.isupper() or _SCENE_RE.match(line) or _TRANSITION_RE.match(line):
        return False
    if any(word in line for word in ("INT.", "EXT.", "CUT TO:", "FADE ")):
        return False
    return bool(next_line.strip())


@router.post("/script/pdf")
async def script_pdf(payload: dict = Body(...)):
    """Render a screenplay with standard US screenplay layout.

    - Letter page, 1.5" left / 1" right / 1" top / 1" bottom margins
    - 12 pt Courier, word-wrapped action, indented dialogue and character cues
    - scene headings in caps, transitions right-aligned, page numbers from page 2
    - CJK fallback: STSong-Light when the script contains Chinese
    """
    text = str(payload.get("text") or "").strip()
    title = str(payload.get("title") or "Screenplay").strip() or "Screenplay"
    if not text:
        raise HTTPException(status_code=400, detail="剧本内容是空的")
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError:
        raise HTTPException(status_code=503, detail="服务端缺少 reportlab，无法导出 PDF")
    from urllib.parse import quote

    # Light cleanup: screenplay text may arrive with markdown emphasis.
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().casefold() == title.casefold():
        lines.pop(0)

    buf = io.BytesIO()
    use_cjk = _has_cjk(text)
    if use_cjk:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            body_font = "STSong-Light"
        except Exception:  # noqa: BLE001
            body_font = "Helvetica"
        title_font = body_font
    else:
        body_font = "Courier"
        title_font = "Courier-Bold"

    page_w, page_h = letter
    left = 1.5 * 72
    right = 1.0 * 72
    top = 1.0 * 72
    bottom = 1.0 * 72
    content_w = page_w - left - right
    dialogue_x = left + 1.0 * 72
    dialogue_w = 3.5 * 72
    character_x = left + 2.2 * 72
    parenthetical_x = left + 1.6 * 72
    parenthetical_w = 2.6 * 72
    size = 12.0
    leading = 13.2

    pdf = canvas.Canvas(buf, pagesize=letter)
    pdf.setTitle(title)
    pdf.setAuthor("Filmmate")
    pdf.setSubject("Screenplay")

    # Title page.
    pdf.setFont(title_font, 18)
    pdf.drawCentredString(page_w / 2, page_h * 0.62, title[:80])
    pdf.setFont(body_font, 12)
    pdf.drawCentredString(page_w / 2, page_h * 0.62 - 28, "Screenplay")
    pdf.showPage()

    page_no = 1
    y = page_h - top

    def new_page() -> None:
        nonlocal y, page_no
        pdf.showPage()
        page_no += 1
        pdf.setFont(body_font, size)
        y = page_h - top
        if page_no > 1:
            pdf.setFont(body_font, 9)
            pdf.drawRightString(page_w - right, page_h - 36, f"{page_no}.")
            pdf.setFont(body_font, size)

    def ensure(height: float) -> None:
        nonlocal y
        if y - height < bottom:
            new_page()

    def draw_line(value: str, x: float, font: str = body_font, size_: float = size) -> None:
        nonlocal y
        ensure(leading)
        pdf.setFont(font, size_)
        pdf.drawString(x, y, value)
        y -= leading

    def draw_block(value: str, x: float, width: float, font: str = body_font, size_: float = size) -> None:
        nonlocal y
        wrapped = _wrap_text(value, font, size_, width)
        ensure(leading * len(wrapped))
        pdf.setFont(font, size_)
        for line in wrapped:
            pdf.drawString(x, y, line)
            y -= leading

    pdf.setFont(body_font, size)
    previous_blank = True
    character_names: set[str] = set()
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        line = raw.strip()
        if not line:
            if not previous_blank:
                y -= leading * 0.55
            previous_blank = True
            i += 1
            continue

        next_nonblank = ""
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines):
            next_nonblank = lines[j].strip()

        if _SCENE_RE.match(line):
            if not previous_blank:
                y -= leading * 0.55
            ensure(leading * 2)
            y -= leading * 0.35
            draw_line(line.upper(), left)
            previous_blank = False
            i += 1
            continue

        if _TRANSITION_RE.match(line):
            ensure(leading * 2)
            y -= leading * 0.5
            pdf.setFont(body_font, size)
            pdf.drawRightString(page_w - right, y, line.upper())
            y -= leading
            previous_blank = False
            i += 1
            continue

        inline = _INLINE_CUE_RE.match(line)
        if inline or _is_character_cue(line, previous_blank, next_nonblank):
            ensure(leading * 2)
            y -= leading * 0.4
            if inline:
                cue = inline.group(1).upper()
                character_names.add(re.sub(r"\s*\(.*?\)\s*$", "", cue).strip())
                draw_line(cue, character_x)
                draw_block(inline.group(2), dialogue_x, dialogue_w)
            else:
                cue = line.upper()
                character_names.add(re.sub(r"\s*\(.*?\)\s*$", "", cue).strip())
                draw_line(cue, character_x)
            i += 1
            # Dialogue / parentheticals until a blank, scene or transition.
            while i < len(lines):
                sub = lines[i].strip()
                if not sub:
                    break
                if _SCENE_RE.match(sub) or _TRANSITION_RE.match(sub):
                    break
                if _INLINE_CUE_RE.match(sub) or _is_character_cue(sub, True, lines[i + 1].strip() if i + 1 < len(lines) else ""):
                    break
                first_word = re.split(r"\s+", sub, maxsplit=1)[0].strip(".,:;!?()").upper()
                if first_word in character_names and not sub.isupper():
                    # An action line beginning with a character name, not dialogue.
                    break
                if sub.startswith("(") and sub.endswith(")"):
                    draw_block(sub, parenthetical_x, parenthetical_w)
                else:
                    draw_block(sub, dialogue_x, dialogue_w)
                i += 1
            previous_blank = False
            continue

        # Action paragraph: collect until blank / scene / transition.
        block = [line]
        i += 1
        while i < len(lines):
            sub = lines[i].strip()
            if not sub or _SCENE_RE.match(sub) or _TRANSITION_RE.match(sub) or _INLINE_CUE_RE.match(sub):
                break
            block.append(sub)
            i += 1
        draw_block(" ".join(block), left, content_w)
        previous_blank = False

    pdf.save()
    buf.seek(0)
    filename = quote((title if title.endswith(".pdf") else title + ".pdf"))
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})
