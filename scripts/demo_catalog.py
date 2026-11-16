#!/usr/bin/env python3
"""生成 docs/catalog_demo.md：演示「灵感 → 选题材 → 相似片推荐」的实际输出。

用法：.venv/bin/python scripts/demo_catalog.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import catalog  # noqa: E402

IDEAS = [
    "一个外卖员在暴雨夜捡到一部手机，里面有一段不该看到的视频",
    "我想拍一个关于母女和解的家庭故事，克制一点，不要煽情",
    "做一个竖屏短剧：女主一睁眼回到 1998 年，成了三个孩子的后妈",
]


def render(idea):
    result = catalog.suggest(idea, k=6)
    lines = [f"## 灵感：{idea}", ""]
    lines.append("**推荐先选的题材**：" + "；".join(
        f"{x['kind']}（{x['description']}）" for x in result["kinds"]))
    if result["moods"]:
        lines.append("**情绪基调**：" + "、".join(f"{x['mood']}({x['count']})" for x in result["moods"]))
    if result["genres"]:
        lines.append("**类型分布**：" + "、".join(f"{x['genre']}({x['count']})" for x in result["genres"]))
    lines.append("")
    lines.append("| # | 片名 | 年份 | 时长 | 情绪 | 相似点 | 原片 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, t in enumerate(result["titles"], 1):
        why = "；".join(t.get("why") or []) or "、".join((t.get("tags") or [])[:3])
        lines.append(f"| {i} | **{t['title_zh']}**（{t['title_en']}） | {t['year']} | "
                     f"{t['duration']} | {'/'.join(t.get('moods') or [])} | {why} | [B 站]({t['url']}) |")
    lines.append("")
    lines.append("<details><summary>可直接放进 LLM 提示词的检索块</summary>")
    lines.append("")
    lines.append("    " + catalog.prompt_block(idea, k=4).replace("\n", "\n    "))
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def main():
    stat = catalog.stats()
    header = [
        "# Filmmate 影视灵感目录 · 检索演示",
        "",
        f"> 库规模：{stat['count']} 部作品 / {stat['frames']} 张静帧；"
        + "、".join(f"{k} {v}" for k, v in stat["by_kind"].items()),
        "> 目的：用户输入灵感 → 先看到「建议题材 + 情绪 + 类型」→ 再看到真实相似作品（带可看链接与 10 张静帧）→ LLM 据此生成可拍思路。",
        "",
        "## 可选题材（给用户的第一步）",
        "",
        "| 题材 | 片量 | 说明 |",
        "|---|---|---|",
    ]
    for item in catalog.kind_options():
        header.append(f"| {item['kind']} | {item['count']} | {item['description']} |")
    header.append("")
    body = "\n".join(render(idea) for idea in IDEAS)
    out = ROOT / "docs" / "catalog_demo.md"
    out.write_text("\n".join(header) + "\n" + body, encoding="utf-8")
    print("已生成", out.relative_to(ROOT), f"({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
