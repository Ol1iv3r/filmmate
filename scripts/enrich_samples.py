#!/usr/bin/env python3
"""把 50 个视频样本（只有时间码 + 英文描述）富化成专业镜头数据。

输入：_ref/AI-Project/AI-Project/samplesv*.json   （原始：youtube_video_id / title / segments）
输出：data/library/samples_enriched.json          （v2：scenes[] + shots[] + 节奏统计）

派生字段（derived=true）说明：
- size / angle / movement：由 description 里的镜头术语解析，解析不到时按景别默认值兜底；
- lighting / setting：由描述中的光线、场景词推断；
- sound：原数据没有音轨分析，按品类（广告/纪录/美食/音乐）推断，标记 inferred；
- structure：广告按 hook→product→payoff 切，纪录片/教程按场景切。
这些都是「可从文本推出」的合理标注，不声称是原片逐帧分析结果。

运行：python3 scripts/enrich_samples.py
"""
import glob
import json
import re
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_ref" / "AI-Project" / "AI-Project"
OUT = ROOT / "data" / "library" / "samples_enriched.json"

# ---------------------------------------------------------------- 解析规则
SIZE_RULES = [
    (r"extreme close[- ]up", "大特写"),
    (r"macro", "大特写"),
    (r"medium close[- ]up|medium close up", "近景"),
    (r"close[- ]up|close up", "特写"),
    (r"medium wide", "全景"),
    (r"medium shot|medium tracking|medium action|mid[- ]shot", "中景"),
    (r"wide establishing|establishing shot|establishing", "全景"),
    (r"full shot", "全景"),
    (r"wide shot|wide view|wide angle|\bwide\b", "全景"),
    (r"two[- ]shot", "中景"),
    (r"pov shot", "中景"),
]

ANGLE_RULES = [
    (r"overhead|top[- ]down|bird'?s[- ]eye", "鸟瞰"),
    (r"aerial|drone", "鸟瞰"),
    (r"high[- ]angle", "俯拍"),
    (r"low[- ]angle", "仰拍"),
    (r"over[- ]the[- ]shoulder", "过肩"),
    (r"dutch", "荷兰角"),
]

MOVE_RULES = [
    (r"gimbal|stabiliz", "稳定器跟随"),
    (r"tracking|dolly|follow", "移"),
    (r"\bpan\b|panning|tilt", "摇"),
    (r"zoom in|push in|push-in", "推"),
    (r"zoom out|pull out|pull-back", "拉"),
    (r"handheld|hand-held", "手持"),
    (r"aerial|drone", "移"),
]

SETTING_RULES = [
    ("studio", r"studio|soundstage|backdrop|seamless"),
    ("indoor", r"indoor|interior|kitchen|room|office|cabin|store|shop|restaurant|bus|car|house|apartment"),
    ("outdoor", r"outdoor|exterior|street|snow|forest|beach|landscape|sky|garden|park|mountain|driveway|suburb|field"),
    ("animation", r"animated|animation|hand-drawn|cartoon"),
]

LIGHT_WORDS = [
    ("自然日光", r"natural daylight|bright daylight|sunlight|sunny"),
    ("阴天散射光", r"overcast|diffused|cloudy"),
    ("暖光", r"warm light|warm lighting|golden hour|golden"),
    ("冷光", r"cool light|cold light|blue light|moonlight"),
    ("霓虹", r"neon"),
    ("暗调/低调光", r"dark|dim|low[- ]key|shadow|silhouette"),
    ("棚拍布光", r"studio light|softbox|key light|studio setting"),
]

AD_WORDS = r"commercial|advertisement|\bad\b|brand|logo|promo|campaign|product"
DOC_WORDS = r"bbc|earth|documentary|nature|wildlife|experiment|how does"
FOOD_WORDS = r"recipe|bread|cook|baking|food|kitchen|chef|potato|cheese"
MUSIC_WORDS = r"music video|official video|lyrics|song|mv\b"


def first_match(rules, text, default):
    for pattern, value in rules:
        if re.search(pattern, text):
            return value
    return default


def parse_time(ts):
    m, s = ts.split(":")
    return int(m) * 60 + int(s)


def classify(title, keywords):
    blob = (title + " " + " ".join(keywords)).lower()
    if re.search(MUSIC_WORDS, blob):
        return "music_video"
    if re.search(DOC_WORDS, blob):
        return "documentary"
    if re.search(FOOD_WORDS, blob):
        return "food_tutorial"
    if re.search(AD_WORDS, blob):
        return "commercial"
    return "short_form"


def sound_for(kind):
    return {
        "commercial": "音乐 + 配音/VO，产品音效前置（推断）",
        "documentary": "自然声 + 旁白，保留环境底噪（推断）",
        "food_tutorial": "音乐 + 烹饪拟音（foley），强调质感声（推断）",
        "music_video": "以音乐为主，画面剪辑跟随节拍（推断）",
        "short_form": "现场声为主（推断）",
    }[kind]


def detect_setting(desc):
    low = desc.lower()
    for name, pattern in SETTING_RULES:
        if re.search(pattern, low):
            return name
    return "neutral"


def day_night(desc):
    low = desc.lower()
    if re.search(r"night|dark|evening|midnight", low):
        return "NIGHT"
    if re.search(r"sunset|dusk|golden hour", low):
        return "DUSK"
    if re.search(r"dawn|sunrise", low):
        return "DAWN"
    return "DAY"


def extract_subject(desc):
    """去掉镜头术语，留下主体与动作，作为检索用的干净文本。"""
    text = re.sub(
        r"^(extreme close[- ]up|macro close[- ]up|close[- ]up|medium close[- ]up|medium tracking|"
        r"medium shot|wide establishing|establishing shot|wide shot|full shot|high[- ]angle|"
        r"low[- ]angle|overhead|aerial|pov)?\s*(shot|view|footage)?\s*(of|showing|as|capturing|focusing on)?\s*",
        "",
        desc.strip(),
        flags=re.I,
    )
    return text.strip() or desc.strip()


def build_shots(segments):
    shots = []
    for i, seg in enumerate(segments, 1):
        desc = seg.get("description", "").strip()
        kws = " ".join(seg.get("keywords", []))
        cam_text = f"{desc} {kws}".lower()
        start, end = parse_time(seg["time_start"]), parse_time(seg["time_end"])
        shots.append({
            "shot_no": i,
            "start": seg["time_start"],
            "end": seg["time_end"],
            "duration_sec": max(1, end - start),
            "size": first_match(SIZE_RULES, cam_text, "中景"),
            "angle": first_match(ANGLE_RULES, cam_text, "平视"),
            "movement": first_match(MOVE_RULES, cam_text, "固定"),
            "setting": detect_setting(desc),
            "day_night": day_night(desc),
            "lighting": first_match(LIGHT_WORDS, desc.lower(), "未标注"),
            "subject": extract_subject(desc)[:160],
            "description": desc,
            "keywords": seg.get("keywords", []),
            "derived": True,
        })
    return shots


def group_scenes(shots, kind):
    """按场景/光线变化切场；广告额外给出 hook/product/payoff 三段式。"""
    scenes = []
    current = []
    for shot in shots:
        if not current:
            current = [shot]
            continue
        prev = current[-1]
        changed = (
            shot["setting"] != prev["setting"]
            or (shot["day_night"] != prev["day_night"] and shot["setting"] != "neutral")
            or int(shot["start"].split(":")[1]) - int(prev["end"].split(":")[1]) > 15
            or len(current) >= 6
        )
        if changed:
            scenes.append(current)
            current = [shot]
        else:
            current.append(shot)
    if current:
        scenes.append(current)

    total = shots[-1]["duration_sec"] + parse_time(shots[-1]["start"]) if shots else 0
    out = []
    for idx, group in enumerate(scenes, 1):
        start = group[0]["start"]
        end = group[-1]["end"]
        if kind == "commercial":
            t = parse_time(start) / max(1, total)
            if total and t < 0.15:
                label = "hook（钩子）"
            elif total and t < 0.72:
                label = "product（产品/冲突展开）"
            else:
                label = "payoff（收尾/品牌落点）"
        else:
            label = f"场景 {idx}"
        out.append({
            "scene_no": idx,
            "label": label,
            "start": start,
            "end": end,
            "setting": group[0]["setting"],
            "day_night": group[0]["day_night"],
            "shot_count": len(group),
            "shots": group,
        })
    return out


def enrich(video):
    shots = build_shots(video.get("segments", []))
    kind = classify(video.get("title", ""), video.get("keywords", []))
    scenes = group_scenes(shots, kind)
    durations = [s["duration_sec"] for s in shots]
    total = sum(durations)
    asl = round(statistics.mean(durations), 2) if durations else 0
    size_dist = Counter(s["size"] for s in shots)
    move_dist = Counter(s["movement"] for s in shots)
    dominant = ", ".join(f"{k}{v}" for k, v in size_dist.most_common(3))

    pacing = "快" if asl and asl <= 2.5 else "中" if asl <= 5 else "慢"
    coverage = (
        f"{len(shots)} 个镜头 / {total}s，平均镜头长度 {asl}s（{pacing}节奏）；"
        f"景别以 {dominant} 为主；运镜以 {'、'.join(k for k, _ in move_dist.most_common(2)) if move_dist else '固定'} 为主。"
    )

    rag_words = [
        video.get("title", ""),
        kind,
        " ".join(video.get("keywords", [])),
        " ".join(sorted({s["size"] for s in shots})),
        " ".join(sorted({s["movement"] for s in shots})),
        " ".join(sorted({s["setting"] for s in shots})),
        " ".join(sorted({s["lighting"] for s in shots if s["lighting"] != "未标注"})),
        " ".join(s["subject"] for s in shots[:6]),
    ]

    return {
        "video_id": video.get("youtube_video_id", ""),
        "title": video.get("title", ""),
        "format": kind,
        "duration_sec": total,
        "keywords": video.get("keywords", []),
        "sound_approach": sound_for(kind),
        "scenes": scenes,
        "stats": {
            "shot_count": len(shots),
            "avg_shot_length_sec": asl,
            "cuts_per_min": round(len(shots) / (total / 60), 1) if total else 0,
            "pacing": pacing,
            "size_distribution": dict(size_dist),
            "movement_distribution": dict(move_dist),
            "coverage_note": coverage,
        },
        "rag_keywords": " ".join(w for w in rag_words if w).strip(),
        "derived": True,
    }


def main():
    files = sorted(glob.glob(str(SRC / "samplesv*.json")))
    if not files:
        raise SystemExit(f"找不到样本文件：{SRC}/samplesv*.json")

    videos = []
    for path in files:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        videos.append(enrich(raw))

    payload = {
        "name": "Filmmate 视频样本库 · 专业富化版",
        "description": "50 个真实短片/广告样本，按镜头语法解析并分组；derived=true 表示字段由描述文本推断。",
        "source": "_ref/AI-Project (Almosty 收集，原 schema 仅 time/description)",
        "count": len(videos),
        "shot_count": sum(v["stats"]["shot_count"] for v in videos),
        "videos": videos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 统计报告 ----
    sizes, moves, angles, formats = Counter(), Counter(), Counter(), Counter()
    for v in videos:
        formats[v["format"]] += 1
        for sc in v["scenes"]:
            for s in sc["shots"]:
                sizes[s["size"]] += 1
                moves[s["movement"]] += 1
                angles[s["angle"]] += 1
    print(f"写入 {OUT.relative_to(ROOT)}：{len(videos)} 个视频 / {payload['shot_count']} 个镜头")
    print("品类:", dict(formats))
    print("景别:", dict(sizes))
    print("运镜:", dict(moves))
    print("机位:", dict(angles))
    asls = [v["stats"]["avg_shot_length_sec"] for v in videos]
    print(f"平均镜头长度：{statistics.mean(asls):.2f}s（最快 {min(asls)}s / 最慢 {max(asls)}s）")
    print("场景总数:", sum(len(v["scenes"]) for v in videos))


if __name__ == "__main__":
    main()
