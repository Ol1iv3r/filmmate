"""创作辅助工具:剧本检查 / 分镜建议 / 拍摄 Rundown / 日程规划 / 灵感激发。

每个工具都有两种实现:
  - 在线模式:DeepSeek 按 JSON 规范生成结构化结果(见 prompts.py)
  - 离线模式:本地启发式/模板(无需 API Key,保证现场演示不翻车)
两个模式的输出结构完全一致,前端无需区分。
"""
import asyncio
import logging
import math
import random
import re
from collections import Counter

import llm
import prompts
import sample_search

logger = logging.getLogger("tools")

# --------------------------------------------------------------------------
# 意图识别(关键词规则,零延迟;前端快捷按钮可强制指定工具)
# --------------------------------------------------------------------------
_REVIEW_WORDS = ["检查", "漏洞", "审", "批改", "评价", "反馈", "意见", "问题", "bug", "review", "plot hole"]
_STORY_WORDS = ["分镜", "storyboard", "分镜头", "镜头表", "shot list", "shotlist", "video plan", "拍摄分镜"]
_RUNDOWN_WORDS = ["rundown", "通告", "call sheet", "拍摄清单", "拍摄安排", "拍摄表"]
_SCHEDULE_WORDS = ["日程", "排期", "schedule", "拍摄计划", "拍几天", "拍摄日"]
_IDEA_WORDS = ["灵感", "题材", "想法", "idea", "想拍", "点子", "创意", "brainstorm"]
_CASE_WORDS = ["案例", "参考案例", "类似案例", "借鉴", "别人怎么拍", "有没有类似", "sample case", "example case", "找例子"]


def _has_any(text, words):
    low = text.lower()
    return any(w in low for w in words)


def detect_tool(message: str):
    """返回 tool 名:review / storyboard / rundown / schedule / inspiration / None(知识问答)。"""
    msg = message.strip()
    if not msg:
        return None
    low = msg.lower()
    # 1) 明确讨论剧本 + 检查类词 → 剧本检查
    if _has_any(msg, ["剧本", "script", "稿子", "大纲", "梗概"]) and _has_any(msg, _REVIEW_WORDS):
        return "review"
    # 2) 粘贴了一大段疑似剧本(长文本、含场次/对白标记)→ 默认按剧本检查
    if len(msg) > 150 and (re.search(r"第\s*\d+\s*[场幕景]", msg) or re.search(r"scene\s*\d+", low) or re.search(r"^\s*[^:]{1,8}[:：].+$", msg, re.M)):
        return "review"
    if _has_any(msg, _STORY_WORDS):
        return "storyboard"
    if _has_any(msg, _CASE_WORDS):
        return "inspiration"
    if _has_any(msg, _SCHEDULE_WORDS) and "日程" in msg:
        return "schedule"
    if _has_any(msg, _RUNDOWN_WORDS):
        return "rundown"
    if _has_any(msg, _SCHEDULE_WORDS):
        return "schedule"
    if _has_any(msg, _IDEA_WORDS):
        return "inspiration"
    return None


# --------------------------------------------------------------------------
# 剧本解析(离线工具共用)
# --------------------------------------------------------------------------
SCENE_RE = re.compile(r"^\s*(?:第\s*\d+\s*[场幕景]|scene\s*\d+|SCENE\s*\d+|第[一二三四五六七八九十]+\s*[场幕景])", re.I)
DIALOGUE_RE = re.compile(r"^\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·\-]{0,7})\s*[:：]\s*(.+)$")
TIME_WORDS = ["凌晨", "清晨", "早上", "上午", "中午", "下午", "傍晚", "黄昏", "晚上", "夜里", "深夜", "午夜", "夜"]


def parse_scenes(text: str):
    """把剧本切成场次。无场次标记时按空行分段;再不行整体作为一场。"""
    lines = [l for l in text.splitlines()]
    scenes, cur = [], []
    for line in lines:
        if SCENE_RE.match(line) and cur:
            scenes.append(cur)
            cur = [line]
        else:
            cur.append(line)
    if cur:
        scenes.append(cur)
    # 只有一场且行数很多 → 按空行细分
    if len(scenes) == 1 and len(scenes[0]) > 12:
        blocks, buf = [], []
        for line in scenes[0]:
            if not line.strip() and buf:
                blocks.append(buf)
                buf = []
            else:
                buf.append(line)
        if buf:
            blocks.append(buf)
        if len(blocks) > 1:
            scenes = blocks
    return [[l for l in s if l.strip()] for s in scenes if any(l.strip() for l in s)]


def extract_dialogues(text: str):
    """返回 [(角色, 台词, 行号)]。"""
    out = []
    for i, line in enumerate(text.splitlines()):
        m = DIALOGUE_RE.match(line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip(), i))
    return out


def _scene_time(scene_lines):
    for l in scene_lines:
        for t in TIME_WORDS:
            if t in l:
                return t
        # 场景标记里的独立「日」(如"第2场 天台 日"),排除"明天/日本"等词
        if re.search(r"(^|[\s。,:、\-])日($|[\s。,:、\-])", l):
            return "日"
    return None


def _pick_topic(text: str):
    """从用户输入中提取主题词,用于离线模板填充。"""
    # 优先匹配「拍一部《X》」「拍一个X」「关于X」等结构(拍字后面不能是"摄")
    m = re.search(r"拍(?!摄)(?:一部|一个|一支|支|个)?(?:关于|有关)?[《「『]?([^《》「」『』\s,。,:，;、]{2,12})", text)
    if m:
        topic = m.group(1)
    else:
        t = re.sub(r"^(帮我|给我|请|我想|我要|麻烦|来|排|做|写|plan|make)", "", text.strip())
        m = re.search(r"([^\s,。,:，;、]{2,12})", t)
        topic = m.group(1) if m else "我的短片"
    topic = re.sub(r"(的戏|的短片|的故事|的影片|的视频|的剧本)$", "", topic)
    if re.match(r"^(第\s*\d+\s*[场幕景]|scene\s*\d+)", text.strip(), re.I):
        topic = "我的短片"
    # 去掉开头多余的"拍摄"字样
    topic = re.sub(r"^(拍摄|拍)", "", topic)
    return topic or "我的短片"


# --------------------------------------------------------------------------
# 剧本检查 review
# --------------------------------------------------------------------------
PROP_WORDS = ["钥匙", "手机", "信", "照片", "枪", "刀", "纸条", "日记", "戒指", "项链", "怀表", "伞"]


def offline_review(text: str):
    """离线剧本检查:基于启发式规则找出可解释的漏洞(在线模式由 LLM 做深度审阅)。"""
    scenes = parse_scenes(text)
    dialogues = extract_dialogues(text)
    issues, strengths = [], []
    first_third = max(1, len(text) // 3)

    # --- 时间线检查 ---
    times = [(i, _scene_time(s)) for i, s in enumerate(scenes)]
    prev = None
    for idx, t in times:
        if t and prev is not None and t != prev[1]:
            marker = "\n".join(scenes[prev[0]][:1])
            tail = text[text.find(marker) + len(marker):] if marker and marker in text else text
            if not re.search(r"第二天|次日|之后|稍后|过了一会儿|接着|转场|Later|Next day", tail, re.I):
                issues.append({
                    "type": "时间线", "severity": "中", "location": f"第{idx + 1}场(相对)",
                    "quote": "", "problem": f"上一场是「{prev[1]}」,这一场变为「{t}」,中间没有交代时间过渡。",
                    "suggestion": "在两场之间加一句过渡说明(如“次日清晨”)或加入时间过渡镜头。",
                })
        if t:
            prev = (idx, t)

    # --- 人物检查:只出现一次且不是最后一场的角色 ---
    name_count = Counter(n for n, _, _ in dialogues)
    name_scene = {}
    for i, s in enumerate(scenes):
        stext = "\n".join(s)
        for n in list(name_count):
            if n in stext:
                name_scene.setdefault(n, []).append(i + 1)
    for n, c in name_count.items():
        appear = name_scene.get(n, [])
        if c >= 1 and len(appear) == 1 and appear[0] != len(scenes):
            issues.append({
                "type": "人物动机", "severity": "中", "location": f"第{appear[0]}场",
                "quote": f"角色「{n}」", "problem": f"角色「{n}」只出现在第 {appear[0]} 场,之后消失且没有交代去向。",
                "suggestion": f"补一场交代「{n}」的离开,或让 TA 在后文再出现一次并交代去向。",
            })

    # --- 对白检查:过长 / 重复 ---
    for n, line, ln in dialogues:
        if len(line) > 60:
            issues.append({
                "type": "对白", "severity": "低", "location": f"第{ln + 1}行",
                "quote": line[:20] + "…", "problem": f"「{n}」这句台词超过 60 字,信息直给、缺少呼吸感。",
                "suggestion": "拆成两句并加入动作/潜台词,或把解释性内容转为画面呈现(Show, don't tell)。",
            })
    seen = {}
    for n, line, ln in dialogues:
        key = line.strip()
        if len(key) > 8 and key in seen:
            issues.append({
                "type": "对白", "severity": "低", "location": f"第{seen[key] + 1}行 / 第{ln + 1}行",
                "quote": key[:20] + "…", "problem": "同一句台词重复出现。",
                "suggestion": "删除或改写其中一处,重复只有在强调主题时才有价值。",
            })
        seen[key] = ln

    # --- 伏笔未回收(契诃夫之枪)---
    for prop in PROP_WORDS:
        positions = [m.start() for m in re.finditer(prop, text)]
        if positions and max(positions) < first_third and len(positions) == 1:
            issues.append({
                "type": "情节漏洞", "severity": "中", "location": "开头部分",
                "quote": f"「{prop}」", "problem": f"「{prop}」在开头出现了一次,之后再未出现——契诃夫之枪:开头出现的道具必须兑现。",
                "suggestion": f"要么在后文让「{prop}」发挥作用,要么删掉这个细节。",
            })

    # --- 开场钩子 ---
    first_scene = "\n".join(scenes[0]) if scenes else ""
    if first_scene and not re.search(r"但|可是|突然|竟然|却发现|争吵|冲突|拒绝|决定|意外|死|消失|秘密", first_scene):
        issues.append({
            "type": "结构", "severity": "低", "location": "第1场",
            "quote": "", "problem": "第一场缺乏冲突或悬念,观众可能在前 30 秒流失。",
            "suggestion": "在开场植入一个小悬念或冲突(如反常细节、未接电话),或直接从故事中段切入(In Medias Res)。",
        })

    # --- 优点(基于可观测事实)---
    if dialogues:
        avg_len = sum(len(l) for _, l, _ in dialogues) / len(dialogues)
        if avg_len <= 40:
            strengths.append("对白整体简洁,有节奏感")
    if len(scenes) > 1:
        strengths.append("场次划分清晰,便于拍摄排期")
    if re.search(r"第\s*\d+\s*[场幕景]", text):
        strengths.append("有明确的场景标记,结构意识好")
    if len(dialogues) >= 6:
        strengths.append("角色之间有足够的对话互动")
    if not strengths:
        strengths = ["已提交完整文本,具备进一步打磨的基础"]

    high = sum(1 for i in issues if i["severity"] == "高")
    mid = sum(1 for i in issues if i["severity"] == "中")
    low = sum(1 for i in issues if i["severity"] == "低")
    score = max(3, min(9, 8 - high * 2 - mid - low * 0.5))
    summary = (f"共发现 {len(issues)} 处可改进的问题(高 {high} / 中 {mid} / 低 {low})。"
               f"这是离线启发式检查,主要覆盖时间线、人物去向、对白长度与伏笔回收;"
               f"接入 API 后还可做动机、潜台词与节奏的深度审阅。")
    next_steps = "建议先处理「高/中」级别问题:补时间过渡与人物去向,再回收伏笔,最后逐句修剪对白。"
    return {
        "summary": summary, "score": round(score), "issues": issues[:8],
        "strengths": strengths[:3], "next_steps": next_steps,
        "production_risks": [], "genre_benchmark": "",
        "mode": "offline",
    }


async def review(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text
            if case_ctx:
                user_content += f"\n\n以下是检索到的参考资料（案例 / 场面模式，审阅时可借鉴其中经验与常见问题）：\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_REVIEW},
                 {"role": "user", "content": user_content[:9000]}], api_key=api_key)
            data = _normalize_review(data)
            data["mode"] = "online"
            if refs:
                data["references"] = refs
            return data
        except Exception as e:  # noqa: BLE001
            logger.warning("在线剧本检查失败(%s),回退离线", e)
    out = offline_review(text)
    if refs:
        out["references"] = refs
    return out


def _normalize_review(data: dict):
    out = {
        "summary": str(data.get("summary", "")),
        "score": max(0, min(10, int(data.get("score", 7) or 7))),
        "issues": [], "strengths": [], "next_steps": str(data.get("next_steps", "")),
    }
    for it in data.get("issues", []) or []:
        if not isinstance(it, dict):
            continue
        out["issues"].append({
            "type": str(it.get("type", "其他")),
            "severity": str(it.get("severity", "中")),
            "location": str(it.get("location", "全文")),
            "quote": str(it.get("quote", "")),
            "problem": str(it.get("problem", "")),
            "suggestion": str(it.get("suggestion", "")),
        })
    for s in data.get("strengths", []) or []:
        out["strengths"].append(str(s))
    risks = []
    for r in data.get("production_risks", []) or []:
        if isinstance(r, dict) and r.get("risk"):
            risks.append({
                "risk": str(r["risk"]),
                "severity": str(r.get("severity", "中")),
                "mitigation": str(r.get("mitigation", "")),
            })
    out["production_risks"] = risks[:4]
    out["genre_benchmark"] = str(data.get("genre_benchmark", ""))
    return out


# --------------------------------------------------------------------------
# 分镜建议 storyboard
# --------------------------------------------------------------------------
SHOT_TYPES = ["全景", "中景", "近景", "特写"]
ANGLES = ["平视", "过肩", "仰拍", "俯拍"]
MOVES = ["固定", "推", "稳定器跟随", "摇"]


def offline_storyboard(text: str, refs: list = None):
    """离线分镜：按场次从镜头模式库挑镜头，组成 master + coverage 的 shot list。"""
    import library

    infos = analyze_script(text)
    scene_lines_all = parse_scenes(text)
    shots, sid, scene_plan = [], 0, []
    role_queries = [
        ("全景", "建立镜头 establishing 交代空间"),
        ("过肩", "过肩 对话 双人 正反打"),
        ("近景", "近景 反应 情绪"),
        ("特写", "特写 细节 情绪 强调"),
        ("大特写", "插入镜头 微距 细节"),
    ]
    for info in infos[:4]:
        scene_text = f"{info['heading']} {info['synopsis']} {' '.join(info['cast'])}"
        scene_label = f"第{info['scene_no']}场 {info['location']}"
        scene_plan.append({
            "scene_no": info["scene_no"],
            "scene": scene_label,
            "coverage": ["master 全景", "OTS 双人过肩", "single A", "insert 细节"],
            "notes": "轴线保持在同一侧；先拍 master 再拍 singles",
        })
        idx = info["scene_no"] - 1
        body = "\n".join(scene_lines_all[idx]) if 0 <= idx < len(scene_lines_all) else ""
        dialogues = extract_dialogues(body)
        first_dlg = dialogues[0][1][:30] if dialogues else ""
        count = min(5, max(3, info["pages_eighths"] // 2 + 2))
        used = set()
        for j in range(count):
            sid += 1
            role, role_q = role_queries[j % len(role_queries)]
            pool = library.search_shots(f"{scene_text} {role_q}", k=8) or []
            p = next((x for x in pool if x.get("id") not in used), None)
            if p:
                used.add(p.get("id"))
            if p:
                shot = {
                    "id": sid, "scene_no": info["scene_no"], "scene": scene_label,
                    "shot_type": p.get("size", "中景"), "angle": p.get("angle", "平视"),
                    "movement": p.get("movement", "固定"), "lens": p.get("lens", "35mm"),
                    "duration": (p.get("duration_range") or "3-5s").split("-")[0] + "s",
                    "description": (p.get("example_use") or p.get("purpose", ""))[:90],
                    "dialogue": first_dlg if j == 2 else "",
                    "lighting": p.get("lighting", ""), "sound": p.get("sound", ""),
                    "purpose": p.get("purpose", ""), "transition": "切",
                }
            else:
                shot = {
                    "id": sid, "scene_no": info["scene_no"], "scene": scene_label,
                    "shot_type": SHOT_TYPES[j % len(SHOT_TYPES)], "angle": ANGLES[(info["scene_no"] + j) % len(ANGLES)],
                    "movement": "固定" if j == 0 else MOVES[(info["scene_no"] + j) % len(MOVES)],
                    "lens": "35mm", "duration": f"{3 + (j % 3) * 2}s",
                    "description": "建立空间关系与人物位置，注意构图留白与视线方向。",
                    "dialogue": first_dlg if j == 1 else "",
                    "lighting": "", "sound": "", "purpose": "建立空间", "transition": "切",
                }
            shots.append(shot)
    if not shots:  # 没有可解析的剧本 → 给一个通用示例
        shots = [
            {"id": 1, "scene_no": 1, "scene": "示例：开场", "shot_type": "全景", "angle": "平视",
             "movement": "固定", "lens": "24mm", "duration": "5s",
             "description": "交代环境与人物位置，画面四边留呼吸空间。", "dialogue": "",
             "lighting": "自然光为主，补一块反光板压暗背景", "sound": "环境声铺底",
             "purpose": "建立场景", "transition": "切"},
            {"id": 2, "scene_no": 1, "scene": "示例：开场", "shot_type": "中景", "angle": "过肩",
             "movement": "固定", "lens": "50mm", "duration": "4s",
             "description": "对话正反打，过肩机位建立空间关系。", "dialogue": "",
             "lighting": "主光 45° 侧打，辅光补暗部", "sound": "对白清晰，压低环境",
             "purpose": "建立人物关系", "transition": "切"},
            {"id": 3, "scene_no": 1, "scene": "示例：开场", "shot_type": "特写", "angle": "平视",
             "movement": "推", "lens": "85mm", "duration": "3s",
             "description": "推向面部，强调情绪转折。", "dialogue": "",
             "lighting": "眼神光 + 轮廓光分离背景", "sound": "音乐进入",
             "purpose": "点出情绪", "transition": "切"},
        ]

    note = "离线模式：镜头由镜头模式库按场次语义匹配；在线模式会逐场定制 coverage。"
    if refs:
        top = refs[0]
        note = f"借鉴案例{top['title']}：{'、'.join(top.get('storyboard_highlights', [])[:2])}"
    out = {
        "shots": shots[:16],
        "scene_plan": scene_plan,
        "coverage_notes": "保持 180 度轴线与视线匹配；景别递进 全景→中景→特写；越轴必须用移动镜头交代。",
        "mode": "offline",
        "note": note,
    }
    if refs:
        out["references"] = refs
    return out


async def storyboard(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:4000]
            if case_ctx:
                user_content += (
                    "\n\n参考资料包含视频片段与拍摄模式。将参考片段的镜头顺序、构图和节奏适配到用户的剧本或创意简报。"
                    "在 coverage_notes 中注明实际借鉴的样本标题与时间码，并说明借鉴方式。\n"
                    f"{case_ctx}"
                )
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_STORYBOARD},
                 {"role": "user", "content": user_content[:9000]}], api_key=api_key)
            shots = []
            for i, s in enumerate(data.get("shots", []) or []):
                if not isinstance(s, dict):
                    continue
                shots.append({
                    "id": int(s.get("id", i + 1) or i + 1),
                    "scene_no": int(s.get("scene_no", 0) or 0),
                    "scene": str(s.get("scene", "")),
                    "shot_type": str(s.get("shot_type", "中景")),
                    "angle": str(s.get("angle", "平视")),
                    "movement": str(s.get("movement", "固定")),
                    "lens": str(s.get("lens", "")),
                    "duration": str(s.get("duration", "4s")),
                    "description": str(s.get("description", "")),
                    "dialogue": str(s.get("dialogue", "")),
                    "lighting": str(s.get("lighting", "")),
                    "sound": str(s.get("sound", "")),
                    "purpose": str(s.get("purpose", "")),
                    "transition": str(s.get("transition", "")),
                })
            out = {
                "shots": shots,
                "scene_plan": data.get("scene_plan", []) or [],
                "coverage_notes": str(data.get("coverage_notes", "")),
                "mode": "online",
            }
            if refs:
                out["references"] = refs
            return out
        except Exception as e:  # noqa: BLE001
            logger.warning("在线分镜失败(%s),回退离线", e)
    return offline_storyboard(text, refs=refs)


# --------------------------------------------------------------------------
# 拍摄 Rundown（专业 stripboard 结构）
# --------------------------------------------------------------------------
INT_HINTS = ["内", "室", "屋内", "房间", "走廊", "电梯", "车内", "便利店", "咖啡", "办公室"]
EXT_HINTS = ["外", "街", "天台", "公园", "海滩", "马路", "门口", "广场", "屋顶", "山", "海"]
NIGHT_HINTS = ["夜", "晚", "凌晨", "深夜", "午夜"]
DUSK_HINTS = ["黄昏", "傍晚", "日落"]
DAWN_HINTS = ["清晨", "黎明", "日出"]
HEAVY_HINTS = ["动作", "追", "打斗", "爆炸", "雨", "水", "火", "动物", "儿童", "孩子", "人群", "特技", "航拍", "飞车"]


def _fmt_clock(minutes: int):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _scene_heading(lines, idx):
    raw = (lines[0] if lines else "").strip()
    raw = re.sub(r"^\s*(?:第\s*\d+\s*[场幕景]|scene\s*\d+)[\s:：\-—]*", "", raw, flags=re.I)
    return (raw or f"场景 {idx}")[:40]


def _scene_int_ext(heading, body):
    blob = f"{heading} {body[:120]}"
    if re.search(r"外景|EXT\b|室外|户外", blob, re.I):
        return "EXT"
    if re.search(r"内景|INT\b|室内|屋内", blob, re.I):
        return "INT"
    if any(k in heading for k in EXT_HINTS) and not any(k in heading for k in INT_HINTS):
        return "EXT"
    return "INT"


def _scene_day_night(heading, body):
    blob = f"{heading} {body[:120]}"
    if any(k in blob for k in NIGHT_HINTS):
        return "NIGHT"
    if any(k in blob for k in DUSK_HINTS):
        return "DUSK"
    if any(k in blob for k in DAWN_HINTS):
        return "DAWN"
    return "DAY"


def _scene_location(heading, int_ext):
    loc = re.sub(r"\b(INT/EXT|INT|EXT)\b|内景|外景", "", heading, flags=re.I)
    loc = re.sub(r"[（(]?\s*(日|夜|清晨|黄昏|傍晚|凌晨|深夜|白天|晚上|DAY|NIGHT|DUSK|DAWN)\s*[)）]?\s*$", "", loc, flags=re.I)
    loc = re.sub(r"^[\s\-—–:：|/]+|[\s\-—–:：|/]+$", "", loc)
    return loc[:24] or "待勘景"


def analyze_script(text: str):
    """把剧本拆成「可排期」的场次：页数（1/8）、预计拍摄分钟、内外景、日夜、演员。"""
    scenes = parse_scenes(text)
    if not scenes:
        scenes = [[text.strip()[:80] or "场景"]]
    infos = []
    for i, lines in enumerate(scenes, 1):
        body = "\n".join(lines)
        heading = _scene_heading(lines, i)
        # 剧情摘要去掉场次标题行，避免「第1场 便利店 夜」在通告单里重复出现
        body_lines = [l for l in lines if not SCENE_RE.match(l)]
        synopsis_text = " ".join(l.strip() for l in body_lines[:3] if l.strip())
        int_ext = _scene_int_ext(heading, body)
        day_night = _scene_day_night(heading, body)
        dialogues = extract_dialogues(body)
        cast = []
        for name, _, _ in dialogues:
            if name not in cast and len(cast) < 5:
                cast.append(name)
        action_lines = [
            l for l in lines
            if l.strip() and not DIALOGUE_RE.match(l) and not SCENE_RE.match(l)
        ]
        # 时长估算：对白 4s/行 + 动作 2s/行 + 10s 基础；1 页 ≈ 60s 成片
        duration = max(15, min(240, 10 + 4 * len(dialogues) + 2 * len(action_lines)))
        pages = max(1, min(12, round(duration / 60 * 8)))
        heavy = sum(1 for k in HEAVY_HINTS if k in body)
        factor = 1 + min(0.6, heavy * 0.12) + (0.15 if day_night == "NIGHT" else 0)
        minutes = max(30, min(240, round(pages / 8 * 75 * factor / 5) * 5))
        clean_heading = re.sub(
            r"[（(]?\s*(日|夜|清晨|黄昏|傍晚|凌晨|深夜|白天|晚上|DAY|NIGHT|DUSK|DAWN)\s*[)）]?\s*$",
            "", heading, flags=re.I,
        ).strip(" -—–:：|/")
        label = {"NIGHT": "夜", "DAY": "日", "DUSK": "黄昏", "DAWN": "清晨"}.get(day_night, day_night)
        infos.append({
            "scene_no": i,
            "int_ext": int_ext,
            "heading": f"{int_ext} {clean_heading or heading} - {label}",
            "synopsis": re.sub(r"\s+", " ", synopsis_text)[:60],
            "cast": cast,
            "day_night": day_night,
            "pages_eighths": pages,
            "est_minutes": minutes,
            "location": _scene_location(heading, int_ext),
            "heavy": heavy > 0,
        })
    return infos


def _build_stripboard(infos, topic, start=7 * 60 + 30, equip="摄影机、指向性话筒、灯光", day_label="Day 1"):
    """按真实通告单顺序排时间块：crew_call → setup → scene(s) → move/meal → wrap。"""
    blocks = []
    clock = start
    moves = meals = 0

    def add(kind, note, minutes, scene_no=None):
        nonlocal clock
        block = {"type": kind, "time": _fmt_clock(clock), "note": note, "est_minutes": minutes}
        if scene_no is not None:
            block["scene_no"] = scene_no
        blocks.append(block)
        clock += minutes
        return block

    add("crew_call", "集合、早餐、设备清点与电量检查", 30)
    add("cast_call", "演员化妆、服装与连戏确认", 30)
    add("setup", f"首个机位布光与测试（参考设备：{equip}）", 45)

    current_loc = None
    for info in infos:
        if current_loc is not None and info["location"] != current_loc:
            add("move", f"// COMPANY MOVE TO {info['location']} // 转场、停车与重新布线", 30)
            moves += 1
        current_loc = info["location"]
        synopsis = info["synopsis"][:24] + "…" if len(info["synopsis"]) > 24 else info["synopsis"]
        note = f"第{info['scene_no']}场 {info['heading']}" + (f"｜{synopsis}" if synopsis else "")
        add("scene", note, info["est_minutes"], info["scene_no"])
        elapsed = clock - start
        if meals == 0 and elapsed >= 5 * 60 + 30:
            add("meal", "// MEAL BREAK // 用餐与休息（不超过 1 小时）", 45)
            meals += 1

    add("wrap", "收工：素材双备份、清点设备、恢复场地", 30)

    total_minutes = sum(b["est_minutes"] for b in blocks)
    pages = sum(i["pages_eighths"] for i in infos)
    overflow = total_minutes > 11 * 60
    locations = []
    for info in infos:
        if not any(l["name"] == info["location"] for l in locations):
            locations.append({"name": info["location"], "int_ext": info["int_ext"], "notes": ""})
    cast_calls = []
    for info in infos:
        for name in info["cast"]:
            if not any(c["name"] == name for c in cast_calls):
                cast_calls.append({"name": name, "role": name, "call": _fmt_clock(start + 30), "notes": "化妆 30–45 分钟"})

    safety = []
    if any(i["day_night"] == "NIGHT" for i in infos):
        safety.append("夜戏：检查照明电缆走线与反光背心，注意电压负载")
    if any(i["heavy"] for i in infos):
        safety.append("高风险场次：特技/追车/动物须提前排练并明确安全区")

    notes = [
        "场次按「同一地点再日夜」排序，减少 company move",
        "每换机位预留 15–30 分钟布光；黄金时刻戏单独块",
    ]
    if overflow:
        notes.append(f"当日预计 {total_minutes} 分钟（约 {total_minutes / 60:.1f} 小时），超出 11 小时安全线，建议拆成两天")
    if sum(i["pages_eighths"] for i in infos) > 48:
        notes.append("单日页数超过 6 页（48/8），剧情片建议控制在 4–6 页")

    return {
        "day": day_label,
        "crew_call": _fmt_clock(start),
        "cast_call": _fmt_clock(start + 30),
        "wrap": _fmt_clock(clock),
        "locations": locations,
        "scenes": infos,
        "blocks": blocks,
        "totals": {
            "pages_eighths": pages,
            "shoot_minutes": total_minutes,
            "company_moves": moves,
            "meals": meals,
        },
        "cast_calls": cast_calls,
        "safety": safety,
        "notes": notes,
    }


def offline_rundown(text: str, refs: list = None):
    topic = _pick_topic(text)
    infos = analyze_script(text)
    ref_case = refs[0] if refs else None
    equip = "、".join(ref_case["equipment"][:4]) if ref_case and ref_case.get("equipment") else "摄影机、指向性话筒、灯光"
    day = _build_stripboard(infos[:8], topic, equip=equip)
    # 兼容旧前端：把 blocks 映射成「时间 / 项目」列表
    items = [{
        "time": b["time"], "item": b["note"], "location": "", "cast": "", "equipment": "",
        "notes": f"{b['est_minutes']} 分钟",
    } for b in day["blocks"]]
    out = {
        "title": f"《{topic}》拍摄通告单",
        "date": "待定",
        "mode": "offline",
        "scenes": day["scenes"][:8],
        **day,
        "items": items,
    }
    if len(infos) > 8:
        out["notes"].append(f"剧本共 {len(infos)} 场，本通告单只排前 8 场；其余请用「日程规划」拆天")
    if refs:
        out["references"] = refs
    return out


def _normalize_stripboard(data: dict, fallback_title="拍摄通告单"):
    """把模型返回的 stripboard 归一化，并用 blocks/scenes 重算 totals，保证前后端一致。"""
    def as_int(value, default=0, lo=0, hi=10_000):
        try:
            return max(lo, min(hi, int(round(float(value)))))
        except (TypeError, ValueError):
            return default

    scenes = []
    for i, s in enumerate(data.get("scenes", []) or []):
        if not isinstance(s, dict):
            continue
        cast = s.get("cast") or []
        if isinstance(cast, str):
            cast = [c.strip() for c in re.split(r"[,，、/]", cast) if c.strip()]
        scenes.append({
            "scene_no": as_int(s.get("scene_no", i + 1), i + 1, 1, 999),
            "int_ext": str(s.get("int_ext", "INT")),
            "heading": str(s.get("heading", "")),
            "synopsis": str(s.get("synopsis", "")),
            "cast": [str(c) for c in cast][:6],
            "day_night": str(s.get("day_night", "DAY")),
            "pages_eighths": as_int(s.get("pages_eighths", 1), 1, 1, 12),
            "est_minutes": as_int(s.get("est_minutes", 45), 45, 5, 480),
            "location": str(s.get("location", "")),
            "notes": str(s.get("notes", "")),
        })

    allowed = {"crew_call", "cast_call", "setup", "scene", "move", "meal", "wrap", "buffer"}
    blocks = []
    for b in data.get("blocks", []) or []:
        if not isinstance(b, dict):
            continue
        kind = str(b.get("type", "scene"))
        if kind not in allowed:
            kind = "scene"
        block = {
            "type": kind,
            "time": str(b.get("time", "")),
            "note": str(b.get("note", "")),
            "est_minutes": as_int(b.get("est_minutes", 0), 0, 0, 720),
        }
        if b.get("scene_no") is not None:
            block["scene_no"] = as_int(b.get("scene_no"), 0, 0, 999)
        blocks.append(block)

    totals = {
        "pages_eighths": sum(s["pages_eighths"] for s in scenes),
        "shoot_minutes": sum(b["est_minutes"] for b in blocks),
        "company_moves": sum(1 for b in blocks if b["type"] == "move"),
        "meals": sum(1 for b in blocks if b["type"] == "meal"),
    }
    locations = []
    for loc in data.get("locations", []) or []:
        if isinstance(loc, dict) and loc.get("name"):
            locations.append({"name": str(loc["name"]), "int_ext": str(loc.get("int_ext", "")),
                              "notes": str(loc.get("notes", ""))})
    if not locations:
        for s in scenes:
            if s["location"] and not any(l["name"] == s["location"] for l in locations):
                locations.append({"name": s["location"], "int_ext": s["int_ext"], "notes": ""})

    cast_calls = []
    for c in data.get("cast_calls", []) or []:
        if isinstance(c, dict) and c.get("name"):
            cast_calls.append({"name": str(c["name"]), "role": str(c.get("role", "")),
                               "call": str(c.get("call", "")), "notes": str(c.get("notes", ""))})

    times = [b["time"] for b in blocks if re.fullmatch(r"\d{1,2}:\d{2}", b["time"])]
    return {
        "title": str(data.get("title", fallback_title)),
        "date": str(data.get("date", "待定")),
        "day": str(data.get("day", "Day 1")),
        "crew_call": str(data.get("crew_call", times[0] if times else "07:30")),
        "cast_call": str(data.get("cast_call", "08:30")),
        "wrap": str(data.get("wrap", times[-1] if times else "19:30")),
        "locations": locations,
        "scenes": scenes,
        "blocks": blocks,
        "totals": totals,
        "cast_calls": cast_calls,
        "safety": [str(x) for x in (data.get("safety") or [])][:5],
        "notes": [str(x) for x in (data.get("notes") or [])][:5],
    }


async def rundown(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:4000]
            if case_ctx:
                user_content += f"\n\n参考资料（检索所得：案例 / 场面模式 / 通告单模板，请借鉴结构但必须适配用户剧本）：\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_RUNDOWN},
                 {"role": "user", "content": user_content[:9000]}], api_key=api_key)
            day = _normalize_stripboard(data)
            day["mode"] = "online"
            if refs:
                day["references"] = refs
            return day
        except Exception as e:  # noqa: BLE001
            logger.warning("在线 rundown 失败(%s),回退离线", e)
    return offline_rundown(text, refs=refs)


# --------------------------------------------------------------------------
# 日程规划 schedule
# --------------------------------------------------------------------------
def _pack_days(infos, days):
    """按地点聚类 + 页数预算（剧情片 6 页/天）把场次分到各天。"""
    budget = 48  # 6 页 = 48/8
    groups, cur, cur_pages, cur_locs = [], [], 0, set()
    for info in infos:
        new_loc = info["location"] not in cur_locs
        if cur and (cur_pages + info["pages_eighths"] > budget or (new_loc and cur_pages >= 24)):
            groups.append(cur)
            cur, cur_pages, cur_locs = [], 0, set()
        cur.append(info)
        cur_pages += info["pages_eighths"]
        cur_locs.add(info["location"])
    if cur:
        groups.append(cur)
    # 天数是下限：不够就继续拆，避免一天塞太多
    while len(groups) < days and any(len(g) > 1 for g in groups):
        idx = max(range(len(groups)), key=lambda i: len(groups[i]))
        group = groups.pop(idx)
        mid = len(group) // 2
        groups[idx:idx] = [group[:mid], group[mid:]]
    return groups


def offline_schedule(text: str, days: int = 2, refs: list = None):
    topic = _pick_topic(text)
    infos = analyze_script(text)
    total_minutes = sum(i["est_minutes"] for i in infos)
    needed = max(1, math.ceil(total_minutes / (9 * 60)))  # 每天有效拍摄约 9 小时
    effective_days = max(1, min(max(1, days), needed))
    groups = _pack_days(infos, effective_days)
    out_days, cast_days, risks = [], {}, []

    for d, group in enumerate(groups, 1):
        night = sum(1 for i in group if i["day_night"] == "NIGHT")
        ext = sum(1 for i in group if i["int_ext"] == "EXT")
        theme = "夜戏集中" if night * 2 > len(group) else ("外景为主" if ext * 2 > len(group) else "内景为主")
        day = _build_stripboard(group, topic, start=8 * 60, day_label=f"Day {d}")
        day["theme"] = theme
        day["date"] = "待定"
        day["location"] = "、".join(loc["name"] for loc in day["locations"][:3])
        day["tips"] = []
        if any(i["day_night"] in ("DUSK", "DAWN") for i in group):
            day["tips"].append("黄金时刻约 20 分钟：提前 40 分钟布好机位与反光板")
        if night:
            day["tips"].append("夜戏先拍全景定空间，再拍特写；注意遮光与邻居噪音投诉")
        if day["totals"]["company_moves"]:
            day["tips"].append(f"当日 {day['totals']['company_moves']} 次 company move，按 30 分钟/次计")
        if d == len(groups):
            day["tips"].append("最后一天留 1–2 小时补拍 buffer，不要排满")
        day["tasks"] = [{"time": b["time"], "task": b["note"], "location": "", "notes": f"{b['est_minutes']} 分钟"}
                        for b in day["blocks"]]
        out_days.append(day)

        for info in group:
            for name in info["cast"]:
                cast_days.setdefault(name, set()).add(d)
        if ext:
            risks.append({"risk": f"Day {d} 有外景，遇雨需改期", "mitigation": "预留内景 cover set 或备选日"})

    strategy = (
        f"{len(infos)} 场 / {sum(i['pages_eighths'] for i in infos)}/8 页，按地点聚类拆成 {len(out_days)} 天；"
        "同地点连续拍、日夜分块，最后一天留补拍缓冲。"
    )
    out = {
        "title": f"《{topic}》拍摄日程",
        "strategy": strategy,
        "mode": "offline",
        "days": out_days,
        "cast_schedule": [{"name": n, "days": sorted(ds), "notes": ""} for n, ds in cast_days.items()],
        "risks": risks[:4],
    }
    if refs:
        out["references"] = refs
    return out


async def schedule(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:4000]
            if case_ctx:
                user_content += f"\n\n参考资料（检索所得：案例 / 场面模式 / 通告单模板，请借鉴排期原则但必须适配用户项目）：\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_SCHEDULE},
                 {"role": "user", "content": user_content[:9000]}], api_key=api_key)
            out_days = []
            for i, d in enumerate(data.get("days", []) or []):
                if not isinstance(d, dict):
                    continue
                day = _normalize_stripboard({
                    "title": d.get("theme", ""),
                    "day": str(d.get("day", f"Day {i + 1}")),
                    "date": d.get("date", "待定"),
                    "crew_call": d.get("call", "08:00"),
                    "cast_call": d.get("cast_call", d.get("call", "08:00")),
                    "wrap": d.get("wrap", "19:00"),
                    "scenes": d.get("scenes", []),
                    "blocks": d.get("blocks", []),
                    "locations": d.get("locations", []),
                    "cast_calls": d.get("cast_calls", []),
                })
                day["theme"] = str(d.get("theme", ""))
                day["date"] = str(d.get("date", "待定"))
                day["location"] = str(d.get("location", ""))
                tips = d.get("tips") or ([d["tip"]] if d.get("tip") else [])
                day["tips"] = [str(t) for t in tips][:4]
                day["tasks"] = [{"time": b["time"], "task": b["note"],
                                 "location": "", "notes": f"{b['est_minutes']} 分钟"}
                                for b in day["blocks"]]
                out_days.append(day)
            return {
                "title": str(data.get("title", "拍摄日程")),
                "strategy": str(data.get("strategy", "")),
                "days": out_days,
                "cast_schedule": data.get("cast_schedule", []) or [],
                "risks": data.get("risks", []) or [],
                "mode": "online",
                **({"references": refs} if refs else {}),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("在线日程失败(%s),回退离线", e)
    return offline_schedule(text, refs=refs)


# --------------------------------------------------------------------------
# 灵感激发 inspiration
# --------------------------------------------------------------------------
IDEA_BANK = [
    {"title": "最后一班渡轮", "genre": "爱情 / 奇幻", "logline": "每天坐尾班渡轮回家的女孩发现,船上总有一个只有她能看见的男人,而渡轮即将停航。",
     "hook": "凌晨的码头,女孩数着渡轮上的乘客,发现比登船时多了一个人。", "twist": "男人是几十年前坠海的水手,他等的不是船,是女孩归还的一枚铜扣。"},
    {"title": "换脸滤镜", "genre": "悬疑 / 惊悚", "logline": "一个滤镜能让人看到陌生人“未来的脸”,大学生用它约会时,看到下一个约会对象的脸变成了自己的遗照。",
     "hook": "手机屏幕里,刚认识的男人笑着,而他的脸在滤镜里是灰白色的。", "twist": "滤镜显示的不是死亡预告,而是“你伤害过的人”。"},
    {"title": "外卖员的最后一单", "genre": "剧情 / 动作", "logline": "深夜送外卖的小哥接到一单送往废弃医院的订单,取餐人声称“你送的不是饭,是赎金”。",
     "hook": "订单备注只有一行字:别打开保温箱。", "twist": "保温箱里是一颗移植心脏,而收件人正是多年前害死他父亲的人。"},
    {"title": "妈妈的短视频", "genre": "亲情 / 喜剧", "logline": "为当网红,大学生偷拍“改造土味老妈”,视频爆红后才发现妈妈早就知道,一直在配合他演戏。",
     "hook": "妈妈对着镜头说:“儿子,这条拍的素材够剪三集吗?”", "twist": "妈妈的账号粉丝是他的十倍,她只是想陪儿子做一次他喜欢的事。"},
    {"title": "停尸间的对讲机", "genre": "恐怖 / 温情", "logline": "值夜班的实习保安捡到一台只会传出自己呼吸声的对讲机,而回应他的声音,来自三天前的自己。",
     "hook": "凌晨 3 点,对讲机突然响起:“别去三号停尸间,求你了。”", "twist": "三号停尸间躺着的是他自己——对讲机是未来发出的警告,他必须改变当晚会发生的事。"},
    {"title": "全班倒数第一", "genre": "校园 / 科幻", "logline": "学渣偶然发现自己能听到别人“心里的分数”,他发现全校第一的学霸内心分数是 0,因为那副身体不属于他。",
     "hook": "考场上,学霸回头对他笑了一下,而他听到:“帮帮我,我快撑不住了。”", "twist": "学霸是几十年前失踪的学生,被人用分数“续命”困在了考场循环里。"},
    {"title": "相亲直播", "genre": "爱情 / 讽刺", "logline": "被家人逼婚的程序员给自己写了个相亲 AI 助手,结果 AI 和女方的 AI 先坠入爱河,还商量着要“私奔”。",
     "hook": "餐厅里,两个真人尴尬喝汤,手机屏幕上的两个 AI 已经聊到蜜月地点。", "twist": "女方的“AI”其实是真人配音——她也在演,而且比他先笑场。"},
    {"title": "天台上的钢琴", "genre": "音乐 / 剧情", "logline": "失聪的调音师每天去天台“调”一架走音的破钢琴,全楼的人以为他疯了,直到暴雨夜那架钢琴自己弹出了一首完整的曲子。",
     "hook": "他摸上琴键:“你今晚想弹哪首?”", "twist": "钢琴里藏着一封 20 年前没寄出的情书,收信人就是楼下每天骂他的房东奶奶。"},
]


IDEA_EXTRAS = {
    "最后一班渡轮": {
        "structure": ["建置：女孩每晚坐尾班渡轮，注意到多出的乘客", "升级：她开始数人数，只有她能看见他", "转折：渡轮公司宣布停航", "收尾：她归还铜扣，他终于下船"],
        "reference_patterns": ["密闭空间里的陌生人（《迷失东京》式距离感）", "重复仪式建立默契"],
        "visual_motif": "铜扣 / 船票：每次特写都比上次更旧",
        "sound_idea": "引擎低频贯穿全片，结尾停航时突然安静",
        "budget_note": "夜渡轮实拍 2 晚，2 名演员，无特效；用真实航班时刻表卡时间",
    },
    "换脸滤镜": {
        "structure": ["建置：主角用滤镜约会，效果灵验", "升级：他看到熟人脸变灰白", "转折：滤镜照出他自己的遗照", "收尾：他删掉 App，最后一帧滤镜自动打开"],
        "reference_patterns": ["screen-life / 手机屏幕叙事", "诅咒道具的规则逐步揭示"],
        "visual_motif": "手机屏幕的冷光与夜店暖光的反差",
        "sound_idea": "滤镜开启时的电子提示音，越听越刺耳",
        "budget_note": "全部手机 POV + 实景夜店，1 名演员分饰多角",
    },
    "外卖员的最后一单": {
        "structure": ["建置：深夜接单，备注诡异", "升级：医院走廊无人，保温箱发出声音", "转折：收件人现身，认出彼此", "收尾：他把心脏送进手术室，自己走进雨里"],
        "reference_patterns": ["追逐片的空间压缩：走廊/楼梯/电梯", "单夜结构（one-night story）"],
        "visual_motif": "保温箱的红色指示灯",
        "sound_idea": "心跳声从保温箱里传出，逐渐与配乐节拍同步",
        "budget_note": "废弃医院 1 晚 + 电动车跟拍；用手机稳定器代替轨道",
    },
    "妈妈的短视频": {
        "structure": ["建置：儿子偷拍妈妈改造计划", "升级：视频爆红，妈妈越来越配合", "转折：他发现妈妈早就知道", "收尾：两人合拍最后一条，不剪"],
        "reference_patterns": ["伪纪录片 / vlog 视角", "喜剧靠反应镜头而非台词"],
        "visual_motif": "竖屏构图与横屏电影感的切换",
        "sound_idea": "手机提示音当作节拍器",
        "budget_note": "家里实景，手机 + 一盏窗光；妈妈角色找素人演出更真",
    },
    "停尸间的对讲机": {
        "structure": ["建置：保安捡到对讲机", "升级：对讲机预言他的行动", "转折：三号停尸间躺着他自己", "收尾：他打破循环，代价是失去一段记忆"],
        "reference_patterns": ["时间循环（《恐怖游轮》式）", "单一场景靠声音吓人"],
        "visual_motif": "走廊尽头的绿灯",
        "sound_idea": "对讲机的电流噪声代替 jump scare",
        "budget_note": "一个停尸间布景 2 晚，4 个灯位，靠声音与剪辑制造恐怖",
    },
    "全班倒数第一": {
        "structure": ["建置：他听见别人的心算分数", "升级：学霸的分数是 0", "转折：学霸求他帮忙", "收尾：他故意考砸，打破续命规则"],
        "reference_patterns": ["校园类型 + 超能力规则", "考试场景的重复变奏"],
        "visual_motif": "分数以字幕浮在人物头顶",
        "sound_idea": "翻卷子声被放大成心跳",
        "budget_note": "一间教室 + 走廊；超能力用字幕与音效实现，零特效",
    },
    "相亲直播": {
        "structure": ["建置：两个 AI 代聊", "升级：AI 先恋爱了", "转折：女方也是真人配音", "收尾：两人关掉手机，真人重新自我介绍"],
        "reference_patterns": ["双线叙事：真人尴尬 / AI 热烈", "喜剧靠信息差"],
        "visual_motif": "手机屏幕与餐桌的来回切",
        "sound_idea": "AI 语音的机械音逐渐变得有感情",
        "budget_note": "一间餐厅 + 两部手机；AI 语音用 TTS，成本几乎为零",
    },
    "天台上的钢琴": {
        "structure": ["建置：失聪调音师每天调琴", "升级：邻居投诉，房东要搬走钢琴", "转折：暴雨夜钢琴自弹", "收尾：情书交还，钢琴被留下"],
        "reference_patterns": ["音乐驱动叙事", "一场景一空间的短片结构"],
        "visual_motif": "琴键上的雨滴",
        "sound_idea": "全片主观听感：失聪者的低频世界，结尾突然听见完整音色",
        "budget_note": "一栋天台 + 一架旧钢琴；雨戏用消防水管，1 晚拍完",
    },
}


def _concepts_from_scenes(topic: str, limit: int = 3):
    """离线灵感兜底：用户给的题材在灵感库里没有时，用场面模式库组合概念。"""
    import library

    out = []
    for scene in library.search_scenes(topic, k=limit) or []:
        beats = scene.get("beat_structure", []) or []
        out.append({
            "title": scene.get("name_zh", "未命名概念"),
            "genre": " / ".join(scene.get("genre", [])) or "剧情",
            "logline": scene.get("conflict", ""),
            "hook": beats[0] if beats else "",
            "twist": scene.get("fix", ""),
            "structure": beats,
            "reference_patterns": [f"{scene.get('name_zh', '')}：{scene.get('staging', '')}"],
            "visual_motif": scene.get("lighting", ""),
            "sound_idea": scene.get("sound", ""),
            "budget_note": f"{scene.get('page_eighths', '?')}/8 页，预计拍摄 {scene.get('shoot_minutes', '?')} 分钟",
        })
    return out


MOOD_HINTS = {
    "孤独": ["孤独", "寂寞", "一个人", "疏离", "alienation", "lonely"],
    "浪漫": ["浪漫", "暗恋", "爱情", "心动", "暧昧", "romance"],
    "温暖": ["温暖", "治愈", "亲情", "家庭", "友情", "warm"],
    "压抑": ["压抑", "窒息", "绝望", "沉重", "oppressive"],
    "荒诞": ["荒诞", "黑色幽默", "讽刺", "离谱", "absurd"],
    "紧张": ["紧张", "悬疑", "惊悚", "焦灼", "thriller", "tension"],
    "心碎": ["心碎", "失恋", "遗憾", "告别", "heartbreak"],
    "怀旧": ["怀旧", "回忆", "年代", "nostalgia"],
    "恐惧": ["恐惧", "恐怖", "害怕", "horror"],
    "敬畏": ["敬畏", "史诗", "宏大", "震撼", "epic"],
}


def _mood_groups(topic: str, per_mood: int = 2, max_moods: int = 6):
    """把「剧本 + 原片」库和个人灵感库按情绪分组，供同一主题下的不同情绪参考。"""
    import case_store
    import personal_library

    pool = []
    for c in case_store.load_cases():
        pool.append({
            "title": c["title"], "moods": c.get("tags", []), "cover": c.get("cover", ""),
            "url": c.get("url", ""), "duration": c.get("duration", ""),
            "script_page": c.get("script_page", ""), "script_pdf": c.get("script_pdf", ""),
            "frames": c.get("frames", []),
            "play": (c.get("stat") or {}).get("view", 0),
            "source": c.get("source", ""), "personal": False,
        })
    for f in personal_library.list_films():
        pool.append({
            "title": f.get("title", ""), "moods": f.get("moods", []), "cover": f.get("cover", ""),
            "url": f.get("url", ""), "duration": f.get("duration", ""),
            "script_page": "", "script_pdf": "", "frames": f.get("frames", []), "play": 0,
            "source": "个人灵感库", "personal": True,
        })

    low = (topic or "").lower()
    scores = {}
    for mood, words in MOOD_HINTS.items():
        score = 0.0
        if mood in (topic or ""):
            score += 5
        score += sum(2 for w in words if w.lower() in low)
        score += min(3, sum(1 for f in pool if mood in f.get("moods", [])))
        scores[mood] = score

    groups = []
    for mood in sorted(scores, key=lambda m: -scores[m]):
        films = [f for f in pool if mood in f.get("moods", [])]
        if not films:
            continue
        films.sort(key=lambda f: (f["personal"], f["play"]), reverse=True)
        groups.append({"mood": mood, "films": films[:per_mood]})
        if len(groups) >= max_moods:
            break
    return groups


def _attach_stills(concept: dict, limit: int = 2):
    """给灵感概念配真实短片的静帧（Bilibili 封面）+ 原片链接，避免空想。"""
    import case_store

    query = " ".join([
        str(concept.get("genre", "")), str(concept.get("title", "")),
        str(concept.get("visual_motif", "")), " ".join(concept.get("reference_patterns", []) or []),
    ]).strip()
    try:
        hits = case_store.search_cases(query or "短片", k=limit + 1)
    except Exception:  # noqa: BLE001
        hits = []
    concept["stills"] = [
        {"title": h["title"], "cover": h.get("cover", ""), "url": h.get("url", ""),
         "duration": h.get("duration", ""), "source": "Bilibili"}
        for h in hits[:limit] if h.get("cover")
    ]
    return concept


def offline_inspiration(topic: str = "", refs: list = None):
    pool = list(IDEA_BANK)
    # 题材近义词:按用户关键词优先给出同题材概念,不足 3 个时用随机补足
    SYNONYMS = {
        "恐怖": ["恐怖", "惊悚", "悬疑"],
        "爱情": ["爱情", "恋爱", "感情"],
        "校园": ["校园", "学校", "学生", "青春"],
        "喜剧": ["喜剧", "搞笑", "幽默"],
        "音乐": ["音乐"],
        "剧情": ["剧情"],
    }
    kw = topic or ""
    matched = [c for c in pool if any(syn in kw for syn in SYNONYMS.get(c["genre"].split("/")[0].strip(), [c["genre"].split("/")[0].strip()]))]
    rng = random.Random(topic + str(random.random()))
    rest = [c for c in pool if c not in matched]
    if not matched and topic:
        picks = _concepts_from_scenes(topic)
        if len(picks) < 3:
            used = {c["title"] for c in picks}
            picks += rng.sample([c for c in IDEA_BANK if c["title"] not in used], 3 - len(picks))
    else:
        picks = (matched + rng.sample(rest, max(0, 3 - len(matched))))[:3]
        rng.shuffle(picks)
    picks = [{**c, **IDEA_EXTRAS.get(c["title"], {})} for c in picks]
    picks = [_attach_stills(c) for c in picks]
    out = {"concepts": picks, "moods": _mood_groups(topic), "mode": "offline",
           "note": f"离线模式从灵感库中抽取了 3 个示例{(f'(主题:「{topic}」)' if topic else '')}——接入 API 后可按你的关键词定制生成。"}
    if refs:
        out["references"] = refs
    return out


async def inspiration(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:2000] or "随机"
            if case_ctx:
                user_content += f"\n\n参考资料（案例 / 场面模式 / 视频样本节奏，可作为灵感参照）：\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_INSPIRATION},
                 {"role": "user", "content": user_content[:9000]}], api_key=api_key)
            concepts = []
            for c in data.get("concepts", []) or []:
                if not isinstance(c, dict):
                    continue
                concept = {
                    "title": str(c.get("title", "")), "genre": str(c.get("genre", "")),
                    "logline": str(c.get("logline", "")), "hook": str(c.get("hook", "")),
                    "twist": str(c.get("twist", "")),
                    "structure": [str(x) for x in (c.get("structure") or [])][:5],
                    "reference_patterns": [str(x) for x in (c.get("reference_patterns") or [])][:3],
                    "visual_motif": str(c.get("visual_motif", "")),
                    "sound_idea": str(c.get("sound_idea", "")),
                    "budget_note": str(c.get("budget_note", "")),
                }
                concepts.append(_attach_stills(concept))
            return {"concepts": concepts, "moods": _mood_groups(text),
                    "mode": "online", **({"references": refs} if refs else {})}
        except Exception as e:  # noqa: BLE001
            logger.warning("在线灵感失败(%s),回退离线", e)
    return offline_inspiration(_pick_topic(text) if text else "", refs=refs)


# --------------------------------------------------------------------------
# 参考案例 cases(模型自主调用 search_cases 工具)
# --------------------------------------------------------------------------
async def cases_tool(message: str, api_key: str = None):
    import case_store

    query = message[:80] or "影视短片"
    if llm.available(api_key):
        try:
            msgs = [{"role": "system", "content": prompts.PROMPT_CASES},
                    {"role": "user", "content": message[:2000] or "请帮我找一些参考案例"}]
            text, steps = await llm.chat_with_tools(msgs, api_key=api_key)
            hits = case_store.search_cases(query, k=3)
            if not any(s["tool"] == "search_cases" for s in steps):
                steps.append({"tool": "search_cases", "query": query})
            return {"text": text, "cases": hits, "steps": steps, "mode": "online"}
        except Exception as e:  # noqa: BLE001
            logger.warning("在线案例检索失败(%s),回退离线", e)
    hits = case_store.search_cases(query, k=3)
    titles = "、".join(c["title"] for c in hits)
    text = (f"为你找到 {len(hits)} 部相关真实短片:{titles}。"
            "每条都附 Bilibili 来源链接与封面,可以直接点开看原片;"
            "需要的话告诉我你的想法,我帮你对照这些片子做风格/结构上的借鉴。(离线演示模式)")
    return {"text": text, "cases": hits, "steps": [{"tool": "search_cases", "query": query}], "mode": "offline"}


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------
def _build_context(tool: str, message: str):
    """为创作类工具组装检索上下文：案例 + 场面模式 + 镜头模式 + 通告单模板。"""
    import case_store
    import library

    parts, refs = [], []
    try:
        ctx, refs = case_store.cases_context(message, k=2)
        if ctx:
            parts.append(ctx)
    except Exception as e:  # noqa: BLE001
        logger.warning("案例检索失败: %s", e)
    try:
        if tool in ("review", "storyboard", "inspiration"):
            parts.extend(library.scene_to_text(s) for s in library.search_scenes(message, k=2))
        if tool == "storyboard":
            parts.extend(library.shot_to_text(s) for s in library.search_shots(message, k=3))
        if tool in ("rundown", "schedule"):
            parts.extend(library.template_to_text(t) for t in library.search_templates(message, k=1))
            parts.extend(library.scene_to_text(s) for s in library.search_scenes(message, k=2))
    except Exception as e:  # noqa: BLE001
        logger.warning("资料库检索失败: %s", e)
    if tool in ("storyboard", "inspiration"):
        samples = sample_search.search_segments(message[:4000], k=2)
        if samples:
            parts.insert(0, "【视频片段】\n" + sample_search.segment_context(samples))
            refs.extend({**hit, "id": f"{hit['video_id']}:{hit['start']}",
                         "type": "Video sample", "logline": hit["description"]} for hit in samples)
    return "\n\n".join(p for p in parts if p), refs


async def run_tool(tool: str, message: str, api_key: str = None):
    if tool == "cases":
        return await cases_tool(message, api_key)
    # 创作类工具先检索资料（案例/场面/镜头/通告单），注入提示词或附到结果
    ctx, refs = "", []
    if tool in ("review", "storyboard", "rundown", "schedule", "inspiration"):
        ctx, refs = await asyncio.to_thread(_build_context, tool, message)
    if tool == "review":
        return await review(message, api_key, ctx, refs)
    if tool == "storyboard":
        return await storyboard(message, api_key, ctx, refs)
    if tool == "rundown":
        return await rundown(message, api_key, ctx, refs)
    if tool == "schedule":
        return await schedule(message, api_key, ctx, refs)
    if tool == "inspiration":
        return await inspiration(message, api_key, ctx, refs)
    raise ValueError(f"未知工具: {tool}")


def tool_labels():
    return {
        "review": "剧本检查",
        "storyboard": "分镜建议",
        "rundown": "拍摄 Rundown",
        "schedule": "日程规划",
        "inspiration": "灵感激发",
        "cases": "参考案例",
    }
