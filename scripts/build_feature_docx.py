"""Build the Filmmate feature report DOCX from the Markdown source.

The Markdown file is the editable source; this script renders it with a
consistent report layout (A4, amber/ink palette, shaded tables, callouts).
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "FEATURES_AND_IMPLEMENTATION.md"
OUTPUT = ROOT / "docs" / "Filmmate_Feature_Description_and_Implementation.docx"

INK = RGBColor(0x17, 0x19, 0x1C)
MUTED = RGBColor(0x60, 0x64, 0x6E)
AMBER = RGBColor(0xB0, 0x7A, 0x2A)
AMBER_DARK = RGBColor(0x8A, 0x5A, 0x1E)
PAPER = RGBColor(0xFB, 0xF7, 0xF0)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

HEX_INK = "17191C"
HEX_MUTED = "60646E"
HEX_AMBER = "B07A2A"
HEX_AMBER_DARK = "8A5A1E"
HEX_PAPER = "FBF7F0"
HEX_TABLE_ALT = "F7F2E8"
HEX_LINE = "D9CFC0"
HEX_CODE_BG = "F4EBDD"

BODY_FONT = "Calibri"
MONO_FONT = "Consolas"
DISPLAY_FONT = "Georgia"

USABLE_WIDTH_CM = 16.6


# --------------------------------------------------------------------------- xml helpers
def shade(element, fill: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    element.append(shd)


def para_shading(paragraph, fill: str) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    shade(pPr, fill)


def para_border(paragraph, edge: str = "bottom", color: str = HEX_LINE, size: int = 6) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.append(pBdr)
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size))
    el.set(qn("w:space"), "4")
    el.set(qn("w:color"), color)
    pBdr.append(el)


def run_shading(run, fill: str) -> None:
    rPr = run._element.get_or_add_rPr()
    shade(rPr, fill)


def set_run_font(run, name: str = BODY_FONT, size: float | None = None, bold=None, italic=None,
                 color: RGBColor | None = None) -> None:
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), name)
    rFonts.set(qn("w:hAnsi"), name)
    rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def set_character_spacing(run, twentieths: int) -> None:
    rPr = run._element.get_or_add_rPr()
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:val"), str(twentieths))
    rPr.append(spacing)


def set_cell_margins(table, top=60, bottom=60, left=90, right=90) -> None:
    tblPr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for edge, width in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:w"), str(width))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblPr.append(mar)


def set_table_borders(table, color: str = HEX_LINE, size: int = 4) -> None:
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblPr.append(borders)


def set_table_width(table, width_cm: float = USABLE_WIDTH_CM) -> None:
    tblPr = table._tbl.tblPr
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), str(int(round(width_cm / USABLE_WIDTH_CM * 5000))))
    tblW.set(qn("w:type"), "pct")
    tblPr.append(tblW)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)


def repeat_header(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def cant_split(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def add_page_field(paragraph, instruction: str, placeholder: str = "1") -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(sep)
    run._r.append(text)
    run._r.append(end)
    set_run_font(run, BODY_FONT, 8, color=MUTED)


# --------------------------------------------------------------------------- inline text
TOKEN_RE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)")


def add_inline(paragraph, text: str, size: float = 10.5, color: RGBColor = INK,
               bold: bool = False, italic: bool = False) -> None:
    for token in TOKEN_RE.split(text):
        if not token:
            continue
        if token.startswith("`") and token.endswith("`") and len(token) > 2:
            run = paragraph.add_run(token[1:-1])
            set_run_font(run, MONO_FONT, size - 1.1, bold=False, italic=False, color=AMBER_DARK)
            run_shading(run, HEX_CODE_BG)
        elif token.startswith("**") and token.endswith("**") and len(token) > 4:
            run = paragraph.add_run(token[2:-2])
            set_run_font(run, BODY_FONT, size, bold=True, italic=italic, color=color)
        elif token.startswith("*") and token.endswith("*") and len(token) > 2:
            run = paragraph.add_run(token[1:-1])
            set_run_font(run, BODY_FONT, size, bold=bold, italic=True, color=color)
        else:
            run = paragraph.add_run(token)
            set_run_font(run, BODY_FONT, size, bold=bold, italic=italic, color=color)


# --------------------------------------------------------------------------- styles
def configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    rPr = normal.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), BODY_FONT)
    rFonts.set(qn("w:hAnsi"), BODY_FONT)
    rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    pf = normal.paragraph_format
    pf.space_after = Pt(6)
    pf.line_spacing = 1.16
    pf.widow_control = True

    h1 = doc.styles["Heading 1"]
    h1.font.name = BODY_FONT
    h1.font.size = Pt(19)
    h1.font.bold = True
    h1.font.color.rgb = INK
    h1.paragraph_format.space_before = Pt(4)
    h1.paragraph_format.space_after = Pt(10)
    h1.paragraph_format.keep_with_next = True

    h2 = doc.styles["Heading 2"]
    h2.font.name = BODY_FONT
    h2.font.size = Pt(13)
    h2.font.bold = True
    h2.font.color.rgb = AMBER_DARK
    h2.paragraph_format.space_before = Pt(15)
    h2.paragraph_format.space_after = Pt(5)
    h2.paragraph_format.keep_with_next = True


def configure_page(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.9)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)
    section.header_distance = Cm(0.9)
    section.footer_distance = Cm(0.9)
    section.different_first_page_header_footer = True

    # Header
    header = section.header
    header.is_linked_to_previous = False
    p = header.paragraphs[0]
    p.style = doc.styles["Normal"]
    p.paragraph_format.tab_stops.clear_all()
    p.paragraph_format.tab_stops.add_tab_stop(Cm(USABLE_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT)
    p.paragraph_format.space_after = Pt(2)
    left = p.add_run("FILMMATE")
    set_run_font(left, BODY_FONT, 8, bold=True, color=AMBER)
    set_character_spacing(left, 40)
    p.add_run("\t")
    right = p.add_run("FEATURE DESCRIPTION  ·  IMPLEMENTATION NOTES")
    set_run_font(right, BODY_FONT, 7.5, color=MUTED)
    set_character_spacing(right, 30)
    para_border(p, "bottom", HEX_LINE, 4)

    # Footer
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.style = doc.styles["Normal"]
    p.paragraph_format.tab_stops.clear_all()
    p.paragraph_format.tab_stops.add_tab_stop(Cm(USABLE_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT)
    p.paragraph_format.space_before = Pt(2)
    para_border(p, "top", HEX_LINE, 4)
    left = p.add_run("COMP4431  ·  Group 20  ·  17 November 2026")
    set_run_font(left, BODY_FONT, 7.5, color=MUTED)
    p.add_run("\t")
    r = p.add_run("Page ")
    set_run_font(r, BODY_FONT, 8, color=MUTED)
    add_page_field(p, " PAGE ")
    r = p.add_run(" of ")
    set_run_font(r, BODY_FONT, 8, color=MUTED)
    add_page_field(p, " NUMPAGES ", "1")

    # Ensure fields update when the document is opened.
    settings = doc.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)


# --------------------------------------------------------------------------- cover
def build_cover(doc: Document) -> None:
    for _ in range(3):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run("COMP4431  ·  ARTIFICIAL INTELLIGENCE  ·  GROUP 20")
    set_run_font(r, BODY_FONT, 8.5, bold=True, color=AMBER)
    set_character_spacing(r, 50)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("Filmmate")
    set_run_font(r, DISPLAY_FONT, 54, bold=True, color=INK)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run("A domain-specific AI assistant for film and video creators.")
    set_run_font(r, DISPLAY_FONT, 13, italic=True, color=MUTED)

    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(8)
    rule.paragraph_format.space_after = Pt(18)
    para_border(rule, "bottom", HEX_AMBER, 18)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("Feature Description and\nImplementation Notes")
    set_run_font(r, BODY_FONT, 25, bold=True, color=INK)
    p.paragraph_format.line_spacing = 1.05

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(26)
    r = p.add_run(
        "A feature-by-feature account of what the chatbot does, how each capability is wired into "
        "the same request pipeline, and where the online and offline paths meet."
    )
    set_run_font(r, BODY_FONT, 11, color=MUTED)
    p.paragraph_format.line_spacing = 1.3

    # Two-column info strip
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.columns[0].width = Cm(8.3)
    table.columns[1].width = Cm(8.3)
    set_table_borders(table, HEX_LINE, 4)
    set_cell_margins(table, 120, 120, 140, 140)
    cells = table.rows[0].cells
    for idx, (label, value) in enumerate(
        (("PREPARED", "17 November 2026"), ("STACK", "FastAPI · React 19 · DeepSeek"))
    ):
        cell = cells[idx]
        cell.width = Cm(8.3)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(label)
        set_run_font(r, BODY_FONT, 7.5, bold=True, color=AMBER)
        set_character_spacing(r, 40)
        p2 = cell.add_paragraph()
        p2.paragraph_format.space_after = Pt(0)
        r = p2.add_run(value)
        set_run_font(r, BODY_FONT, 9.5, color=INK)

    for _ in range(2):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("“Filmmate does not create in place of the filmmaker. It helps the filmmaker make better decisions.”")
    set_run_font(r, DISPLAY_FONT, 10.5, italic=True, color=AMBER_DARK)
    para_border(p, "left", HEX_AMBER, 18)
    p.paragraph_format.left_indent = Cm(0.35)
    p.paragraph_format.space_before = Pt(4)

    doc.add_page_break()


# --------------------------------------------------------------------------- kpi strip
def build_kpi_strip(doc: Document) -> None:
    items = [
        ("198", "KNOWLEDGE ENTRIES"),
        ("16", "SCRIPT + FILM PAIRS"),
        ("260", "CATALOG TITLES"),
        ("6", "RETRIEVAL TOOLS"),
    ]
    table = doc.add_table(rows=2, cols=4)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table, "FFFFFF", 0)
    set_cell_margins(table, 80, 80, 60, 60)
    for i, (number, label) in enumerate(items):
        table.columns[i].width = Cm(USABLE_WIDTH_CM / 4)
        top = table.rows[0].cells[i]
        bottom = table.rows[1].cells[i]
        for cell in (top, bottom):
            cell.width = Cm(USABLE_WIDTH_CM / 4)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = top.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(number)
        set_run_font(r, DISPLAY_FONT, 22, bold=True, color=AMBER)
        p = bottom.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(label)
        set_run_font(r, BODY_FONT, 7.2, bold=True, color=MUTED)
        set_character_spacing(r, 20)

    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(2)
    rule.paragraph_format.space_after = Pt(8)
    para_border(rule, "bottom", HEX_LINE, 4)


# --------------------------------------------------------------------------- body blocks
def add_heading1(doc: Document, text: str, page_break: bool = False) -> None:
    p = doc.add_paragraph(style="Heading 1")
    p.paragraph_format.page_break_before = page_break
    add_inline(p, text, size=19, color=INK, bold=True)
    para_border(p, "bottom", HEX_AMBER, 10)


def add_heading2(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="Heading 2")
    add_inline(p, text, size=13, color=AMBER_DARK, bold=True)


def add_body(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    add_inline(p, text, size=10.5, color=INK)


def add_numbered(doc: Document, number: str, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.75)
    p.paragraph_format.first_line_indent = Cm(-0.75)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.tab_stops.add_tab_stop(Cm(0.75), WD_TAB_ALIGNMENT.LEFT)
    r = p.add_run(number + ".")
    set_run_font(r, BODY_FONT, 10.2, bold=True, color=AMBER)
    r = p.add_run("\t")
    set_run_font(r, BODY_FONT, 10.2)
    add_inline(p, text, size=10.2, color=INK)


def add_bullet(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.65)
    p.paragraph_format.first_line_indent = Cm(-0.45)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("•  ")
    set_run_font(r, BODY_FONT, 10.2, bold=True, color=AMBER)
    add_inline(p, text, size=10.2, color=INK)


def add_key_modules(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.55)
    p.paragraph_format.first_line_indent = Cm(-0.55)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run("│  ")
    set_run_font(r, BODY_FONT, 9, bold=True, color=AMBER)
    label = p.add_run("KEY MODULES   ")
    set_run_font(label, BODY_FONT, 7, bold=True, color=AMBER)
    set_character_spacing(label, 25)
    body = text.strip()
    if body.startswith("*") and body.endswith("*"):
        body = body[1:-1]
    if body.lower().startswith("key modules:"):
        body = body[len("key modules:"):].strip()
    add_inline(p, body, size=9, color=MUTED, italic=True)


def add_seam(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.right_indent = Cm(0.2)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(10)
    para_shading(p, HEX_PAPER)
    para_border(p, "left", HEX_AMBER, 18)
    r = p.add_run("INTEGRATION SEAM   ")
    set_run_font(r, BODY_FONT, 7, bold=True, color=AMBER)
    set_character_spacing(r, 30)
    body = text
    if body.lower().startswith("integration seam:"):
        body = body[len("integration seam:"):].strip()
    add_inline(p, body, size=9.3, color=INK, italic=True)


def add_quote(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.55)
    p.paragraph_format.right_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(12)
    para_shading(p, HEX_PAPER)
    para_border(p, "left", HEX_AMBER, 24)
    add_inline(p, text, size=11, color=AMBER_DARK, italic=True)


def add_separator(doc: Document) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    para_border(p, "bottom", HEX_LINE, 4)


def column_widths(n: int, header: str) -> list[float]:
    header_lower = header.lower()
    if n == 2:
        return [4.9, 11.7]
    if n == 4:
        return [0.9, 4.3, 2.3, 9.1]
    if n == 3:
        if "method" in header_lower:
            return [1.7, 6.1, 8.8]
        if "layer" in header_lower:
            return [3.0, 7.7, 5.9]
        if "asset" in header_lower:
            return [4.5, 2.2, 9.9]
        if "feature" in header_lower:
            return [0.9, 4.3, 2.3, 9.1]
        return [4.6, 5.4, 6.6]
    return [USABLE_WIDTH_CM / n] * n


def add_table(doc: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    header = rows[0]
    body = rows[1:]
    table = doc.add_table(rows=1 + len(body), cols=len(header))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_width(table)
    set_table_borders(table)
    set_cell_margins(table)
    widths = column_widths(len(header), " | ".join(header))

    for j, width in enumerate(widths):
        table.columns[j].width = Cm(width)

    # Header row
    header_row = table.rows[0]
    repeat_header(header_row)
    cant_split(header_row)
    for j, text in enumerate(header):
        cell = header_row.cells[j]
        cell.width = Cm(widths[j])
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        tcPr = cell._tc.get_or_add_tcPr()
        shade(tcPr, HEX_INK)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        if j == 0 and len(header) > 2:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_inline(p, text, size=8.4, color=WHITE, bold=True)

    # Body rows
    for i, row_data in enumerate(body):
        row = table.rows[i + 1]
        cant_split(row)
        for j, text in enumerate(row_data):
            if j >= len(widths):
                break
            cell = row.cells[j]
            cell.width = Cm(widths[j])
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            tcPr = cell._tc.get_or_add_tcPr()
            if i % 2 == 1:
                shade(tcPr, HEX_TABLE_ALT)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.05
            if j == 0 and len(header) > 2:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_inline(p, text, size=8.5, color=INK)

    # Give a little breathing room after the table.
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 0.6


# --------------------------------------------------------------------------- markdown parser
def parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        cells = [cell.strip() for cell in raw.strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells):
            rows.append(cells)
        i += 1
    return rows, i


def build_body(doc: Document, markdown: str) -> None:
    lines = markdown.splitlines()
    # Skip the Markdown title block; the cover carries it.
    try:
        start = next(idx for idx, line in enumerate(lines) if line.strip() == "## Executive summary")
    except StopIteration:
        start = 0

    i = start
    page_break_sections = set()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("|"):
            rows, i = parse_table(lines, i)
            add_table(doc, rows)
            continue

        if stripped.startswith("## "):
            text = stripped[3:].strip()
            add_heading1(doc, text, page_break=text.startswith(tuple(page_break_sections)))
            i += 1
            continue

        if stripped.startswith("### "):
            add_heading2(doc, stripped[4:].strip())
            i += 1
            continue

        if stripped == "---":
            add_separator(doc)
            i += 1
            continue

        if stripped.startswith("> "):
            add_quote(doc, stripped[2:].strip())
            i += 1
            continue

        if stripped.startswith("*Key modules:"):
            add_key_modules(doc, stripped)
            i += 1
            continue

        if stripped.startswith("*Integration seam:"):
            add_seam(doc, stripped.strip("*"))
            i += 1
            continue

        m = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if m:
            add_numbered(doc, m.group(1), m.group(2))
            i += 1
            continue

        if stripped.startswith("- "):
            add_bullet(doc, stripped[2:].strip())
            i += 1
            continue

        # Accumulate a normal paragraph until a blank line or a block marker.
        buf = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", "|", "> ", "---", "*Key modules:", "*Integration seam:"))
                    or re.match(r"^\d+\.\s+", nxt) or nxt.startswith("- ")):
                break
            buf.append(nxt)
            i += 1
        add_body(doc, " ".join(buf))


# --------------------------------------------------------------------------- main
def main() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    doc = Document()
    configure_styles(doc)
    configure_page(doc)
    build_cover(doc)
    build_kpi_strip(doc)
    build_body(doc, markdown)

    # Keep an integration-seam callout with the paragraph it summarises.
    for index, paragraph in enumerate(doc.paragraphs):
        if paragraph.text.startswith("INTEGRATION SEAM") and index > 0:
            doc.paragraphs[index - 1].paragraph_format.keep_with_next = True

    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
