#!/usr/bin/env python3
"""把 data/library/catalog.json 导出为：CSV / Markdown / Excel / HTML 画廊。"""
import csv
import json
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CATALOG = ROOT / "data" / "library" / "catalog.json"
CSV_OUT = DOCS / "film_catalog.csv"
MD_OUT = DOCS / "FILM_CATALOG.md"
XLSX_OUT = DOCS / "film_catalog.xlsx"
HTML_OUT = DOCS / "catalog.html"

BASE_COLUMNS = ["编号", "种类", "中文名", "英文名", "年份", "时长",
                "情绪", "内容梗概", "Tag", "原片链接"]
EXTRA_COLUMNS = ["静帧数", "静帧质量", "链接可信度", "静帧目录", "BV号", "匹配视频", "UP主",
                 "播放量(万)", "匹配分", "链接核验时间", "静帧时间码", "平台"]
KIND_ORDER = ["电影", "电视剧", "长片", "短片", "竖屏短剧",
              "广告/TVC", "教程/产品演示", "Vlog/美食", "动画"]
KIND_EN = {"电影": "Feature Film", "电视剧": "TV Series", "长片": "Long-form / Docs",
           "短片": "Short Film", "竖屏短剧": "Vertical Micro-drama",
           "广告/TVC": "Commercial / TVC", "教程/产品演示": "Tutorial / Product Demo",
           "Vlog/美食": "Vlog / Food", "动画": "Animation"}


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def md_escape(text):
    return str(text or "").replace("|", chr(92) + "|").replace(chr(10), " ")


def frame_rel(path):
    if not path:
        return ""
    return "../" + path.lstrip("/")


def write_csv(catalog):
    rows = catalog["titles"]
    fields = BASE_COLUMNS + EXTRA_COLUMNS
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(fields)
        for r in rows:
            writer.writerow([
                r["id"], r["kind"], r["title_zh"], r["title_en"], r["year"],
                r["duration"], " / ".join(r["moods"]), r["synopsis"],
                "、".join(r["tags"]), r["url"],
                len(r["frames"]), r.get("frame_quality", "高"), r.get("link_confidence", ""),
                r["frame_dir"], r["bvid"], r["video_title"], r["owner"],
                round(r.get("play", 0) / 10000, 1), r.get("match_score", ""), r["verified_at"],
                " · ".join(f["timecode"] for f in r.get("frame_meta", [])), r.get("platform", ""),
            ])
    return CSV_OUT


def write_markdown(catalog):
    rows = catalog["titles"]
    lines = [
        "# Filmmate 影视灵感目录（B 站原片 + 每部 10 张代表性静帧）",
        "",
        "> 生成时间：" + catalog["generated_at"] + "　｜　共 **" + str(catalog["count"]) + " 部**："
        + "、".join(k + " " + str(v) for k, v in catalog["by_kind"].items()),
        "> 全部原片链接在生成时实测可播放（B 站 view 接口 + 官方 storyboard 抽帧双校验）；"
        "静帧取自官方播放器预览帧（每部 10 张，均匀分布在 8%–94% 时间轴，自动避开片头字幕卡/片尾字幕并裁掉黑边）。",
        "> 可视化浏览（含 10 帧图墙）：[catalog.html](catalog.html)",
        "",
        "## 字段说明",
        "",
        "| 字段 | 含义 |",
        "|---|---|",
        "| 编号 | 类别字母 + 序号（D=电影 / T=电视剧 / F=长片 / S=短片 / V=竖屏短剧） |",
        "| 情绪 | 受控情绪词（2–4 个），用于「用户灵感 → 同情绪影片」检索 |",
        "| 内容梗概 | 主角 + 处境 + 核心冲突 + 钩子（60–110 字，不剧透结局） |",
        "| Tag | 题材/主题/结构/视觉/受众等检索标签（4–8 个） |",
        "| 原片链接 | B 站可播放原片（单集/整剧/合集，多 P 已定位到具体 P），生成时核验 |",
        "| 静帧 | 每部 10 张，见 static/frames/catalog/<BV号>/01–10.jpg |",
        "",
    ]
    for kind in KIND_ORDER:
        items = [r for r in rows if r["kind"] == kind]
        if not items:
            continue
        lines += [
            "## " + kind + "（" + str(len(items)) + " 部 / " + KIND_EN[kind] + "）",
            "",
            "| # | 中文名 / 英文名 | 年份 | 时长 | 情绪 | 内容梗概 | Tag | 原片链接 | 静帧 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in items:
            first = frame_rel(r["frames"][0]) if r["frames"] else ""
            frame_cell = ("![" + r["title_zh"] + " 静帧](" + first + ")<br>[10 张](catalog.html#" + r["id"] + ")") if first else "—"
            lines.append(
                "| " + r["id"] + " | **" + md_escape(r["title_zh"]) + "**<br>" + md_escape(r["title_en"]) + " | "
                + str(r["year"]) + " | " + md_escape(r["duration"]) + " | " + " / ".join(r["moods"]) + " | "
                + md_escape(r["synopsis"]) + " | " + "、".join(r["tags"]) + " | "
                + "[▶ B 站观看](" + r["url"] + ") | " + frame_cell + " |")
        lines.append("")
    lines += [
        "## 版权与使用说明",
        "",
        "- 原片链接全部指向哔哩哔哩上公开可播放的页面，版权归原权利人与上传者所有；本目录仅用于创作学习与灵感检索，不做二次分发。",
        "- 静帧是播放器 storyboard 预览图（480×270 级别，窄画幅/竖屏已裁边并 2x 放大），用于情绪板与构图参考；需要高清静帧时，按静帧时间码在原片中定位后重新截取。",
        "- 链接会随时间失效（下架/换源）；链接核验时间是生成时的核验时间，后续可用 scripts/build_catalog.py resolve --force 重跑。",
        "",
    ]
    MD_OUT.write_text(chr(10).join(lines), encoding="utf-8")
    return MD_OUT


HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
THIN = Side(style="thin", color="D1D5DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
KIND_FILL = {
    "电影": PatternFill("solid", fgColor="E0F2FE"),
    "电视剧": PatternFill("solid", fgColor="FEF3C7"),
    "长片": PatternFill("solid", fgColor="EDE9FE"),
    "短片": PatternFill("solid", fgColor="DCFCE7"),
    "竖屏短剧": PatternFill("solid", fgColor="FFE4E6"),
    "广告/TVC": PatternFill("solid", fgColor="FDE68A"),
    "教程/产品演示": PatternFill("solid", fgColor="DBEAFE"),
    "Vlog/美食": PatternFill("solid", fgColor="FCE7F3"),
    "动画": PatternFill("solid", fgColor="E9D5FF"),
}


def write_xlsx(catalog):
    rows = catalog["titles"]
    wb = Workbook()
    ws = wb.active
    ws.title = "总表"
    headers = BASE_COLUMNS + EXTRA_COLUMNS
    widths = [9, 11, 18, 26, 7, 16, 20, 52, 30, 20, 7, 18, 12, 34, 14, 34, 14, 10, 8, 20, 34, 10]
    ws.append(headers)
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[1].height = 30
    for idx, r in enumerate(rows, 2):
        values = [
            r["id"], r["kind"], r["title_zh"], r["title_en"], r["year"], r["duration"],
            " / ".join(r["moods"]), r["synopsis"], "、".join(r["tags"]), r["url"],
            len(r["frames"]), r.get("frame_quality", "高"), r.get("link_confidence", ""),
            r["frame_dir"], r["bvid"], r["video_title"], r["owner"],
            round(r.get("play", 0) / 10000, 1), r.get("match_score", ""), r["verified_at"],
            " · ".join(f["timecode"] for f in r.get("frame_meta", [])), r.get("platform", ""),
        ]
        ws.append(values)
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=idx, column=col)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=col in (3, 4, 7, 8, 9, 12, 14, 18))
            if col == 2:
                cell.fill = KIND_FILL.get(r["kind"], PatternFill())
        link_cell = ws.cell(row=idx, column=10)
        link_cell.hyperlink = r["url"]
        link_cell.font = Font(color="2563EB", underline="single")
        ws.row_dimensions[idx].height = 34
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = "A1:" + get_column_letter(len(headers)) + str(len(rows) + 1)

    stat = wb.create_sheet("统计")
    stat.column_dimensions["A"].width = 18
    stat.column_dimensions["B"].width = 10
    stat.append(["种类", "数量"])
    for kind in KIND_ORDER:
        stat.append([kind, catalog["by_kind"].get(kind, 0)])
    stat.append(["合计", catalog["count"]])
    stat.append([])
    stat.append(["情绪", "影片数"])
    for mood, num in Counter(m for r in rows for m in r["moods"]).most_common(30):
        stat.append([mood, num])
    stat.append([])
    stat.append(["题材/类型", "影片数"])
    for genre, num in Counter(g for r in rows for g in r["genre"]).most_common(30):
        stat.append([genre, num])
    stat.append([])
    stat.append(["年代", "影片数"])
    decades = Counter(str(int(r["year"]) // 10 * 10) + "s" for r in rows if r.get("year"))
    for decade, num in sorted(decades.items()):
        stat.append([decade, num])

    note = wb.create_sheet("说明")
    note.column_dimensions["A"].width = 110
    notes = [
        "Filmmate 影视灵感目录",
        "生成时间：" + catalog["generated_at"],
        "共 " + str(catalog["count"]) + " 部：" + "、".join(k + " " + str(v) for k, v in catalog["by_kind"].items()),
        "",
        "用途：用户输入灵感 → 先选题材/情绪 → LLM 结合本库给出创作思路 → 推荐相似作品与参考静帧。",
        "字段：编号、种类、中文名、英文名、年份、时长、情绪、内容梗概、Tag、原片链接、静帧。",
        "",
        "核验口径：",
        "1) 原片链接生成时用 B 站 view 接口确认可播放，并用官方 videoshot/storyboard 接口抽到 10 帧才收录；",
        "2) 静帧 = 播放器 storyboard 预览帧，自动挑选构图/信息量高的帧，去重、避开片头字幕卡与片尾字幕、裁掉黑边；",
        "3) 链接会随时间失效，核验时间见「链接核验时间」列，可用 scripts/build_catalog.py 重跑。",
        "",
        "版权：原片版权归原权利人/上传者；静帧仅用于创作学习与情绪板参考，不做二次分发。",
    ]
    for line in notes:
        note.append([line])
        note.cell(row=note.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(XLSX_OUT)
    return XLSX_OUT


TEMPLATE_FILE = Path(__file__).resolve().parent / "catalog_page_template.html"


def write_html(catalog):
    rows = catalog["titles"]
    data = []
    for r in rows:
        frames = []
        for meta in r.get("frame_meta", []):
            frames.append({"src": frame_rel(meta["path"]), "w": meta["size"][0],
                           "h": meta["size"][1], "t": meta.get("timecode", "")})
        data.append({
            "id": r["id"], "kind": r["kind"], "title_zh": r["title_zh"],
            "title_en": r["title_en"], "year": r["year"], "duration": r["duration"],
            "moods": r["moods"], "genre": r["genre"], "synopsis": r["synopsis"],
            "tags": r["tags"], "url": r["url"], "video_title": r["video_title"],
            "frames": frames,
        })
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<" + chr(92) + "/")
    total_frames = sum(len(r["frames"]) for r in rows)
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    page = (template.replace("__COUNT__", str(len(rows)))
            .replace("__FRAMES__", str(total_frames))
            .replace("__TIME__", catalog["generated_at"])
            .replace("__DATA__", payload))
    HTML_OUT.write_text(page, encoding="utf-8")

    # 同一份画廊再写一份到 static/：由 Filmmate 服务以 /static/catalog.html 直接访问，
    # 图片用 frames/... 相对路径，避免 ../static 在网页里 404 的问题。
    static_payload = payload.replace('"../static/', '"')
    static_page = (template.replace("__COUNT__", str(len(rows)))
                   .replace("__FRAMES__", str(total_frames))
                   .replace("__TIME__", catalog["generated_at"])
                   .replace("__DATA__", static_payload))
    static_html = ROOT / "static" / "catalog.html"
    static_html.parent.mkdir(parents=True, exist_ok=True)
    static_html.write_text(static_page, encoding="utf-8")
    return HTML_OUT


def export_all(catalog=None):
    catalog = catalog or load_catalog()
    DOCS.mkdir(parents=True, exist_ok=True)
    paths = [write_csv(catalog), write_markdown(catalog), write_xlsx(catalog), write_html(catalog)]
    print("导出完成：")
    for path in paths:
        print("  " + str(path.relative_to(ROOT)) + "  (" + str(round(path.stat().st_size / 1024)) + " KB)")
    return paths


if __name__ == "__main__":
    export_all()

