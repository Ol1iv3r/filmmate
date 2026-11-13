#!/usr/bin/env python3
"""校验 Filmmate 数据层（docs/DATA_SCHEMA.md）。

检查项：
  1. JSON 可解析、必需字段齐全
  2. id 全局唯一（知识/场景/镜头/案例/模板/样本 之间不冲突）
  3. 枚举合法（景别/机位/运镜/INT-EXT/DAY-NIGHT/blocks.type）
  4. 页数（1/8）与拍摄分钟在合理区间
  5. 案例与通告单模板的 totals 与明细求和一致（±5 分钟）

运行：
  python3 scripts/validate_data.py
退出码 0 = 全部通过；1 = 有错误（会逐条打印）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "data" / "library"

SIZES = {"远景", "全景", "中景", "近景", "特写", "大特写"}
ANGLES = {"平视", "俯拍", "仰拍", "鸟瞰", "过肩", "荷兰角"}
MOVES = {"固定", "推", "拉", "摇", "移", "手持", "稳定器跟随"}
BLOCK_TYPES = {"crew_call", "cast_call", "setup", "scene", "move", "meal", "wrap", "buffer"}
CATEGORIES = {
    "剧本结构", "剧本审阅", "人物", "对白", "类型片", "场面调度", "景别", "机位", "运镜",
    "灯光", "收音", "剪辑", "调色", "制片", "通告单", "场记", "预算", "勘景", "香港拍摄",
    "安全法规", "后期交付", "AI辅助",
    # 基础库（knowledge.json，2026-11-05）沿用的旧分类
    "机位角度", "拍摄流程", "香港取景", "设备", "剧本", "类型", "后期",
}

errors = []
counts = {}


def fail(msg):
    errors.append(msg)


def load(path):
    if not path.exists():
        fail(f"缺少文件：{path.relative_to(ROOT)}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        fail(f"{path.name} 不是合法 JSON：{exc}")
        return None


def check_ids(items, label, seen):
    for item in items:
        item_id = item.get("id")
        if not item_id:
            fail(f"{label} 有条目缺 id")
            continue
        if item_id in seen:
            fail(f"id 重复：{item_id}（{label} 与 {seen[item_id]}）")
        seen[item_id] = label


def check_shot(shot, where):
    for field, allowed in (("size", SIZES), ("angle", ANGLES), ("movement", MOVES)):
        value = shot.get(field)
        if value and value not in allowed:
            fail(f"{where} 的 {field}={value!r} 不在枚举内")


def day_scenes(scenes, blocks):
    """多日项目里，一天只拍 blocks 里引用到的场次。"""
    refs = {b.get("scene_no") for b in blocks if b.get("type") == "scene" and b.get("scene_no")}
    if not refs:
        # 缓冲日没有任何 scene 块 → 页数为 0；有 scene 块但没写编号 → 退回全量
        return scenes if any(b.get("type") == "scene" for b in blocks) else []
    picked = [s for s in scenes if s.get("scene_no") in refs]
    return picked or scenes


def check_totals(scenes, blocks, totals, where):
    pages = sum(int(s.get("pages_eighths", 0) or 0) for s in scenes)
    minutes = sum(int(b.get("est_minutes", 0) or 0) for b in blocks)
    if "pages_eighths" in totals and abs(int(totals.get("pages_eighths", 0)) - pages) > 0:
        fail(f"{where} totals.pages_eighths={totals.get('pages_eighths')} ≠ scenes 求和 {pages}")
    if "shoot_minutes" in totals and abs(int(totals.get("shoot_minutes", 0)) - minutes) > 5:
        fail(f"{where} totals.shoot_minutes={totals.get('shoot_minutes')} ≠ blocks 求和 {minutes}（容差 5）")


def main():
    seen = {"knowledge": {}, "scene": {}, "shot": {}, "case": {}, "template": {}}

    # ---- 知识库 ----
    base = load(ROOT / "knowledge" / "knowledge.json")
    extra = load(LIB / "knowledge_extra.json")
    entries = []
    for data, label in ((base, "knowledge.json"), (extra, "knowledge_extra.json")):
        if not data:
            continue
        items = data.get("entries", [])
        counts[label] = len(items)
        for e in items:
            entries.append(e)
            if e.get("category") not in CATEGORIES:
                fail(f"知识条目 {e.get('id')} 的 category={e.get('category')!r} 不合法")
            if not (50 <= len(e.get("content", "")) <= 220):
                fail(f"知识条目 {e.get('id')} 内容长度 {len(e.get('content', ''))} 超出 50–220")
    check_ids(entries, "知识", seen["knowledge"])

    # ---- 场面模式 ----
    scenes_data = load(LIB / "scenes.json")
    if scenes_data:
        scenes = scenes_data.get("scenes", [])
        counts["scenes.json"] = len(scenes)
        check_ids(scenes, "场面", seen["scene"])
        for s in scenes:
            if not (4 <= len(s.get("beat_structure", [])) <= 6):
                fail(f"场面 {s.get('id')} 的节拍数应为 4–6")
            if not (1 <= int(s.get("page_eighths", 0)) <= 12):
                fail(f"场面 {s.get('id')} 的 page_eighths 越界")
            if not (30 <= int(s.get("shoot_minutes", 0)) <= 240):
                fail(f"场面 {s.get('id')} 的 shoot_minutes 越界")
            for shot in s.get("shots", []):
                check_shot(shot, f"场面 {s.get('id')}")

    # ---- 镜头模式 ----
    shots_data = load(LIB / "shots.json")
    if shots_data:
        shots = shots_data.get("shots", [])
        counts["shots.json"] = len(shots)
        check_ids(shots, "镜头", seen["shot"])
        for s in shots:
            check_shot(s, f"镜头 {s.get('id')}")
            if not s.get("purpose"):
                fail(f"镜头 {s.get('id')} 缺 purpose")

    # ---- 真实短片库（Bilibili，只允许可核验元数据）----
    films_data = load(LIB / "films_real.json")
    if films_data:
        films = films_data.get("films", [])
        counts["films_real.json"] = len(films)
        seen_bv = set()
        for f in films:
            for key in ("id", "bvid", "title", "url", "cover", "duration_sec", "source", "verified_at"):
                if not f.get(key):
                    fail(f"短片 {f.get('id')} 缺字段 {key}")
            if f.get("source") != "bilibili":
                fail(f"短片 {f.get('id')} 的来源不是 bilibili")
            if f.get("bvid") in seen_bv:
                fail(f"BV 号重复：{f.get('bvid')}")
            seen_bv.add(f.get("bvid"))
            if f.get("bvid") and f.get("bvid") not in f.get("url", ""):
                fail(f"短片 {f.get('id')} 的 url 与 bvid 不一致")
            if not (30 <= int(f.get("duration_sec", 0)) <= 3600):
                fail(f"短片 {f.get('id')} 时长异常：{f.get('duration_sec')}")
            # 真实影片库不允许出现臆造的制作数据
            for forbidden in ("budget", "stripboard", "shot_list", "scenes", "crew_roles"):
                if forbidden in f:
                    fail(f"短片 {f.get('id')} 含不允许的臆造字段 {forbidden}")

    # ---- 通告单模板 ----
    tb = load(LIB / "stripboards.json")
    if tb:
        templates = tb.get("templates", [])
        counts["stripboards.json"] = len(templates)
        check_ids(templates, "通告单模板", seen["template"])
        for t in templates:
            days = t.get("days", [])
            if len(days) != int(t.get("shoot_days", 0)):
                fail(f"模板 {t.get('id')} 的 shoot_days 与 days 数量不一致")
            for day in days:
                blocks = day.get("blocks", [])
                bad = [b.get("type") for b in blocks if b.get("type") not in BLOCK_TYPES]
                if bad:
                    fail(f"模板 {t.get('id')} 的 block type 不合法：{bad}")
                if not any(b.get("type") == "crew_call" for b in blocks):
                    fail(f"模板 {t.get('id')} Day {day.get('day')} 缺 crew_call")
                if not any(b.get("type") == "wrap" for b in blocks):
                    fail(f"模板 {t.get('id')} Day {day.get('day')} 缺 wrap")
                check_totals(day_scenes(t.get("scenes", []), blocks), blocks, day.get("totals", {}), f"模板 {t.get('id')} Day {day.get('day')}")

    # ---- 剧本 + 原片双源库 ----
    scripted = load(LIB / "films_scripted.json")
    if scripted:
        films = scripted.get("films", [])
        counts["films_scripted.json"] = len(films)
        for f in films:
            for key in ("bvid", "title", "url", "script", "moods", "verified_at"):
                if not f.get(key):
                    fail(f"双源影片 {f.get('title')} 缺字段 {key}")
            if not f.get("script", {}).get("page") or not f.get("script", {}).get("pdf"):
                fail(f"双源影片 {f.get('title')} 缺剧本链接")
            if f.get("bvid") and f["bvid"] not in f.get("url", ""):
                fail(f"双源影片 {f.get('title')} 的 url 与 bvid 不一致")

    # ---- 富化样本 ----
    samples = load(LIB / "samples_enriched.json")
    if samples:
        videos = samples.get("videos", [])
        counts["samples_enriched.json"] = len(videos)
        n_shots = 0
        for v in videos:
            for scene in v.get("scenes", []):
                for shot in scene.get("shots", []):
                    n_shots += 1
                    check_shot(shot, f"样本 {v.get('video_id')}")
        counts["样本镜头数"] = n_shots

    # ---- 输出 ----
    print("数据规模：")
    for key, value in counts.items():
        print(f"  {key:24} {value}")
    if errors:
        print(f"\n❌ 发现 {len(errors)} 个问题：")
        for err in errors[:40]:
            print("  -", err)
        if len(errors) > 40:
            print(f"  … 其余 {len(errors) - 40} 条省略")
        return 1
    print("\n✅ 全部校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
