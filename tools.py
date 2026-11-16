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
    """返回 tool 名:review / storyboard / rundown / schedule / inspiration / None(知识问答)。

    模糊识别：用户说「帮我想一个关于香港的短片」「写个香港的TVC剧本」也能猜中。
    """
    msg = (message or "").strip()
    if not msg:
        return None
    tool, _kind, _idea = guess_intent(msg)
    if tool:
        return tool
    # 兜底：粘贴了长剧本 → 剧本检查
    if len(msg) > 150 and (re.search(r"第\s*\d+\s*[场幕景]", msg) or re.search(r"scene\s*\d+", msg, re.I)):
        return "review"
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
            user_content += lang_hint()
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


async def inspiration(text: str, api_key: str = None, case_ctx: str = "", refs: list = None,
                      catalog_ctx: str = ""):
    if llm.available(api_key):
        try:
            user_content = text[:2000] or "随机"
            if case_ctx:
                user_content += f"\n\n参考资料（案例 / 场面模式 / 视频样本节奏，可作为灵感参照）：\n{case_ctx}"
            if catalog_ctx:
                user_content += "\n\n" + catalog_ctx
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
        samples = sample_search.search_segments(message[:4000])
        if samples:
            parts.insert(0, "【视频片段】\n" + sample_search.segment_context(samples))
            refs.extend({**hit, "id": f"{hit['video_id']}:{hit['start']}",
                         "type": "Video sample", "logline": hit["description"]} for hit in samples)
    return "\n\n".join(p for p in parts if p), refs


# --------------------------------------------------------------------------
# 找灵感 v2：先选题材（划库）→ 只在对应库里找片 → 风格 / 主题 / 契合电影
# --------------------------------------------------------------------------
KIND_CHOICES = ["电影", "电视剧", "长片", "短片", "竖屏短剧",
                "广告/TVC", "教程/产品演示", "Vlog/美食", "动画"]
_KIND_PREFIX = re.compile(r"^\s*【题材[:：]\s*([^】]{1,16})】\s*", re.S)

KIND_GUIDE = {
    "inspiration": {
        "电影": "院线长片的气质：完整世界观、人物弧光、长片体量；主题要像一个能撑 100 分钟的故事。",
        "电视剧": "剧集气质：单集 45 分钟、连续人物弧光、集末钩子；主题要有可持续的关系线。",
        "长片": "独立/艺术/纪录长片：真实人物、观察式、作者表达；主题要落在真实处境上。",
        "短片": "短片气质：6-15 分钟、一个概念/一个情绪转折；主题必须小而准。",
        "竖屏短剧": "竖屏短剧：1-2 分钟/集、3 秒进冲突、强钩子、强反转；主题要能拆成很多小爽点。",
        "广告/TVC": "广告/TVC：15/30/60 秒；必须围绕「产品/品牌 + 目标人群 + 一个洞察 + 视觉钩子 + 一句 slogan」来构思，主题是广告创意方向，不是剧情短片。",
        "教程/产品演示": "教程/产品演示：围绕「功能 → 使用场景 → 步骤 → 结果」组织，主题是演示主线。",
        "Vlog/美食": "Vlog/美食：真实体验/制作流程 + 人物状态；主题是一段可拍的生活切片。",
        "动画": "动画：风格化世界观/无对白叙事/视觉比喻；主题要能用画面和动作讲完。",
    },
    "script": {
        "电影": "写标准电影剧本：场号 + 内/外景 + 地点 + 时间；动作现在时；角色名单独一行、对白在其下；全片 12-20 场。",
        "电视剧": "写单集电视剧剧本：场次标题格式同电影，单集 40-50 分钟，集末留钩子。",
        "长片": "写纪录片/艺术长片脚本：场次 + 观察段落 + 访谈/旁白提示，不用虚构对白。",
        "短片": "写 6-10 分钟短片剧本：场次标题格式同电影，10-14 场，结尾有反转或留白。",
        "竖屏短剧": "写单集竖屏短剧剧本：1-2 分钟、3 秒进冲突、台词短、每 15 秒一个钩子；用「第1集」标注。",
        "广告/TVC": "写广告脚本表，不是电影剧本：列「镜头/时长/画面/旁白或台词/字幕/音效」，总时长 30 秒（可附 15 秒版），最后给一句 slogan；必须写清产品与目标人群。",
        "教程/产品演示": "写产品演示脚本：分步骤（步骤名 + 画面 + 口播 + 屏幕提示），总时长 60-180 秒。",
        "Vlog/美食": "写 Vlog 脚本：分段落（开场/过程/细节/收尾），每段给画面、旁白、环境声与转场。",
        "动画": "写动画短片剧本：场次标题 + 画面动作描述 + 必要旁白；可以无对白，强调视觉叙事。",
    },
}

KIND_ALIASES = [
    ("廣告/TVC", "广告/TVC"), ("广告/TVC", "广告/TVC"), ("TVC", "广告/TVC"), ("tvc", "广告/TVC"),
    ("广告片", "广告/TVC"), ("廣告片", "广告/TVC"), ("广告", "广告/TVC"), ("廣告", "广告/TVC"),
    ("教程", "教程/产品演示"), ("产品演示", "教程/产品演示"), ("產品演示", "教程/产品演示"),
    ("Vlog", "Vlog/美食"), ("vlog", "Vlog/美食"), ("美食", "Vlog/美食"),
    ("动画", "动画"), ("動畫", "动画"),
    ("竖屏短剧", "竖屏短剧"), ("竖屏", "竖屏短剧"), ("短剧", "竖屏短剧"), ("短劇", "竖屏短剧"),
    ("长片", "长片"), ("長片", "长片"), ("纪录片", "长片"), ("紀錄片", "长片"),
    ("电视剧", "电视剧"), ("電視劇", "电视剧"), ("剧集", "电视剧"), ("劇集", "电视剧"),
    ("微电影", "短片"), ("微電影", "短片"), ("短片", "短片"),
    ("电影", "电影"), ("電影", "电影"),
]


def kind_from_text(text: str):
    msg = text or ""
    for alias, kind in KIND_ALIASES:
        if alias in msg:
            return kind
    return None


def history_for_prompt(history, max_turns: int = 12, max_chars: int = 5200):
    """给模型用的对话历史：最多 max_turns 条、总字符不超过 max_chars（从最新往旧取）。"""
    out = []
    used = 0
    for turn in reversed(history or []):
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        content = content[:1800]
        if used + len(content) > max_chars and out:
            break
        out.append({"role": role, "content": content})
        used += len(content)
        if len(out) >= max_turns:
            break
    return list(reversed(out))


def history_block(history, max_turns: int = 8, max_chars: int = 1600) -> str:
    """给工具提示词用的对话上下文摘要。"""
    turns = history_for_prompt(history, max_turns=max_turns, max_chars=max_chars)
    if not turns:
        return ""
    lines = ["【对话上下文（供延续上文，勿重复已给过的内容）】"]
    for turn in turns:
        who = "用户" if turn["role"] == "user" else "助手"
        lines.append(f"{who}：{turn['content'][:500]}")
    return "\n".join(lines)


def _idea_from_history(history) -> str:
    for turn in reversed(history or []):
        if turn.get("role") != "assistant":
            continue
        m = re.search(r"关键词\*{0,2}\s*[:：]\s*([^\n]+)", str(turn.get("content") or ""))
        if m:
            return m.group(1).strip()
    return ""


def _last_tool_from_history(history):
    """从 assistant 文本标记猜测上一轮工具，用于「换一批/继续」这类追问。"""
    for turn in reversed(history or []):
        if turn.get("role") != "assistant":
            continue
        content = str(turn.get("content") or "")
        if "### 梗要" in content or "剧本全文" in content:
            return "review", _kind_from_history(history)
        if "分镜表（" in content or "分镜表(" in content:
            return "storyboard", None
        if "详细拍摄方案" in content or "拍摄日" in content:
            return "schedule", None
        if "风格 1" in content and ("契合电影" in content or "**题材**" in content or "**关键词**" in content):
            return "inspiration", _kind_from_history(history)
    return None, None


_CONTINUE_WORDS = re.compile(
    r"^(?:再(?:来|换|给|出|做|生成|写)?(?:一|几|三|五|十)?(?:批|个|组|版|份|条)?|"
    r"换(?:一批|一批吧|一组|一个|个|一版)|继续|接着|还有(?:吗|么|没有)|next|more|again|continue)[!！。？?~～\s]*$",
    re.I)


def is_continuation(message: str) -> bool:
    msg = (message or "").strip()
    return bool(msg) and len(msg) <= 12 and bool(_CONTINUE_WORDS.match(msg))


def _kind_from_history(history):
    for turn in reversed(history or []):
        if turn.get("role") != "assistant":
            continue
        content = str(turn.get("content", ""))
        m = re.search(r"题材\*{0,2}\s*[:：]\s*([^\s｜|\n]+)", content)
        if m:
            return kind_from_text(m.group(1)) or m.group(1).strip()
    return None


_LANG_EN_CMD = re.compile(
    r"(?:切换到|切换成|切换|切到|改成|改为|换成|换到|使用|用|说|讲|回答|回复|输出|生成|翻译成|翻譯成)\s*(?:英文|英语|English)"
    r"|(?:英文|英语|English)\s*(?:回答|回复|输出|写|生成|模式)"
    r"|switch\s+to\s+english|in\s+english|english\s+please|use\s+english",
    re.I)
_LANG_ZH_CMD = re.compile(
    r"(?:切换到|切换成|切换|切到|改成|改为|换成|换到|使用|用|说|讲|回答|回复|输出|生成|翻译成|翻譯成)\s*(?:中文|汉语|漢語|Chinese)"
    r"|(?:中文|汉语|漢語|Chinese)\s*(?:回答|回复|输出|写|生成|模式)"
    r"|switch\s+to\s+chinese|in\s+chinese|chinese\s+please|use\s+chinese",
    re.I)


def detect_lang_command(message: str):
    """识别「切换英文 / 用英文回答 / switch to English」等语言切换指令。"""
    msg = message or ""
    en = bool(_LANG_EN_CMD.search(msg))
    zh = bool(_LANG_ZH_CMD.search(msg))
    if not en and not zh:
        return None
    if en and zh:
        # 两者都有时取「最后出现的指令」为目标语言
        last_en = max(m.end() for m in _LANG_EN_CMD.finditer(msg))
        last_zh = max(m.end() for m in _LANG_ZH_CMD.finditer(msg))
        return "en" if last_en > last_zh else "zh"
    return "en" if en else "zh"


def strip_lang_command(message: str) -> str:
    """去掉消息里的语言切换指令，保留真正的请求。"""
    msg = message or ""
    msg = _LANG_EN_CMD.sub("", msg)
    msg = _LANG_ZH_CMD.sub("", msg)
    msg = re.sub(r"^[，,。；;\s]+", "", msg).strip()
    return msg or ""


def is_lang_command_only(message: str) -> bool:
    return bool(detect_lang_command(message)) and len(strip_lang_command(message)) <= 4


_LANG = "zh"


def set_lang(lang) -> None:
    global _LANG
    _LANG = "en" if str(lang or "").lower().startswith("en") else "zh"


def lang_hint() -> str:
    if _LANG != "en":
        return ""
    return ("\n\nIMPORTANT: The user interface is English. Reply entirely in English "
            "(all headings, explanations, loglines, dialogue). Keep JSON field names exactly as specified.")


def llm_error_hint(exc: Exception) -> str:
    """把模型/额度错误翻译成用户能操作的提示。"""
    msg = str(exc or "")
    if "402" in msg or "budget" in msg.lower() or "quota" in msg.lower():
        return ("模型额度已用尽（Vercel AI Gateway: budget exceeded）。"
                "请在项目 .env 里更换 AI_GATEWAY_API_KEY（或设置 DEEPSEEK_API_KEY），"
                "然后重启服务：.venv/bin/python app.py。")
    if "401" in msg or "invalid api key" in msg.lower():
        return "模型 API Key 无效（401），请在 .env 检查 AI_GATEWAY_API_KEY / DEEPSEEK_API_KEY。"
    if "429" in msg or "rate limit" in msg.lower():
        return "模型请求太频繁（429），等一分钟再试。"
    if "timeout" in msg.lower():
        return "模型响应超时，重试一次或把剧本拆短。"
    return "模型调用失败：" + msg[:160]


def _taste_block():
    try:
        import personal_library
        return personal_library.taste_context()
    except Exception:  # noqa: BLE001
        return ""


def _theme_from_text(message: str, kind: str = None):
    msg = (message or "").strip()
    m = re.search(r"(?:关于|關於|围绕|圍繞)\s*([^的，。,.\n]{1,20}?)\s*的?(?:电影|電影|短片|广告|廣告|tvc|TVC|剧集|劇集|动画|動畫|片)", msg)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(r"^(?:帮我|幫我|请|請|给我|給我)?\s*(?:做|写|寫|拍|生成|出一个|出一個|来一个|來一個)\s*", "", msg)
    cleaned = re.sub(r"^(?:一个|一個|一部|一支)?\s*", "", cleaned)
    for alias, _ in KIND_ALIASES:
        cleaned = cleaned.replace(alias, "")
    cleaned = re.sub(r"(剧本|劇本)$", "", cleaned).strip(" ：:，,。.\n")
    if len(cleaned) >= 2:
        return cleaned
    return ""


def guess_intent(message: str):
    """模糊意图识别：返回 (tool, kind, idea)。tool 可为 inspiration/review/storyboard/schedule/rundown/None。"""
    msg = (message or "").strip()
    if not msg:
        return None, None, ""
    low = msg.lower()
    kind = kind_from_text(msg)
    idea = _theme_from_text(msg, kind) if kind else ""
    if re.search(r"拍摄计划|拍攝計劃|拍摄方案|拍攝方案|排期|場記|場記表|通告单|通告單|rundown|call sheet|拍几天|拍幾天", msg, re.I):
        return "rundown" if re.search(r"rundown|call sheet", msg, re.I) else "schedule", kind, idea
    if re.search(r"分镜头?建议|分镜头?生成|分镜|storyboard|shot list", msg):
        return "storyboard", kind, idea
    # 先判「写/生成/改剧本」类动作（否则「写一个关于香港的TVC剧本」会被误判成找灵感）
    if re.search(r"(写|寫|生成|改|检查|檢查|优化|優化|审|審)[^，。,\n]{0,20}(剧本|劇本)"
                 r"|(?:剧本|劇本).{0,6}(?:检查|檢查|生成|改)|写剧本|寫劇本|生成剧本|生成劇本|剧本生成|劇本生成|改剧本|改劇本|"
                 r"改标准|改標準|标准格式|標準格式", msg, re.I):
        return "review", kind, idea
    if re.search(r"灵感|靈感|想拍|想拍一个|想拍一個|帮我做|幫我做|做一个|做一個|来一个|來一個|关于.{0,12}(电影|電影|短片|广告|廣告|短片|剧|劇)|创意|創意|idea", msg, re.I):
        return "inspiration", kind, idea
    if re.search(r"剧本|劇本|script", msg, re.I):
        if re.search(r"检查|檢查|冲突|衝突|漏洞|意见|意見|问题|問題|审|審|review", msg, re.I):
            return "review", kind, idea
        if len(msg) > 150:
            return "review", kind, idea
        # 「这个剧本第一场发生了什么？」这类提问 → 交给问答（可引用当前剧本上下文）
        if re.search(r"[?？]|吗|什么|怎么|为什么|哪裡|哪里|谁|多少|讲讲|说说|分析", msg):
            return None, kind, idea
        return "inspiration", kind, idea
    if re.search(r"拍摄计划|拍攝計劃|日程|排期|schedule", msg, re.I):
        return "schedule", kind, idea
    return None, kind, idea



def parse_inspiration_kind(message: str):
    """解析题材：优先 UI 下发的【题材：电影】前缀；否则识别消息中出现的题材词。"""
    msg = message or ""
    m = _KIND_PREFIX.match(msg)
    if m:
        rest = re.sub(r"^\s*找\s*灵\s*感\s*[:：]\s*", "", msg[m.end():])
        return m.group(1).strip(), rest.strip()
    for kind in sorted(KIND_CHOICES, key=len, reverse=True):
        if kind in msg:
            return kind, msg.strip()
    return None, re.sub(r"^\s*找\s*灵\s*感\s*[:：]\s*", "", msg).strip()


def _kind_ask_text():
    if _LANG == "en":
        return ("Pick a genre first: " + " / ".join(KIND_CHOICES) + "\n\n"
                "Then describe the feeling in one line (e.g. Hong Kong, rainy night, old buildings, loneliness). "
                "I will only search real works in that genre and return style → theme → matching film (story + stills + link).")
    return (
        "先选一下你想找哪一类片的灵感：" + " / ".join(KIND_CHOICES) + "\n\n"
        "选好题材后，用一句话描述你想要的感觉（例如：香港、雨夜、旧楼、孤独、身份流动）。"
        "我会只在你选的题材库里找真实作品，再给你「风格 → 主题 → 契合电影（内容 + 静帧 + 原片链接）」。"
    )


def _norm_title(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (text or "").lower())


KIND_EN = {
    "电影": "Film", "电视剧": "TV series", "长片": "Feature", "短片": "Short",
    "竖屏短剧": "Vertical drama", "广告/TVC": "Ad / TVC", "教程/产品演示": "Tutorial",
    "Vlog/美食": "Vlog / Food", "动画": "Animation",
}


def _films_markdown(kind: str, idea: str, styles: list) -> str:
    en = _LANG == "en"
    if en:
        lines = [f"**Genre**: {KIND_EN.get(kind, kind)}　｜　**Keywords**: {idea or '(not given, using genre classics)'}", ""]
    else:
        lines = [f"**题材**：{kind}　｜　**关键词**：{idea or '（未填写，按题材代表作）'}", ""]
    for i, s in enumerate(styles, 1):
        film = s["film"]
        title = film.get("title_zh")
        year = film.get("year")
        duration = film.get("duration") or ""
        moods = "/".join(film.get("moods") or [])
        tags = ", ".join((film.get("tags") or [])[:5]) if en else "、".join((film.get("tags") or [])[:5])
        if en:
            lines.append(f"### Style {i}: {s['style_name']}")
            lines.append(f"- **Why it fits there**: {s['why_fits']}")
            lines.append(f"- **Theme {i}**: {s['theme']}")
            lines.append(f"- **Matching film {i}**: *{title}* ({year})　{duration}")
            lines.append(f"  - Story: {film.get('synopsis') or ''}")
            lines.append(f"  - Mood: {moods}　｜　Tags: {tags}")
            if film.get("url"):
                lines.append(f"  - Watch: [{film.get('platform') or 'link'}]({film['url']})")
            if s.get("film_reason"):
                lines.append(f"  - Reference point: {s['film_reason']}")
        else:
            lines.append(f"### 风格 {i}：{s['style_name']}")
            lines.append(f"- **为什么契合「{idea or kind}」**：{s['why_fits']}")
            lines.append(f"- **主题 {i}**：{s['theme']}")
            lines.append(f"- **契合电影 {i}**：《{title}》（{year}）　{duration}")
            lines.append(f"  - 内容：{film.get('synopsis') or ''}")
            lines.append(f"  - 情绪：{moods}　｜　标签：{tags}")
            if film.get("url"):
                lines.append(f"  - 原片：[{film.get('platform') or '原片链接'}]({film['url']})")
            if s.get("film_reason"):
                lines.append(f"  - 参考点：{s['film_reason']}")
        lines.append("")
    lines.append("---")
    if en:
        lines.append("Want me to write the script based on **Theme 1** first? Reply 'write script'. "
                     "After the script, reply 'storyboard' for the shot list. To switch theme, reply 'write script: theme name'.")
    else:
        lines.append("要不要我按 **主题 1** 先写一版剧本？回复「写剧本」即可（会先给一段话梗要 + 标准格式剧本）。")
        lines.append("拿到剧本之后再回复「出分镜」，就能按剧本出分镜表。想换主题就回复「写剧本：主题名」。")
    return "\n".join(lines)


async def inspiration_films(text: str, api_key: str = None, kind: str = None, history: list = None):
    """按题材划库的找灵感：只在该题材作品中检索，返回风格/主题/契合电影。"""
    import catalog as _catalog

    if not kind or kind not in KIND_CHOICES:
        return {"text": _kind_ask_text(), "need_kind": True,
                "kind_options": KIND_CHOICES, "mode": "offline"}
    idea = (text or "").strip()
    cands = _catalog.semantic_candidates(idea, kind, k=8)
    if not cands:
        return {"text": f"「{kind}」题材库里暂时没有可用作品，换一类试试？",
                "need_kind": True, "kind_options": KIND_CHOICES, "mode": "offline"}

    styles = []
    if llm.available(api_key):
        try:
            film_lines = []
            for c in cands:
                film_lines.append(
                    f"- 《{c['title_zh']}》（{c.get('year')}，{c.get('duration')}）"
                    f"｜情绪：{'/'.join(c.get('moods') or [])}"
                    f"｜类型：{'/'.join(c.get('genre') or [])}"
                    f"｜标签：{'、'.join((c.get('tags') or [])[:6])}"
                    f"｜地点线索：{'、'.join(c.get('place_hints') or [])}"
                    f"｜梗概：{c.get('synopsis')}")
            kind_req = KIND_GUIDE["inspiration"].get(kind, "")
            taste = _taste_block()
            user_content = (
                f"用户想找的类型：{kind}\n"
                f"该类型的创作要求（必须遵守，不许写成别的片种）：{kind_req}\n"
                f"用户描述的感觉/关键词：{idea or '（未填）'}\n\n"
                + ("【TVC 额外要求】每个 style 的 theme 必须点名：产品/品牌、目标人群、一句 slogan 方向；"
                   "why_fits 要说明视觉钩子如何服务产品卖点。\n\n" if kind == "广告/TVC" else "")
                + (taste + "\n\n" if taste else "")
                + ("\n\n" + history_block(history) if history else "")
                + "\n\n候选影片（只能从这里挑，片名必须逐字一致）：\n" + "\n".join(film_lines)
                + lang_hint())
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_INSPIRATION_FILMS},
                 {"role": "user", "content": user_content[:9000]}], api_key=api_key)
            by_title = {_norm_title(c["title_zh"]): c for c in cands}
            for s in data.get("styles") or []:
                if not isinstance(s, dict):
                    continue
                wanted = _norm_title(str(s.get("film_title", "")))
                film = by_title.get(wanted)
                if film is None:
                    for key, value in by_title.items():
                        if key and wanted and (key in wanted or wanted in key):
                            film = value
                            break
                if film is None or any(x["film"] is film for x in styles):
                    continue
                styles.append({
                    "style_name": str(s.get("style_name", "")).strip() or "风格",
                    "why_fits": str(s.get("why_fits", "")).strip(),
                    "theme": str(s.get("theme", "")).strip(),
                    "film_reason": str(s.get("film_reason", "")).strip(),
                    "film": film,
                })
                if len(styles) >= 3:
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("在线找灵感失败(%s),回退规则版", e)
            styles = []

    if not styles:  # 离线 / 模型失败：用检索到的真实影片套一组风格模板
        templates = [
            ("城市潮湿的夜行气质", "把空间、湿度与人物距离放在同一条街上，用夜与雨水连接人物"),
            ("关系里的克制张力", "把关系放进具体空间，让沉默与空镜承担情绪"),
            ("空间与身份的错位", "用旧楼、走廊、窗口这些空间写身份的变化"),
        ]
        for c, (name, wh) in zip(cands[:3], templates):
            if idea:
                why = f"你写到的「{idea}」在空间、湿度与人物距离上，和这部片的影像气质同频；{wh}"
            else:
                why = f"这部片是「{kind}」里最能代表这种气质的作品之一；{wh}"
            styles.append({
                "style_name": name, "why_fits": why,
                "theme": "一个人回到熟悉的旧城区，发现记忆里的人都换了身份，"
                         "他必须在留下与离开之间做一次决定。",
                "film_reason": "同题材下，这部片的影像与叙事气质最接近这个主题",
                "film": c,
            })
        mode = "offline"
    else:
        mode = "online"

    text_out = _films_markdown(kind, idea, styles)
    return {
        "kind": kind, "idea": idea,
        "styles": [{k: v for k, v in s.items() if k != "film"} for s in styles],
        "films": [s["film"] for s in styles],
        "text": text_out, "mode": mode, "kind_options": KIND_CHOICES,
    }


def _fallback_theme_storyboard(theme: str):
    """离线兜底：按主题给一份通用的 8 镜分镜（不依赖模型）。"""
    brief = (theme or "")[:60]
    template = [
        ("远景", "平视", "固定", "12s",
         f"环境建立：与「{brief}」相关的空间在雨/夜色里显出轮廓，人物从画面边缘进入", "", "现场环境声铺底，不加音乐"),
        ("中景", "平视", "跟", "6s", "镜头跟人物穿过通道或门口，前景有遮挡，交代他与这个空间的关系", "", "脚步与呼吸声"),
        ("近景", "过肩", "固定", "4s", "人物停下，目光落在某个物件或另一个人身上，背景保持虚焦", "", "环境声压低，留出对白空间"),
        ("特写", "俯拍", "固定", "3s", "手部动作：触碰、拿起或放下关键道具", "", "道具声放大"),
        ("中景", "平视", "固定", "5s", "两人不同框的对峙或沉默，靠画外音建立距离", "（按主题写一句台词）", "只留空间混响"),
        ("近景", "平视", "微推", "4s", "情绪转折点：人物表情变化，镜头慢慢推近", "", "音乐第一次进入"),
        ("全景", "俯拍", "固定", "6s", "空间关系揭示：人物在大空间里显得很小", "", "音乐延续"),
        ("特写", "平视", "固定", "5s", "收尾意象：与开头呼应的道具/光线/水痕，留白", "", "只剩环境声"),
    ]
    shots = []
    for i, (shot_type, angle, movement, duration, desc, dialogue, sound) in enumerate(template, 1):
        shots.append({
            "id": i, "scene": f"第{i}场", "shot_type": shot_type, "angle": angle,
            "movement": movement, "lens": "", "duration": duration,
            "description": desc, "dialogue": dialogue,
            "lighting": "按主题统一光比，保留现场实用光", "sound": sound,
            "purpose": "推进主题与人物关系", "transition": "切",
        })
    return shots


async def storyboard_from_theme(message: str, history: list = None, api_key: str = None):
    """用户确认主题后，按该主题出完整分镜。"""
    theme = ""
    m = re.match(r"^\s*出\s*分镜\s*[:：]\s*(.+)$", message or "", re.S)
    if m:
        theme = m.group(1).strip()
    if not theme:
        for turn in reversed(history or []):
            if turn.get("role") != "assistant":
                continue
            mm = re.search(r"主题\s*1\s*\*{0,2}\s*[:：]\s*([^\n]+)", str(turn.get("content", "")))
            if mm:
                theme = mm.group(1).strip()
                break
    if not theme:
        return {"text": "想按哪个主题出分镜？回复「出分镜：主题名」就行。", "mode": "offline"}

    shots, notes, mode = [], "", "offline"
    if llm.available(api_key):
        try:
            user_content = f"主题：{theme}\n类型：短片（6–8 分钟），请按这个主题出 8–10 个镜头。"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_STORYBOARD_THEME},
                 {"role": "user", "content": user_content[:4000]}], api_key=api_key)
            for i, s in enumerate((data.get("shots") or [])[:10]):
                if not isinstance(s, dict):
                    continue
                shots.append({
                    "id": int(s.get("id", i + 1) or i + 1),
                    "scene": str(s.get("scene", "")), "shot_type": str(s.get("shot_type", "中景")),
                    "angle": str(s.get("angle", "平视")), "movement": str(s.get("movement", "固定")),
                    "lens": str(s.get("lens", "")), "duration": str(s.get("duration", "4s")),
                    "description": str(s.get("description", "")),
                    "dialogue": str(s.get("dialogue", "")),
                    "lighting": str(s.get("lighting", "")), "sound": str(s.get("sound", "")),
                    "purpose": str(s.get("purpose", "")), "transition": str(s.get("transition", "切")),
                })
            notes = str(data.get("coverage_notes", ""))
            if shots:
                mode = "online"
        except Exception as e:  # noqa: BLE001
            logger.warning("在线分镜失败(%s),回退规则版", e)
            notes = notes or ("（在线分镜不可用：" + llm_error_hint(e) + "；已用规则版分镜）")
    if not shots:
        shots = _fallback_theme_storyboard(theme)

    lines = [f"### 分镜（主题：{theme}）", "",
             "| # | 场景 | 景别/机位/运镜 | 时长 | 画面 | 声音 |",
             "|---|---|---|---|---|---|"]
    for s in shots:
        lines.append(
            f"| {s.get('id')} | {s.get('scene', '')} | {s.get('shot_type', '')}/{s.get('angle', '')}/"
            f"{s.get('movement', '')} | {s.get('duration', '')} | {s.get('description', '')} | {s.get('sound', '')} |")
    if notes:
        lines += ["", f"**整体方向**：{notes}"]
    return {"shots": shots, "coverage_notes": notes, "mode": mode,
            "theme": theme, "text": "\n".join(lines)}



# --------------------------------------------------------------------------
# 剧本检查/生成：没剧本→按主题生成（梗要 + 标准格式剧本）；有剧本→查冲突+问是否改格式
# --------------------------------------------------------------------------
_SCRIPT_HEAD = re.compile(r"(第\s*\d+\s*[场幕]|^\s*\d+\s*[\.、]\s*(?:内|外)景|INT\.|EXT\.)", re.M)


def looks_like_script(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    hits = 0
    if re.search(r"第\s*\d+\s*[场幕]", text):
        hits += 2
    if re.search(r"^\s*\d+\s*[\.、]\s*(?:内|外)景", text, re.M):
        hits += 2
    if re.search(r"(内景|外景|INT\.|EXT\.)", text, re.I):
        hits += 1
    if re.search(r"^[^\s：:]{1,10}[：:].{2,}$", text, re.M):
        hits += 1
    if re.search(r"[（(](夜|日|清晨|傍晚|深夜|黄昏|黎明)[）)]", text):
        hits += 1
    if re.search(r"[-—]\s*(?:夜|日|清晨|傍晚|深夜|黄昏|黎明)", text):
        hits += 1
    return hits >= 2


def _norm_logline(data):
    d = data or {}
    return {
        "title": str(d.get("title") or "未命名").strip(),
        "title_en": str(d.get("title_en") or "").strip(),
        "theme": str(d.get("theme") or "").strip(),
        "summary": str(d.get("summary") or "").strip(),
    }


def _script_intro(logline):
    if _LANG == "en":
        name = logline.get("title") or "Untitled"
        en = f" ({logline['title_en']})" if logline.get("title_en") else ""
        return (
            f"### Logline\n**Title**: {name}{en}\n"
            f"**Theme**: {logline.get('theme') or '—'}\n\n"
            f"{logline.get('summary') or ''}\n\n"
            "The full script is in the scrollable area below; click \"Download PDF\" for the formatted screenplay."
        )
    name = logline.get("title") or "未命名"
    en = f"（{logline['title_en']}）" if logline.get("title_en") else ""
    return (
        f"### 梗要\n**片名**：{name}{en}\n"
        f"**主题**：{logline.get('theme') or '—'}\n\n"
        f"{logline.get('summary') or ''}\n\n"
        "剧本全文在下方可滚动区域；点「下载 PDF」可以拿到标准格式剧本。"
    )


async def _theme_from_history(history, message):
    for turn in reversed(history or []):
        if turn.get("role") != "assistant":
            continue
        content = str(turn.get("content", ""))
        m = re.search(r"主题\s*1\s*\*{0,2}\s*[:：]\s*([^\n]+)", content)
        if m:
            return m.group(1).strip()
        m = re.search(r"主题\s*[：:]\s*([^\n]+)", content)
        if m:
            return m.group(1).strip()
    return ""


async def _logline_for_script(script_text, api_key):
    if llm.available(api_key):
        try:
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_SCRIPT_LOG_LINE},
                 {"role": "user", "content": script_text[:8000] + lang_hint()}], api_key=api_key)
            return _norm_logline(data)
        except Exception as e:  # noqa: BLE001
            logger.warning("梗要生成失败(%s)", e)
    first = (script_text.strip().splitlines() or ["未命名剧本"])[0][:40]
    return {"title": first or "未命名剧本", "title_en": "", "theme": "",
            "summary": script_text.strip()[:120].replace("\n", " ") + "…"}


def _format_review(report) -> str:
    """把 review() 的结构化结果转成给人看的文字。"""
    if not isinstance(report, dict):
        return ""
    if report.get("text"):
        return str(report["text"])
    lines = []
    if report.get("summary"):
        lines.append("**总评**：" + str(report["summary"]))
    issues = report.get("issues") or []
    if issues:
        lines.append("")
        lines.append("**发现的问题**：")
        for it in issues[:8]:
            if not isinstance(it, dict):
                continue
            lines.append(
                f"- [{it.get('severity', '中')}] {it.get('location', '')}："
                f"{it.get('problem', '')}（建议：{it.get('suggestion', '')}）")
    strengths = report.get("strengths") or []
    if strengths:
        lines.append("")
        lines.append(("**Strengths**: " if _LANG == "en" else "**可保留的优点**：") + "；".join(str(x) for x in strengths[:4]))
    if report.get("next_steps"):
        lines.append("")
        lines.append(("**Next steps**: " if _LANG == "en" else "**下一步**：") + str(report["next_steps"]))
    return "\n".join(lines)


async def script_tool(message: str, api_key: str = None, script_text: str = "", history: list = None, kind: str = None):
    """剧本检查/生成：有剧本查冲突并问是否改标准格式；没剧本按主题生成。"""
    msg = (message or "").strip()
    script = (script_text or "").strip()
    msg = re.sub(r"^(?:剧本检查[/／]?生成|剧本检查|剧本生成|写剧本)\s*[:：]?\s*", "", msg)

    if script:
        if not looks_like_script(script):
            return {
                "text": "这份内容看起来不像分场剧本（没找到场次标题、内/外景或对白）。"
                        "可以点输入区的回形针上传 PDF / DOCX / TXT，或直接粘贴「第1场 内景 便利店 夜」这种格式。",
                "needs_script": True, "mode": "offline",
            }
        if re.search(r"改成标准|标准格式|改成剧本格式|整理成剧本|重排格式", msg):
            if not llm.available(api_key):
                return {"text": "改格式需要在线模型，当前模型不可用。", "mode": "offline"}
            try:
                data = await llm.complete_json(
                    [{"role": "system", "content": prompts.PROMPT_SCRIPT_REFORMAT},
                     {"role": "user", "content": script[:12000]}], api_key=api_key)
                logline = _norm_logline(data.get("logline"))
                text = str(data.get("script_text") or "").strip() or script
                return {"kind": "script", "logline": logline, "script_text": text,
                        "text": _script_intro(logline) + "\n\n已按标准电影剧本格式整理。",
                        "mode": "online"}
            except Exception as e:  # noqa: BLE001
                logger.warning("剧本改格式失败(%s)", e)
                return {"text": "改格式失败了，稍后再试一次。", "mode": "offline"}
        # 冲突检查
        ctx, refs = await asyncio.to_thread(_build_context, "review", script)
        report = await review(script, api_key, ctx, refs)
        report_text = _format_review(report).strip()
        summary = (
            f"剧本已识别（约 {len(script)} 字）。先做冲突与问题检查：\n\n"
            f"{report_text[:3500] if report_text else '（未生成检查报告）'}\n\n---\n"
            "要不要我把这份剧本改成**标准电影剧本格式**（场次标题 / 动作 / 角色与对白分行）？"
            "回复「改成标准格式」即可；改完可以下载 PDF。"
        )
        return {"kind": "script_check", "logline": None, "script_text": script,
                "findings": report.get("findings") or [], "text": summary,
                "mode": report.get("mode", "offline")}

    # 没剧本：按主题生成
    theme = ""
    m = re.search(r"写剧本\s*[:：]\s*(.+)", msg, re.S)
    if m:
        theme = m.group(1).strip()
    if not theme:
        theme = await _theme_from_history(history, msg)
    if not theme:
        theme = _theme_from_text(msg, kind)
    if not theme and len(msg) >= 8:
        theme = msg
    if not theme:
        return {"text": "写剧本需要先有一个主题：可以先用「找灵感」得到主题，或直接回复「写剧本：你的主题」。",
                "needs_theme": True, "mode": "offline"}
    if not llm.available(api_key):
        return {"text": "剧本生成需要在线模型，当前模型不可用。", "mode": "offline"}
    try:
        film_kind = kind or _kind_from_history(history) or kind_from_text(msg) or "短片"
        guide = KIND_GUIDE["script"].get(film_kind, KIND_GUIDE["script"]["短片"])
        taste = _taste_block()
        user_prompt = (
            f"主题：{theme}\n输出类型：{film_kind}\n类型与格式要求（必须遵守）：{guide}\n"
            + (("用户收藏的参考片（贴近其品味）：\n" + taste + "\n") if taste else "")
            + "请只输出这个类型该有的剧本/脚本格式，不要写成别的片种。"
            + lang_hint()
        )
        # 直接生成正文纯文本（比长 JSON 稳，英文剧本也不会被截断）；梗要再单独生成
        plain_system = ("你是职业编剧。直接输出标准格式的剧本/脚本正文，"
                        "不要 JSON、不要 markdown 代码块、不要解释。" + lang_hint())
        text = ""
        for _attempt in range(2):
            try:
                text = (await llm.complete(
                    [{"role": "system", "content": plain_system},
                     {"role": "user", "content": user_prompt + "\n请直接输出正文。"}],
                    api_key=api_key)).strip()
            except Exception as _e:  # noqa: BLE001
                logger.warning("剧本正文生成失败(%s)", _e)
                text = ""
            if text:
                break
        if not text:
            raise ValueError("模型没有返回剧本正文（已重试）")
        logline = await _logline_for_script(text, api_key)
        if not logline or not logline.get("title"):
            logline = _norm_logline({"title": theme[:24] or ("Untitled" if _LANG == "en" else "未命名"),
                                     "theme": theme, "summary": text[:120]})
        return {"kind": "script", "film_kind": film_kind, "logline": logline,
                "script_text": text, "characters": [],
                "text": _script_intro(logline) + "\n\n剧本生成好了！想改哪场直接说；要出分镜就回复「出分镜」。",
                "mode": "online"}
    except Exception as e:  # noqa: BLE001
        logger.warning("剧本生成失败(%s)", e)
        hint = llm_error_hint(e)
        return {"text": "剧本生成失败：" + hint, "mode": "offline", "error_hint": hint}


_HEADING_RE = re.compile(r"^\s*(?:第\s*(\d+)\s*场[\s\.、:：-]*|(\d+)\s*[\.、]\s*)(.*)$")


def split_script_scenes(text: str):
    """兼容多种格式的剧本分场：1. 内景 便利店 - 深夜 / 第1场 内景 便利店 夜 / 内景 …"""
    lines = (text or "").splitlines()
    scenes, cur = [], None
    for line in lines:
        m = _HEADING_RE.match(line)
        heading = None
        if m:
            rest = (m.group(3) or "").strip()
            num = m.group(1) or m.group(2)
            looks_location = bool(re.search(r"(内景|外景|INT\.?|EXT\.?|日|夜)", rest, re.I)) or len(rest) >= 2
            if looks_location and rest and not rest.startswith(("：", ":")):
                heading = (int(num), f"第{int(num)}场 {rest}")
        if heading:
            if cur:
                scenes.append(cur)
            cur = {"scene_no": heading[0], "heading": heading[1], "body": []}
        elif cur is not None:
            cur["body"].append(line)
    if cur:
        scenes.append(cur)
    # 若标题里没写 内/外景 而正文第一行写了，合并进标题
    for s in scenes:
        body_lines = [x.strip() for x in s["body"] if x.strip()]
        s["body_text"] = "\n".join(body_lines)
        if body_lines and not re.search(r"(内景|外景|INT\.?|EXT\.?)", s["heading"], re.I):
            first = body_lines[0]
            if re.match(r"^\s*(内景|外景|INT\.?|EXT\.?)", first, re.I):
                s["heading"] = s["heading"] + " " + first[:20]
                s["body_text"] = "\n".join(body_lines[1:])
        if not s["body_text"]:
            s["body_text"] = "（此场无正文）"
    # 重新编号，保证连续
    for i, s in enumerate(scenes, 1):
        s["scene_no"] = i
        s["heading"] = re.sub(r"^第\d+场", f"第{i}场", s["heading"])
    return scenes


def _scene_blocks(script_text: str):
    scenes = split_script_scenes(script_text)
    blocks = []
    for s in scenes[:14]:
        dialogues = extract_dialogues(s["body_text"])
        dlg = "；".join(f"{d[0]}：{d[1][:36]}" for d in dialogues[:3])
        cast = [d[0] for d in dialogues[:5]]
        blocks.append({
            "scene_no": s["scene_no"], "heading": s["heading"],
            "cast": "、".join(dict.fromkeys(cast)), "body": s["body_text"],
            "dialogue": dlg, "scenes": scenes,
        })
    return scenes, blocks


def _scene_keywords(scene):
    body = scene.get("body_text", "")
    words = re.findall(r"[\u4e00-\u9fff]{2,4}", body)
    stop = {"一个", "他们", "自己", "什么", "然后", "时候", "这里", "那里", "已经", "没有", "开始", "慢慢", "看见", "抬头", "转身", "声音", "镜头"}
    return [w for w in dict.fromkeys(words) if w not in stop][:24]


def _rule_shots_from_scenes(scenes):
    """规则分镜：严格按剧本场次生成 master + 对白 + 细节，保证与剧本一致。"""
    shots = []
    sid = 0
    for scene in scenes:
        no = scene["scene_no"]
        heading = scene["heading"]
        body = scene["body_text"]
        dialogues = extract_dialogues(body)
        sentences = [x.strip() for x in re.split(r"[。！？\n]", body) if x.strip()]
        master = sentences[0][:80] if sentences else heading
        sid += 1
        shots.append({
            "id": sid, "scene_no": no, "scene": heading,
            "shot_type": "全景", "angle": "平视", "movement": "固定", "lens": "24mm",
            "duration": "6s",
            "description": f"全景交代{heading}：{master}",
            "dialogue": "", "lighting": "现场实用光 + 一盏柔光补脸", "sound": "环境声铺底",
            "purpose": "建立空间与人物位置", "transition": "切",
        })
        if dialogues:
            name, line = dialogues[0][0], dialogues[0][1]
            sid += 1
            shots.append({
                "id": sid, "scene_no": no, "scene": heading,
                "shot_type": "近景", "angle": "过肩", "movement": "固定", "lens": "50mm",
                "duration": "4s",
                "description": f"{name}说「{line[:40]}」时的反应与表情，背景虚焦",
                "dialogue": line[:60], "lighting": "主光偏侧，保留半张脸阴影", "sound": "对白为主，环境声压低",
                "purpose": "推进这一场的信息与情绪", "transition": "切",
            })
        detail = sentences[-1][:80] if sentences else ""
        sid += 1
        shots.append({
            "id": sid, "scene_no": no, "scene": heading,
            "shot_type": "特写", "angle": "平视", "movement": "微推", "lens": "85mm",
            "duration": "3s",
            "description": f"细节特写：{detail or master}",
            "dialogue": "", "lighting": "局部光，突出质感", "sound": "细节声放大",
            "purpose": "收住这一场的情绪或信息点", "transition": "切",
        })
    return shots


def _shots_match_scenes(shots, scenes):
    if not shots:
        return False
    by_no = {s["scene_no"]: s for s in scenes}
    matched = 0
    for shot in shots:
        scene = by_no.get(shot.get("scene_no"))
        if not scene:
            continue
        keys = _scene_keywords(scene)
        desc = shot.get("description", "") + shot.get("dialogue", "")
        if any(k in desc for k in keys):
            matched += 1
    return matched >= max(2, int(len(shots) * 0.5))


async def storyboard_tool(message: str, api_key: str = None, script_text: str = "", history: list = None):
    """分镜建议/生成：必须先有剧本；严格按剧本逐场出分镜（避免内容和剧本对不上）。"""
    script = (script_text or "").strip()
    if not script:
        return {
            "text": "分镜需要先有剧本。\n\n点输入区的回形针上传 PDF / DOCX / TXT，或把剧本贴在输入框里，"
                    "再点「分镜建议/生成」。\n（如果还没剧本，可以先用「找灵感」定主题，再用「剧本检查/生成」写一版剧本。）",
            "needs_script": True, "mode": "offline",
        }
    if not looks_like_script(script):
        return {"text": "上传的内容看起来不像分场剧本（没找到场次/对白/场景标题），先确认一下剧本文件。",
                "needs_script": True, "mode": "offline"}

    scenes, blocks = _scene_blocks(script)
    shots, notes, mode = [], "", "offline"
    if llm.available(api_key) and scenes:
        try:
            scene_text = "\n\n".join(
                f"【第{b['scene_no']}场】{b['heading']}\n人物：{b['cast'] or '—'}\n"
                f"正文：{b['body'][:420]}" + (("\n对白：" + b["dialogue"]) if b["dialogue"] else "")
                for b in blocks)
            user_prompt = (
                "这是用户上传的剧本，请严格逐场出分镜，不能换故事：\n\n"
                f"剧本全文：\n{script[:6500]}\n\n逐场信息（每一场都要覆盖）：\n{scene_text}" + lang_hint())
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_STORYBOARD_SCRIPT},
                 {"role": "user", "content": user_prompt}],
                api_key=api_key, temperature=0.2)
            raw_shots = data.get("shots") or []
            normalized = []
            for i, s in enumerate(raw_shots):
                if not isinstance(s, dict):
                    continue
                try:
                    scene_no = int(s.get("scene_no") or 0)
                except (TypeError, ValueError):
                    scene_no = 0
                if not (1 <= scene_no <= len(scenes)):
                    continue
                normalized.append({
                    "id": int(s.get("id", i + 1) or i + 1), "scene_no": scene_no,
                    "scene": scenes[scene_no - 1]["heading"],
                    "shot_type": str(s.get("shot_type", "中景")), "angle": str(s.get("angle", "平视")),
                    "movement": str(s.get("movement", "固定")), "lens": str(s.get("lens", "")),
                    "duration": str(s.get("duration", "4s")), "description": str(s.get("description", "")),
                    "dialogue": str(s.get("dialogue", "")), "lighting": str(s.get("lighting", "")),
                    "sound": str(s.get("sound", "")), "purpose": str(s.get("purpose", "")),
                    "transition": str(s.get("transition", "切")),
                })
            notes = str(data.get("coverage_notes") or "")
            if _shots_match_scenes(normalized, scenes):
                shots = normalized
                mode = "online"
            else:
                logger.warning("分镜与剧本内容不匹配，改用规则分镜")
        except Exception as e:  # noqa: BLE001
            logger.warning("在线分镜失败(%s),回退规则版", e)

    if not shots:
        shots = _rule_shots_from_scenes(scenes)
        mode = "offline"

    logline = await _logline_for_script(script, api_key)
    result = {
        "kind": "storyboard", "logline": logline, "shots": shots,
        "coverage_notes": notes, "mode": mode, "scene_count": len(scenes),
    }
    result["text"] = (_script_intro(logline)
                      + (f"\n\nThe storyboard ({len(shots)} shots covering {len(scenes)} scenes) is below; "
                         "click \"Download CSV\" to get the table." if _LANG == "en" else
                         f"\n\n分镜表（{len(shots)} 个镜头，覆盖剧本 {len(scenes)} 场）在下方，"
                         "点「下载 CSV」可直接拿到表格。"))
    return result


async def schedule_tool(message: str, api_key: str = None, storyboard: dict = None, history: list = None):
    """拍摄计划：根据最近一版分镜生成详细拍摄方案 + 可下载的日历事件。"""
    import datetime as _dt
    from datetime import timedelta

    shots = []
    if isinstance(storyboard, dict):
        shots = storyboard.get("shots") or []
    if not shots:
        return {"text": "拍摄计划需要最近的一版分镜：请先用「分镜建议/生成」生成分镜，再点「拍摄计划」。",
                "needs_storyboard": True, "mode": "offline"}
    shots = shots[:40]
    today = _dt.datetime.now().astimezone()
    shot_lines = [
        f"- 镜{s.get('id')}｜{s.get('scene')}｜{s.get('shot_type')}/{s.get('angle')}/{s.get('movement')}"
        f"｜{s.get('duration')}｜{str(s.get('description'))[:60]}"
        for s in shots
    ]
    pref = (message or "").strip()
    if re.fullmatch(r"根据最近的分镜[，,]?\s*生成(详细)?的?拍摄(方案|计划)", pref):
        pref = ""
    summary, crew, equipment, locations, days, risks, calendar = "", [], [], [], [], [], []
    mode = "offline"
    if llm.available(api_key):
        try:
            user_prompt = (
                f"当前日期：{today.date().isoformat()}\n"
                f"用户偏好/限制（必须优先满足）：{pref or '（未特别说明，按常规安排）'}\n"
                f"分镜表（共 {len(shots)} 镜）：\n" + "\n".join(shot_lines) + lang_hint())
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_SHOOTING_PLAN},
                 {"role": "user", "content": user_prompt}], api_key=api_key, temperature=0.4)
            summary = str(data.get("summary") or "")
            crew = data.get("crew") or []
            equipment = data.get("equipment") or []
            locations = data.get("locations") or []
            days = data.get("days") or []
            risks = data.get("risks") or []
            calendar = data.get("calendar") or []
            if days:
                mode = "online"
        except Exception as e:  # noqa: BLE001
            logger.warning("在线拍摄计划失败(%s),回退规则版", e)
    if not days:
        d1 = (today.date() + timedelta(days=1)).isoformat()
        scenes = [s for s in dict.fromkeys(x.get("scene") for x in shots) if s]
        days = [{
            "day": 1, "date": d1, "call": "08:00", "wrap": "18:00",
            "scenes": scenes,
            "blocks": [
                {"start": "08:00", "end": "09:00", "activity": "crew call / 器材与场景准备"},
                {"start": "09:00", "end": "13:00", "activity": "上午：按场次拍 master + 主要 coverage"},
                {"start": "13:00", "end": "14:00", "activity": "午饭"},
                {"start": "14:00", "end": "18:00", "activity": "下午：补近景/特写与插入镜头"},
            ],
            "notes": "按场次分组拍摄，夜戏留到傍晚抢天光",
        }]
        calendar = [{
            "title": "Day 1 拍摄", "start": d1 + "T09:00:00", "end": d1 + "T18:00:00",
            "location": "待定", "description": "根据分镜生成的拍摄日",
        }]
        summary = summary or f"共 {len(shots)} 个镜头，集中在 1 天完成；先 master 后 coverage。"

    if _LANG == "en":
        lines = ["### Detailed shooting plan", "", f"**Overview**: {summary or 'Schedule based on the storyboard'}"]
    else:
        lines = ["### 详细拍摄方案", "", f"**概述**：{summary or '按分镜表安排拍摄'}"]
    if crew:
        lines.append(("**Crew**: " if _LANG == "en" else "**人员**：") + "；".join(
            f"{c.get('role')}×{c.get('count', 1)}{('（' + str(c.get('note')) + '）') if c.get('note') else ''}"
            for c in crew[:8] if isinstance(c, dict)))
    if equipment:
        lines.append(("**Gear**: " if _LANG == "en" else "**器材**：") + "、".join(str(x) for x in equipment[:10]))
    if locations:
        lines.append(("**Locations**: " if _LANG == "en" else "**场景**：") + "；".join(
            f"{l.get('name')}{('（' + str(l.get('note')) + '）') if l.get('note') else ''}"
            for l in locations[:8] if isinstance(l, dict)))
    lines += (["", "| Day | Date | Time | Scenes | Notes |", "|---|---|---|---|---|"] if _LANG == "en"
              else ["", "| Day | 日期 | 时间 | 场次 | 要点 |", "|---|---|---|---|---|"])
    for d in days:
        if not isinstance(d, dict):
            continue
        lines.append(
            f"| Day {d.get('day')} | {d.get('date')} | {d.get('call')}-{d.get('wrap')} | "
            f"{'、'.join(str(x) for x in (d.get('scenes') or []))} | {d.get('notes', '')} |")
    if risks:
        lines += ["", ("**Risks**: " if _LANG == "en" else "**风险与预案**：") + "；".join(
            f"{r.get('risk')}→{r.get('mitigation')}" for r in risks[:6] if isinstance(r, dict))]
    lines += ["", ("Once dates are confirmed, click \"Download calendar (.ics)\" below to import into your calendar." if _LANG == "en"
                 else "确认档期后，点下方「下载日历（.ics）」可直接导入系统日历。")]
    if pref:
        lines.insert(2, (f"**Your preferences**: {pref}\n" if _LANG == "en" else f"**你的偏好**：{pref}\n"))
    return {
        "kind": "schedule", "summary": summary, "crew": crew, "equipment": equipment,
        "locations": locations, "days": days, "risks": risks, "calendar": calendar,
        "shots_count": len(shots), "preferences": pref, "mode": mode, "text": "\n".join(lines),
    }



async def run_tool(tool: str, message: str, api_key: str = None, history: list = None, kind: str = None):
    if tool == "cases":
        return await cases_tool(message, api_key)
    # 找灵感 v2：先确定题材（划库），只在对应题材的影片库里找片
    if tool == "inspiration":
        prefix_match = _KIND_PREFIX.match(message or "")
        prefix_kind = prefix_match.group(1).strip() if prefix_match else None
        idea = (message[prefix_match.end():] if prefix_match else message or "").strip()
        use_kind = kind or prefix_kind or kind_from_text(message) or _kind_from_history(history)
        if not prefix_kind:
            extracted = _theme_from_text(idea, use_kind)
            if extracted:
                idea = extracted
        idea = re.sub(r"^\s*找\s*灵\s*感\s*[:：]\s*", "", idea).strip()
        # 「再换一批 / 继续」：沿用上一轮的关键词，而不是把指令当关键词
        if is_continuation(message):
            idea = _idea_from_history(history) or idea
        return await inspiration_films(idea, api_key, use_kind, history=history)
    if tool == "schedule":
        return await schedule_tool(message, api_key, None, history)
    # 用户确认主题后出分镜
    if tool == "storyboard" and re.match(r"^\s*出\s*分镜", message or ""):
        return await storyboard_from_theme(message, history, api_key)
    # 创作类工具先检索资料（案例/场面/镜头/通告单），注入提示词或附到结果
    ctx, refs = "", []
    if tool in ("review", "storyboard", "rundown", "schedule"):
        ctx, refs = await asyncio.to_thread(_build_context, tool, message)
    if tool == "review":
        return await review(message, api_key, ctx, refs)
    if tool == "storyboard":
        return await storyboard(message, api_key, ctx, refs)
    if tool == "rundown":
        return await rundown(message, api_key, ctx, refs)
    if tool == "schedule":
        return await schedule(message, api_key, ctx, refs)
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
