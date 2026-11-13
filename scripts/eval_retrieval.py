#!/usr/bin/env python3
"""检索质量评测：用代表性查询检查 RAG 是否命中该命中的资料。

每个用例给出「期望命中」的关键词（出现在标题/id/名称里即算命中），
分别测 知识库 / 案例 / 场面 / 镜头 / 通告单模板 五个索引。

运行：python3 scripts/eval_retrieval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import case_store  # noqa: E402
import library  # noqa: E402
import rag  # noqa: E402

CASES = [
    # (索引, 查询, 期望命中的关键词)
    ("knowledge", "剧本伏笔没有回收怎么办", ["回收", "Payoff", "setup"]),
    ("knowledge", "一天能拍多少页", ["页", "Page Eighths", "页数"]),
    ("knowledge", "香港航拍要申请吗", ["无人机", "航拍", "香港"]),
    ("knowledge", "夜戏怎么布光", ["夜", "布光", "灯光"]),
    ("knowledge", "场记要记什么", ["场记", "连戏", "continuity"]),
    ("knowledge", "对白太直白怎么办", ["潜台词", "subtext", "对白"]),
    ("knowledge", "动作片追逐怎么拍省钱", ["动作", "预算", "低成本"]),
    ("cases", "孤独 压抑", ["小丑", "爱尔兰人", "奥本海默"]),
    ("cases", "温暖 成长", ["绿皮书", "小妇人", "伯德小姐"]),
    ("cases", "悬疑 反转", ["利刃出鞘", "秘密会议"]),
    ("scenes", "天台告白的戏怎么拍", ["天台", "告白"]),
    ("scenes", "审讯室对峙怎么调度", ["审讯", "对峙"]),
    ("scenes", "恐怖片地下室惊吓", ["地下室", "恐怖", "惊吓"]),
    ("shots", "推镜头什么时候用", ["推", "push"]),
    ("shots", "荷兰角表达不安", ["荷兰角", "dutch"]),
    ("shots", "过肩镜头对话", ["过肩", "over"]),
    ("stripboards", "单日广告通告单怎么排", ["广告", "单日"]),
    ("stripboards", "三天短片拍摄日程", ["短片", "3", "三"]),
    ("stripboards", "纪录访谈要几个机位", ["访谈", "纪录"]),
]


def fetch(index, query):
    if index == "knowledge":
        hits = rag.retrieve(query, k=3)
        return [(h["title"], h.get("category", "")) for h in hits]
    if index == "cases":
        hits = case_store.search_cases(query, k=3)
        return [(h["title"], h.get("genre", "")) for h in hits]
    if index == "scenes":
        hits = library.search_scenes(query, k=3)
        return [(h["name_zh"], h.get("dramatic_function", "")) for h in hits]
    if index == "shots":
        hits = library.search_shots(query, k=3)
        return [(h["name_zh"], h.get("purpose", "")) for h in hits]
    hits = library.search_templates(query, k=2)
    return [(h["name"], h.get("type", "")) for h in hits]


def main():
    passed = 0
    for index, query, expects in CASES:
        hits = fetch(index, query)
        blob = " ".join(f"{title} {meta}" for title, meta in hits)
        ok = any(word.lower() in blob.lower() for word in expects)
        passed += ok
        mark = "✅" if ok else "❌"
        top = " | ".join(title for title, _ in hits[:2]) or "（无结果）"
        print(f"{mark} [{index:12}] {query:22} → {top}")
        if not ok:
            print(f"      期望包含：{expects}")
    total = len(CASES)
    print(f"\n命中率：{passed}/{total} = {passed / total:.0%}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
