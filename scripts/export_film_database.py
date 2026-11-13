#!/usr/bin/env python3
"""导出「剧本 + 原片」数据库为 Markdown 表格 + CSV，方便逐条比对链接。"""
import csv
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "library" / "films_scripted.json"
MD = ROOT / "docs" / "FILM_DATABASE.md"
CSV_OUT = ROOT / "docs" / "film_database.csv"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}


def check_pdf(url):
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def check_bili(bvid):
    try:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as resp:
            return json.loads(resp.read().decode()).get("code") == 0
    except Exception:
        return False


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows = []
    for i, f in enumerate(data["films"], 1):
        pdf_ok = check_pdf(f["script"]["pdf"])
        bili_ok = check_bili(f["bvid"])
        rows.append({
            "序号": i,
            "中文名": f["title"],
            "英文名": f["title_en"],
            "年份": f["year"],
            "时长": f["duration"],
            "情绪": " / ".join(f["moods"]),
            "BV号": f["bvid"],
            "B站链接": f["url"],
            "剧本页": f["script"]["page"],
            "剧本PDF": f["script"]["pdf"],
            "UP主": f.get("owner", ""),
            "静帧数": len(f.get("frames", [])),
            "B站有效": "✅" if bili_ok else "❌",
            "PDF有效": "✅" if pdf_ok else "❌",
        })

    # CSV
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Markdown
    lines = [
        "# Filmmate 电影数据库（剧本 + 原片）",
        "",
        f"> 导出时间：{data.get('verified_at', '')}　｜　共 **{len(rows)} 部**。",
        "> 每部片都同时有 scriptslug 剧本（页面 + PDF）与 Bilibili 原片；链接状态为导出时实时核验。",
        "",
        "| # | 片名 | 年份 | 时长 | 情绪 | Bilibili 原片 | 剧本 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['序号']} | **{r['中文名']}**<br>{r['英文名']} | {r['年份']} | {r['时长']} | "
            f"{r['情绪']} | [▶ {r['BV号']}]({r['B站链接']}) {r['B站有效']} | "
            f"[页面]({r['剧本页']}) · [PDF]({r['剧本PDF']}) {r['PDF有效']} |"
        )
    lines += ["", "## 未匹配的影片（B 站无合格原片）", "", "| 片名 | 原因 |", "|---|---|"]
    for m in data.get("misses", []):
        lines.append(f"| {m['title']} | {m['reason']} |")
    lines += [
        "",
        "> 匹配标准：B 站原片时长与真实片长误差 ≤15 分钟、单 P、标题命中、非解说/原声/游戏；",
        "> 不满足的不硬凑。PDF 链接来自 scriptslug 的公开资源，版权归原作者。",
        "",
    ]
    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"导出 {len(rows)} 部 → {MD.relative_to(ROOT)} / {CSV_OUT.relative_to(ROOT)}")
    bad = [r for r in rows if r["B站有效"] == "❌" or r["PDF有效"] == "❌"]
    print("链接异常：", [(r["中文名"], r["B站有效"], r["PDF有效"]) for r in bad] or "无")


if __name__ == "__main__":
    main()
