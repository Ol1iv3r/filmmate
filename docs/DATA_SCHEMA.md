# Filmmate 数据层 Schema v2

> 目标：把「50 个视频 + 78 条知识 + 10 个案例」的薄数据，扩成一套**能直接支撑专业输出**的资料库：
> 灵感 → 剧本覆盖（coverage）→ 分镜（shot list）→ 通告单（stripboard / call sheet）→ 多日日程（DOOD）。
>
> 所有文件均为 **UTF-8 JSON**，不要注释、不要尾逗号。中文为主，专业术语中英对照。

---

## 0. 目录约定

```
knowledge/knowledge.json          # 原有 78 条问答知识（保留，追加 category）
data/library/knowledge_extra.json # 新增：剧本审阅/制片/通告单/安全等条目
data/library/scenes.json          # 新增：场面模式库（scene patterns）
data/library/shots.json           # 新增：镜头模式库（shot patterns）
data/library/stripboards.json     # 新增：通告单/日程模板（可复用的生产计划）
data/library/films_real.json      # 真实短片库（Bilibili API 校验；取代全部虚构案例）
data/library/samples_enriched.json# 由脚本生成：50 个视频样本的专业化富化
```

**真实性原则（2026-11-13 修订）**：所有「案例」必须是可核验的真实短片，带 `bvid`、`url`、`verified_at`。
禁止再生成「合成教学案例」，也禁止为真实影片编造预算、档期、分镜、通告单等平台不提供的字段。

---

## 1. 知识条目 `knowledge_extra.json`

```json
{
  "name": "Filmmate 影视创作知识库 · 扩充卷",
  "description": "剧本审阅、场面调度、制片与通告单、香港拍摄实务",
  "entries": [
    {
      "id": "cov-chekhov-gun",
      "category": "剧本审阅",
      "title": "契诃夫之枪（Chekhov's Gun）",
      "keywords": ["伏笔", "契诃夫之枪", "setup", "payoff", "道具", "回收"],
      "content": "第一幕出现的道具/信息，第三幕必须兑现，否则观众会觉得被耍。检查方法：把每场出现的特殊道具、台词里的承诺、人物技能列成清单，逐一问「它在后面用上了吗」。若只是气氛道具，就不要给它特写或专门台词——镜头与台词本身就是承诺。",
      "applies_to": ["review", "inspiration"],
      "level": "core"
    }
  ]
}
```

约束：
- `id`：`kebab-case`，全局唯一，前缀体现类别（`cov-` 审阅、`prod-` 制片、`sb-` 通告单、`sched-` 排期、`biz-` 预算、`hk-` 香港、`safe-` 安全、`genre-` 类型、`block-` 调度、`sound-` 声音、`edit-` 剪辑）。
- `category` 只能取：`剧本结构` `剧本审阅` `人物` `对白` `类型片` `场面调度` `景别` `机位` `运镜` `灯光` `收音` `剪辑` `调色` `制片` `通告单` `场记` `预算` `勘景` `香港拍摄` `安全法规` `后期交付` `AI辅助`。
- `content`：**80–200 字**，必须给可执行方法/判断标准/常见错误，禁止空泛套话。
- `keywords`：4–8 个，中英混合，包含用户可能输入的口语说法。
- `applies_to`：`qa` `inspiration` `review` `storyboard` `rundown` `schedule` 的子集。
- `level`：`core` | `advanced`。

---

## 2. 场面模式 `scenes.json`

一个「场面」= 有戏剧功能的一段戏（不是地点）。用于：灵感生成、剧本漏洞检查、分镜起手、时间估算。

```json
{
  "name": "场面模式库",
  "scenes": [
    {
      "id": "scene-rooftop-confession",
      "name_zh": "天台告白",
      "name_en": "Rooftop Confession",
      "genre": ["爱情", "青春", "剧情"],
      "dramatic_function": "关系转折 / 情感高点",
      "beat_structure": ["试探靠近", "用闲话拖延", "被第三方打断", "终于说出口", "留白收尾"],
      "conflict": "想说又怕毁掉现有关系",
      "subtext": "两人谈的是天气，说的是「你会不会留下」",
      "staging": "两人始终不同框到最后一拍；用栏杆/晾衣绳做前景分隔，最后才越过界线同框",
      "shots": [
        {"size": "全景", "angle": "平视", "movement": "固定", "purpose": "交代天台空间与两人的物理距离"},
        {"size": "近景", "angle": "过肩", "movement": "固定", "purpose": "正反打，制造「不敢看对方」"},
        {"size": "特写", "angle": "平视", "movement": "微推", "purpose": "说到关键句时推近，压缩空间"}
      ],
      "lighting": "城市夜景实用光为主，人物侧后方一盏 LED 棒做轮廓；避免正面大平光",
      "sound": "环境声（远处车流、风声）压低对白间隙；不用配乐，最后一句后才进音乐",
      "duration_sec": 150,
      "page_eighths": 6,
      "shoot_minutes": 120,
      "common_pitfalls": ["一开口就说重点，没有试探过程", "两个人一直同框，没有距离变化", "用旁白解释心理"],
      "fix": "把「说出口」拆成三次尝试，前两次被自己或环境打断；用走位制造距离变化",
      "budget_tier": "low",
      "keywords": ["天台", "告白", "夜景", "浪漫", "关系转折", "rooftop", "confession"]
    }
  ]
}
```

约束：
- 40 个以上；覆盖 `爱情` `悬疑` `喜剧` `恐怖` `动作` `科幻` `家庭` `青春` `犯罪` `广告`。
- `beat_structure` 4–6 拍，必须是**可拍的 action**，不是抽象情绪。
- `shots` 3–6 个，`size`/`angle`/`movement` 必须取自 Filmmate 现有枚举（见 §6）。
- `page_eighths`：1–12 的整数（1 = 1/8 页）。`shoot_minutes`：30–240 的整数。
- `common_pitfalls` 2–4 条，`fix` 一条具体做法。

---

## 3. 镜头模式 `shots.json`

```json
{
  "name": "镜头模式库",
  "shots": [
    {
      "id": "shot-dutch-tilt-reveal",
      "name_zh": "荷兰角揭示",
      "name_en": "Dutch Angle Reveal",
      "size": "中景",
      "angle": "荷兰角",
      "movement": "固定",
      "lens": "24mm",
      "frame_rate": "24fps",
      "lighting": "单侧硬光，留大面积阴影",
      "sound": "低频 drone + 突然静音",
      "purpose": "让观众潜意识感到「不对劲」，用于信息揭示前",
      "best_for": ["悬疑", "心理惊悚", "反派登场"],
      "pitfalls": ["整场都用荷兰角会失效，只在一个转折点用", "角度过大会变成滑稽"],
      "example_use": "主角打开抽屉发现照片被换掉的那一刻，镜头轻微倾斜 12°",
      "duration_range": "2-4s",
      "keywords": ["荷兰角", "倾斜", "不安", "dutch angle", "揭示"]
    }
  ]
}
```

约束：60 个以上；覆盖景别/机位/运镜/镜头焦段/特殊镜头（插入镜头、反应镜头、establishing、POV、OTS、whip pan、dolly zoom、微距、航拍、水下、镜面、遮挡转场）。`lens` 用真实焦段，`duration_range` 形如 `"2-4s"`。

---

## 4. 通告单模板 `stripboards.json`

直接对标专业 stripboard / call sheet（见用户提供的 Touring Man 样例）。用于「排 Rundown」和「排日程」时给模型一个真实结构参照。

```json
{
  "name": "通告单与拍摄日程模板",
  "templates": [
    {
      "id": "sb-1day-commercial",
      "name": "单日广告通告单（1 天 / 单场景）",
      "type": "广告",
      "shoot_days": 1,
      "crew_call": "07:30",
      "cast_call": "08:30",
      "wrap": "19:30",
      "locations": [
        {"name": "便利店（内景）", "int_ext": "INT", "permit": "店铺租赁 1 天", "notes": "夜戏需遮光"}
      ],
      "cast": [{"name": "女主 A", "role": "顾客", "days": [1]}, {"name": "店员 B", "role": "配角", "days": [1]}],
      "scenes": [
        {
          "scene_no": 1, "int_ext": "INT", "heading": "便利店 - 夜",
          "synopsis": "女主在货架前犹豫，拿起又放下", "cast": ["女主 A"],
          "day_night": "NIGHT", "pages_eighths": 2, "est_minutes": 75,
          "location": "便利店（内景）", "notes": "先拍全景定空间，再拍手部特写"
        }
      ],
      "blocks": [
        {"type": "crew_call", "time": "07:30", "note": "集合、早餐、设备清点", "est_minutes": 30},
        {"type": "setup", "time": "08:00", "note": "布光 + 机位测试", "est_minutes": 60},
        {"type": "scene", "time": "09:00", "scene_no": 1, "est_minutes": 75, "note": "按分镜顺序连拍"},
        {"type": "move", "time": "10:15", "note": "// COMPANY MOVE TO 天台 //", "est_minutes": 30},
        {"type": "meal", "time": "13:00", "note": "// MEAL BREAK //", "est_minutes": 60},
        {"type": "scene", "time": "14:00", "scene_no": 2, "est_minutes": 90, "note": ""},
        {"type": "wrap", "time": "19:30", "note": "素材双备份、设备清点", "est_minutes": 30}
      ],
      "totals": {"pages_eighths": 9, "shoot_minutes": 480, "company_moves": 1, "meals": 1},
      "checklist": ["场地钥匙", "艺人肖像授权", "产品道具备份 2 份"],
      "tips": ["广告客户通常现场改脚本，预留 1 小时补拍"]
    }
  ]
}
```

约束：6 个以上模板，覆盖：单日广告、单日产品 demo、音乐录影（MV）、3 分钟剧情短片（2–3 天）、纪录访谈（1 天）、企业宣传片、低成本长片（8–12 天）。
`blocks[].type` 只能取 `crew_call` `cast_call` `setup` `scene` `move` `meal` `wrap` `buffer`。
`totals.pages_eighths` 与 scenes 求和一致；`shoot_minutes` 与 blocks 求和一致（允许 ±5 分钟误差）。

---

## 5. 真实短片库 `films_real.json`

> 2026-11-13 起，**所有虚构案例（含早期 10 部 + 生成式 9 部）已从检索中移除**。
> 案例库改为「真实短片库」：只保存 Bilibili 公开 API 可核验的元数据，
> **不写导演/预算/档期/分镜/通告单**——这些平台并不提供，写出来就是编造。

```json
{
  "name": "Filmmate 真实短片库",
  "source": "api.bilibili.com",
  "verified_at": "2026-11-13T20:42:28+08:00",
  "count": 78,
  "films": [
    {
      "id": "bili-BV1GJ411x7h7",
      "bvid": "BV1GJ411x7h7",
      "title": "调音师",
      "title_raw": "调音师（2011年卢纹国际电影节最佳短片奖…）",
      "summary": "阿德里安是一名天才钢琴家……",
      "url": "https://www.bilibili.com/video/BV1GJ411x7h7",
      "cover": "https://i1.hdslb.com/bfs/archive/xxx.jpg",
      "duration_sec": 817,
      "duration": "13:37",
      "owner": "UP 主昵称",
      "pubdate": "2024-05-01",
      "description": "平台简介原文（截断 400 字）",
      "category": "动画 | 真人 | 短片",
      "signals": ["获奖", "学生作品", "动画"],
      "tags": ["亲情", "反转", "默片"],
      "stat": {"view": 275415, "like": 12000},
      "source": "bilibili",
      "verified_at": "2026-11-13T20:42:28+08:00"
    }
  ]
}
```

约束：
- `bvid` 唯一，`url` 必须包含该 `bvid`；
- 所有字段必须来自 API 响应，`verified_at` 是最近一次校验时间；
- **禁止**新增 `budget` / `shoot_days` / `stripboard` / `shot_list` / `scenes` 等字段；
- 封面直链来自 `i0/i1/i2.hdslb.com`，前端 `<img referrerpolicy="no-referrer">` 展示；
- `frames[]`：从 B 站 `videoshot` 帧拼图裁出的 6 张真实画面，路径 `/static/frames/<bvid>/frame-0N.jpg`；
- 版权归原作者，仅存元数据与链接，不下载/不转存视频。

重建：`python3 scripts/build_real_films.py --limit 80`（需要能访问 `api.bilibili.com`）。

> **YouTube 说明**：本项目开发机上 `youtube.com` 与 `i.ytimg.com` 不可达，
> 无法核验 YouTube 视频是否仍然有效，因此**没有新增任何 YouTube 条目**；
> 仓库里原有的 50 条 YouTube 样本是组员此前收集的，保留原始 ID，但未在本次重新校验。

### 5b. 「剧本 + 原片」双源库 `films_scripted.json`

人工片单在 `curated_script_films.json`（slug / 英文名 / 中文名 / 情绪标签 / 真实片长），
`scripts/build_scripted_films.py` 逐部校验两件事：

1. `https://www.scriptslug.com/script/<slug>` 页面 200，且
   `https://assets.scriptslug.com/live/pdf/scripts/<slug>.pdf` 可访问；
2. Bilibili 搜索结果里存在**片长误差 ≤ 15 分钟、单 P、标题命中且非解说/原声/游戏**的原片，
   再经 `api.bilibili.com/x/web-interface/view` 复核。

```json
{
  "id": "bili-BV1EV8M6hEgi",
  "bvid": "BV1EV8M6hEgi",
  "title": "寄生虫",
  "title_en": "Parasite",
  "year": "2019",
  "url": "https://www.bilibili.com/video/BV1EV8M6hEgi",
  "cover": "https://i1.hdslb.com/...jpg",
  "duration": "2:11:55",
  "duration_sec": 7915,
  "owner": "UP 主",
  "play": 2784,
  "moods": ["压抑", "荒诞", "黑色幽默"],
  "script": {
    "page": "https://www.scriptslug.com/script/parasite-2019",
    "pdf": "https://assets.scriptslug.com/live/pdf/scripts/parasite-2019.pdf"
  },
  "sources": ["scriptslug", "bilibili"],
  "verified_at": "2026-11-13T21:03:52+08:00"
}
```

匹配不到的影片写入顶层 `misses`，**不得**放宽标准硬凑。

### 5c. 个人灵感库（本机）

`data/personal/films.json`（已 gitignore）：用户粘贴 Bilibili 链接 + 情绪标签即可收藏；
服务端用公开 API 补全标题/封面/时长，条目会混入灵感输出并标注「我的」。不上传、不转存视频。

### 方法与模板数据（非影片档案）

`scenes.json` / `shots.json` / `stripboards.json` 是**编辑整理的方法库与行业模板**，
参考《Film Art》《The Grammar of the Film Language》《Shot by Shot》《Save the Cat》等公开教材的通用做法，
不代表任何一部真实影片的实际拍摄资料；UI 中也按「模板/模式」标注。

## 6. 枚举（前后端与提示词共用）

- `size` 景别：`远景` `全景` `中景` `近景` `特写` `大特写`
- `angle` 机位：`平视` `俯拍` `仰拍` `鸟瞰` `过肩` `荷兰角`
- `movement` 运镜：`固定` `推` `拉` `摇` `移` `手持` `稳定器跟随`
- `int_ext`：`INT` `EXT` `INT/EXT`
- `day_night`：`DAY` `NIGHT` `DAWN` `DUSK`
- `blocks.type`：`crew_call` `cast_call` `setup` `scene` `move` `meal` `wrap` `buffer`

---

## 7. 质量与校验

1. 所有 JSON 必须能被 `python -c "json.load(...)"` 解析；
2. `id` 全局唯一；枚举值不得自创；
3. `page_eighths` 与 `est_minutes` 要符合行业经验：**1 页 ≈ 8/8，剧情片 1 页 ≈ 60–90 分钟拍摄**，动作/特效场另计；
4. 禁止出现真实影片的**虚构**预算、档期、通告单；真实影片只能引用公开事实；
5. 语言：中文为主，专业术语保留英文（stripboard / call sheet / DOOD / coverage / blocking）。
