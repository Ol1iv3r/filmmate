"""创作辅助工具:剧本检查 / 分镜建议 / 拍摄 Rundown / 日程规划 / 灵感激发。

每个工具都有两种实现:
  - 在线模式:DeepSeek 按 JSON 规范生成结构化结果(见 prompts.py)
  - 离线模式:本地启发式/模板(无需 API Key,保证现场演示不翻车)
两个模式的输出结构完全一致,前端无需区分。
"""
import logging
import random
import re
from collections import Counter

import llm
import prompts

logger = logging.getLogger("tools")

# --------------------------------------------------------------------------
# 意图识别(关键词规则,零延迟;前端快捷按钮可强制指定工具)
# --------------------------------------------------------------------------
_REVIEW_WORDS = ["检查", "漏洞", "审", "批改", "评价", "反馈", "意见", "问题", "bug", "review", "plot hole"]
_STORY_WORDS = ["分镜", "storyboard", "分镜头", "镜头表", "shot list", "shotlist"]
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
    if _has_any(msg, _CASE_WORDS):
        return "cases"
    if _has_any(msg, _STORY_WORDS):
        return "storyboard"
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
        "mode": "offline",
    }


async def review(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text
            if case_ctx:
                user_content += f"\n\n以下是案例库中与本题材相关的优秀案例(检索所得),审阅时可借鉴其中的经验教训:\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_REVIEW},
                 {"role": "user", "content": user_content[:6000]}], api_key=api_key)
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
        "score": int(data.get("score", 7)),
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
    return out


# --------------------------------------------------------------------------
# 分镜建议 storyboard
# --------------------------------------------------------------------------
SHOT_TYPES = ["全景", "中景", "近景", "特写"]
ANGLES = ["平视", "过肩", "仰拍", "俯拍"]
MOVES = ["固定", "推", "稳定器跟随", "摇"]


def offline_storyboard(text: str, refs: list = None):
    scenes = parse_scenes(text)
    shots, sid = [], 0
    for si, scene in enumerate(scenes[:4]):
        sname = scene[0][:24] if scene else f"第{si + 1}场"
        stext = "\n".join(scene)
        dlg = extract_dialogues(stext)
        first_dlg = dlg[0][1][:30] if dlg else ""
        n = 3 if len(stext) > 80 else 2
        for j in range(n):
            shot_type = SHOT_TYPES[j % len(SHOT_TYPES)]
            sid += 1
            shots.append({
                "id": sid, "scene": f"第{si + 1}场 {sname}",
                "shot_type": shot_type,
                "angle": ANGLES[(si + j) % len(ANGLES)],
                "movement": "固定" if j == 0 else MOVES[(si + j) % len(MOVES)],
                "duration": f"{3 + (j % 3) * 2}s",
                "description": f"以{shot_type}建立{'空间关系与人物位置' if j == 0 else '情绪与细节'},注意构图留白与视线方向。",
                "dialogue": first_dlg if j == 1 else "",
            })
    if not shots:  # 没有可解析的剧本 → 给一个通用示例
        shots = [
            {"id": 1, "scene": "示例:开场", "shot_type": "全景", "angle": "平视", "movement": "固定",
             "duration": "5s", "description": "交代环境与人物位置,画面四边留呼吸空间。", "dialogue": ""},
            {"id": 2, "scene": "示例:开场", "shot_type": "中景", "angle": "过肩", "movement": "固定",
             "duration": "4s", "description": "对话正反打,过肩机位建立空间关系。", "dialogue": ""},
            {"id": 3, "scene": "示例:开场", "shot_type": "特写", "angle": "平视", "movement": "推",
             "duration": "3s", "description": "推向面部,强调情绪转折。", "dialogue": ""},
        ]
    note = "离线模式生成的分镜草稿示例;接入 API 后按剧本语义自动设计。"
    if refs:
        top = refs[0]
        note = f"借鉴案例{top['title']}:{'、'.join(top.get('storyboard_highlights', [])[:2])}(接入 API 后按剧本语义定制)"
    out = {"shots": shots, "mode": "offline", "note": note}
    if refs:
        out["references"] = refs
    return out


async def storyboard(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:4000]
            if case_ctx:
                user_content += f"\n\n参考案例(检索自案例库,请借鉴其分镜设计与拍摄流程,但必须适配用户剧本):\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_STORYBOARD},
                 {"role": "user", "content": user_content[:6000]}], api_key=api_key)
            shots = []
            for i, s in enumerate(data.get("shots", []) or []):
                if not isinstance(s, dict):
                    continue
                shots.append({
                    "id": int(s.get("id", i + 1)),
                    "scene": str(s.get("scene", "")),
                    "shot_type": str(s.get("shot_type", "中景")),
                    "angle": str(s.get("angle", "平视")),
                    "movement": str(s.get("movement", "固定")),
                    "duration": str(s.get("duration", "4s")),
                    "description": str(s.get("description", "")),
                    "dialogue": str(s.get("dialogue", "")),
                })
            return {"shots": shots, "mode": "online", **({"references": refs} if refs else {})}
        except Exception as e:  # noqa: BLE001
            logger.warning("在线分镜失败(%s),回退离线", e)
    return offline_storyboard(text, refs=refs)


# --------------------------------------------------------------------------
# 拍摄 Rundown
# --------------------------------------------------------------------------
def offline_rundown(text: str, refs: list = None):
    scenes = parse_scenes(text)
    topic = _pick_topic(text)
    ref_case = refs[0] if refs else None
    case_equip = "、".join(ref_case["equipment"][:4]) if ref_case and ref_case.get("equipment") else "摄影机、指向性话筒、灯光"
    case_loc = ref_case["locations"][0] if ref_case and ref_case.get("locations") else "内景/外景(待勘景确认)"
    items = [
        {"time": "08:00", "item": "集合与设备检查", "location": "集合点", "cast": "全员", "equipment": case_equip, "notes": "开拍前确认所有电池满电"},
        {"time": "08:30", "item": "演员化妆与服装确认", "location": "化妆区", "cast": "演员", "equipment": "化妆包", "notes": "场记同步登记服装与道具"},
    ]
    t = 9 * 60 + 30
    for i, scene in enumerate(scenes[:6]):
        sname = scene[0][:20] if scene else f"场景 {i + 1}"
        t += 40
        items.append({
            "time": f"{t // 60:02d}:{t % 60:02d}",
            "item": f"拍摄:第{i + 1}场 {sname}",
            "location": case_loc,
            "cast": "该场演员",
            "equipment": case_equip,
            "notes": "按镜头清单同机位连拍,先全景后特写",
        })
        if i == 2:
            items.append({"time": "12:30", "item": "午餐", "location": "", "cast": "全员", "equipment": "", "notes": "提前订餐,控制在 1 小时"})
            t = 13 * 60 + 30
    if len(scenes) > 6:
        items.append({"time": "17:00", "item": f"拍摄:第7场及之后({len(scenes) - 6} 场)", "location": "待定", "cast": "", "equipment": "", "notes": "或移至第二天,避免超时"})
    items.append({"time": "19:00", "item": "收工:备份素材、清点设备", "location": "", "cast": "全员", "equipment": "硬盘×2", "notes": "当日素材双备份后才可离开"})
    return {"title": f"《{topic}》拍摄通告单", "date": "待定", "items": items, "mode": "offline",
            **({"references": refs} if refs else {})}


async def rundown(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:4000]
            if case_ctx:
                user_content += f"\n\n参考案例(检索自案例库,请借鉴其 Rundown 结构、设备与经验,但必须适配用户需求):\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_RUNDOWN},
                 {"role": "user", "content": user_content[:6000]}], api_key=api_key)
            items = []
            for it in data.get("items", []) or []:
                if not isinstance(it, dict):
                    continue
                items.append({
                    "time": str(it.get("time", "")), "item": str(it.get("item", "")),
                    "location": str(it.get("location", "")), "cast": str(it.get("cast", "")),
                    "equipment": str(it.get("equipment", "")), "notes": str(it.get("notes", "")),
                })
            return {"title": str(data.get("title", "拍摄通告单")), "date": str(data.get("date", "待定")),
                    "items": items, "mode": "online", **({"references": refs} if refs else {})}
        except Exception as e:  # noqa: BLE001
            logger.warning("在线 rundown 失败(%s),回退离线", e)
    return offline_rundown(text, refs=refs)


# --------------------------------------------------------------------------
# 日程规划 schedule
# --------------------------------------------------------------------------
def offline_schedule(text: str, days: int = 2, refs: list = None):
    scenes = parse_scenes(text)
    topic = _pick_topic(text)
    if len(scenes) < 2:
        scenes = scenes or [["(场景待补充)"]]
    ref_case = refs[0] if refs else None
    per_day = max(1, (len(scenes) + days - 1) // days)
    out_days = []
    for d in range(days):
        chunk = scenes[d * per_day:(d + 1) * per_day]
        tasks = [{"time": "09:00", "task": f"Day {d + 1} 集合与设备准备", "location": "集合点", "notes": "检查天气,外景确认光线"}]
        t = 10 * 60
        for i, scene in enumerate(chunk):
            sname = scene[0][:20] if scene else f"场景 {d * per_day + i + 1}"
            t += 50
            tasks.append({
                "time": f"{t // 60:02d}:{t % 60:02d}",
                "task": f"拍摄:第{d * per_day + i + 1}场 {sname}",
                "location": (ref_case["locations"][0] if ref_case and ref_case.get("locations") else "内景/外景(按勘景确认)"),
                "notes": "同地点镜头集中拍,减少转场",
            })
        tasks.append({"time": "12:30", "task": "午餐与休息", "location": "", "notes": ""})
        tasks.append({"time": "13:30", "task": "下午拍摄/转场", "location": "待定", "notes": "预留 30 分钟转场缓冲"})
        tasks.append({"time": "18:00", "task": "收工与素材双备份", "location": "", "notes": ""})
        base_tip = ("外景安排在光线最好的时段(黄金时刻);如遇雨天,启用备份日或改拍内景。" if d == 0
                    else "最后一天预留补拍时间,优先补拍第 1 天的问题镜头。")
        if ref_case and d == 0:
            base_tip += f" 案例{ref_case['title']}的经验:{ref_case.get('lessons', '')[:60]}"
        out_days.append({"day": f"Day {d + 1}", "theme": "外景为主" if d == 0 else "内景与补拍", "tasks": tasks, "tip": base_tip})
    out = {"title": f"《{topic}》拍摄日程", "days": out_days, "mode": "offline"}
    if refs:
        out["references"] = refs
    return out


async def schedule(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:4000]
            if case_ctx:
                user_content += f"\n\n参考案例(检索自案例库,请借鉴其排期原则与转场安排,但必须适配用户需求):\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_SCHEDULE},
                 {"role": "user", "content": user_content[:6000]}], api_key=api_key)
            days = []
            for d in data.get("days", []) or []:
                if not isinstance(d, dict):
                    continue
                tasks = []
                for tk in d.get("tasks", []) or []:
                    if not isinstance(tk, dict):
                        continue
                    tasks.append({
                        "time": str(tk.get("time", "")), "task": str(tk.get("task", "")),
                        "location": str(tk.get("location", "")), "notes": str(tk.get("notes", "")),
                    })
                days.append({"day": str(d.get("day", "")), "theme": str(d.get("theme", "")), "tasks": tasks, "tip": str(d.get("tip", ""))})
            return {"title": str(data.get("title", "拍摄日程")), "days": days, "mode": "online",
                    **({"references": refs} if refs else {})}
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
    picks = (matched + rng.sample(rest, max(0, 3 - len(matched))))[:3]
    rng.shuffle(picks)
    out = {"concepts": picks, "mode": "offline",
           "note": f"离线模式从灵感库中抽取了 3 个示例{(f'(主题:「{topic}」)' if topic else '')}——接入 API 后可按你的关键词定制生成。"}
    if refs:
        out["references"] = refs
    return out


async def inspiration(text: str, api_key: str = None, case_ctx: str = "", refs: list = None):
    if llm.available(api_key):
        try:
            user_content = text[:2000] or "随机"
            if case_ctx:
                user_content += f"\n\n相关案例(检索自案例库,可作为灵感参照):\n{case_ctx}"
            data = await llm.complete_json(
                [{"role": "system", "content": prompts.PROMPT_INSPIRATION},
                 {"role": "user", "content": user_content[:6000]}], api_key=api_key)
            concepts = []
            for c in data.get("concepts", []) or []:
                if not isinstance(c, dict):
                    continue
                concepts.append({
                    "title": str(c.get("title", "")), "genre": str(c.get("genre", "")),
                    "logline": str(c.get("logline", "")), "hook": str(c.get("hook", "")),
                    "twist": str(c.get("twist", "")),
                })
            return {"concepts": concepts, "mode": "online", **({"references": refs} if refs else {})}
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
    text = (f"为你找到 {len(hits)} 部相关参考案例:{titles}。"
            "可以先看每部案例的拍摄 Rundown 与经验教训;需要的话告诉我你的想法,"
            "我帮你对照案例给出改编建议。(离线演示模式)")
    return {"text": text, "cases": hits, "steps": [{"tool": "search_cases", "query": query}], "mode": "offline"}


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------
async def run_tool(tool: str, message: str, api_key: str = None):
    import case_store

    if tool == "cases":
        return await cases_tool(message, api_key)
    # 创作类工具先检索相关案例,注入提示词(在线)或附到结果(离线)
    case_ctx, refs = "", []
    if tool in ("review", "storyboard", "rundown", "schedule", "inspiration"):
        try:
            ctx, refs = case_store.cases_context(message, k=2)
            case_ctx = ctx
        except Exception as e:  # noqa: BLE001
            logger.warning("案例检索失败: %s", e)
    if tool == "review":
        return await review(message, api_key, case_ctx, refs)
    if tool == "storyboard":
        return await storyboard(message, api_key, case_ctx, refs)
    if tool == "rundown":
        return await rundown(message, api_key, case_ctx, refs)
    if tool == "schedule":
        return await schedule(message, api_key, case_ctx, refs)
    if tool == "inspiration":
        return await inspiration(message, api_key, case_ctx, refs)
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
