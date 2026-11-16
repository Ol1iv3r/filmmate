# Filmmate 影视灵感目录（Catalog v1）说明

> 目标：把「用户灵感 → 选题材 → 创作思路 → 相似作品推荐」这条链路，接上一个真实、可点击、带静帧参考的影片库。

## 1. 交付物

| 文件 | 内容 |
|---|---|
| data/library/catalog.json | 机器可读总库（243 部，含 bvid/cid、原片链接、10 张静帧路径与时间码、检索标签、核验时间） |
| docs/film_catalog.xlsx | 主表（编号-种类-中文名-英文名-年份-时长-情绪-内容梗概-Tag-原片链接 + 静帧列），链接可点、带筛选 |
| docs/film_catalog.csv | 与主表同字段的 CSV（utf-8-sig，Excel 直接打开不乱码） |
| docs/FILM_CATALOG.md | Markdown 表格（按类目分组，每行带首帧缩略图与原片链接） |
| docs/catalog.html | 可浏览画廊：按种类/情绪筛选、关键词搜索、每部 10 张静帧、点图放大、一键跳 B 站 |
| static/frames/catalog/[BV号]/01-10.jpg | 每部 10 张代表性静帧（共 2430 张） |
| catalog.py | 检索层：search() / suggest() / prompt_block() / kind_options() |
| scripts/build_catalog.py | 构建管线：B 站搜索匹配 → 可播放校验 → storyboard 抽帧 → 导出 |
| scripts/catalog_export.py | 导出 CSV / Markdown / Excel / HTML 画廊 |

## 2. 数据链路（可复现）

    data/catalog_src/*.json（策展片单：电影/电视剧/长片/短片/竖屏短剧 各 65 条候选）
            |
            +- resolve：B 站搜索 API → 标题命中 + 时长匹配 + 播放量/类型打分
            |            → view 接口校验 → videoshot 校验（能抽到帧才算有效）
            |            匹配不上的候选直接丢弃，绝不硬凑链接
            |
            +- frames：官方 storyboard（10x10 拼图）→ 每部按 8%-94% 时间轴分 10 桶
            |           每桶内按「边缘细节/肤色(人物)/色彩/亮度/对比」打分
            |           去重（dHash）、避开片头字幕卡/片尾字幕、自动裁黑边
            |           竖屏短剧被塞进横屏画幅时自动裁成竖幅并 2x 放大
            |
            +- export：catalog.json + CSV/MD/XLSX + HTML 画廊

运行方式：

    .venv/bin/python scripts/build_catalog.py resolve     # 搜索匹配（可 --kinds 电影,短片）
    .venv/bin/python scripts/build_catalog.py frames      # 抽 10 张静帧
    .venv/bin/python scripts/build_catalog.py export      # 导出全部表格与画廊

## 3. 字段字典（catalog.json 每条）

| 字段 | 说明 |
|---|---|
| id | 编号：D=电影 / T=电视剧 / F=长片 / S=短片 / V=竖屏短剧，如 D007 |
| kind | 种类（五类之一） |
| title_zh / title_en | 中/英文名 |
| year | 首映/首播年份 |
| duration | 电影/长片/短片为片长；电视剧为「单集 x 分钟」；竖屏短剧为「N集xM分」 |
| moods | 受控情绪词 2-4 个（压抑/孤独/荒诞/温暖/紧张/悲凉/讽刺…） |
| synopsis | 60-110 字：主角 + 处境 + 核心冲突 + 钩子（不剧透结局） |
| tags | 4-8 个检索标签：题材/主题/结构/视觉/流派 |
| genre | 类型（悬疑/犯罪/家庭/动画/纪录片…） |
| bvid / url | B 站原片 BV 号与可播放链接（多 P 已定位到具体 P） |
| video_title / owner / play | 命中的投稿标题 / UP 主 / 播放量（判断是否为原片而非解说） |
| match_score | 匹配得分（标题x0.58 + 时长x0.30 + 播放x0.12） |
| verified_at | 链接/抽帧核验时间 |
| frames | 10 张静帧的 URL 路径 |
| frame_meta | 每张静帧的时间码（hh:mm:ss）、尺寸、质量分 |
| frame_dir | 静帧目录（static/frames/catalog/[BV号]） |

## 4. 推荐流程（产品侧的用法）

用户输入一句灵感（例：「一个外卖员在暴雨夜捡到一部手机，里面有一段不该看到的视频」）后：

1. **先选题材**：catalog.kind_options() 返回五类 + 每类代表作数与一句话定义；也可以用 catalog.suggest(idea) 的 kinds 字段给出「倾向题材」排序，作为推荐给用户的第一步选项。
2. **同题材/同情绪检索**：catalog.search(idea, kind=选中种类, k=6) → 返回真实作品（带原片链接与 10 张静帧）。
3. **生成思路**：把 catalog.prompt_block(idea) 塞进 LLM 提示词（tools.py 的 inspiration 工具已接入），让模型基于真实作品而不是空想给出 2-3 个可拍思路，并说明「借鉴了哪部片的哪一点」。
4. **配图参考**：把每部作品的 10 张静帧作为情绪板（frames / frame_meta 带时间码，需要高清图时按时间码回原片截取）。

命令行体验：

    python3 catalog.py "一个外卖员在暴雨夜捡到一部手机"

输出包含：可选题材、情绪/类型分布、6 部相似作品（片名/年份/时长/情绪/梗概/参考点/原片链接），以及可直接拷给 LLM 的提示词块。

## 5. 已做的校验

- **链接**：每部都过 /x/web-interface/view 确认可播放，且 /x/player/videoshot 能取到 storyboard 才收录；核验时间写入 verified_at。
- **时长**：以 B 站实际视频页时长（多 P 用对应 P 的时长）与真实片长比对，误差过大直接丢弃；电视剧允许匹配单集或整剧合集，竖屏短剧允许整剧合集（时长 = 单集x集数）。
- **反解说/反混剪**：标题含「解说/影评/吐槽/混剪/盘点/第一次看/陪看/翻跳/串联」等关键词降权或拒绝；标题里出现多个《》视为混剪；避免把 3 分钟剪辑当原片。
- **静帧**：同片内 dHash 去重、避开片头/片尾、自动裁黑边；竖屏短剧裁成竖幅。

## 6. 已知限制

- 静帧是 B 站播放器 storyboard 预览帧（约 480x270），不是 1080p 截图；已 2x 放大便于查看，需要高清图请按 frame_meta.timecode 回原片截取。
- 竖屏短剧被上传成横屏画幅时，裁出的竖帧分辨率较低（约 300x540），但内容完整。
- B 站投稿会下架/换源，链接可能失效；verified_at 是核验时间，重跑 resolve 可刷新。
- 类目口径：电影=院线/主流叙事长片；长片=独立/艺术/纪录长片；短片<=40 分钟；竖屏短剧=单集 1-3 分钟的竖屏微短剧。
- 版权：原片版权归原权利人/上传者，静帧仅用于创作学习与情绪板参考，不做二次分发。

## 7. 本版实际规模（自动生成）

| 种类 | 数量 | 说明 |
|---|---|---|
| 电影 | 43 | 严格剔除「评论音轨/音频版/图集/解说」等非原片后不足 50；其余候选仍留在库里，可用 build_catalog.py resolve 继续补 |
| 电视剧 | 50 | 单集或整剧合集，多 P 已定位到具体 P |
| 长片 | 50 | 独立/纪录/艺术长片，部分为分段/合集上传 |
| 短片 | 50 | 大部分复用项目原有 B 站已核验短片库 |
| 竖屏短剧 | 50 | 多为整剧合集/分集；被传成横屏的已裁成竖幅 |
| **合计** | **243** | **2430 张静帧（每部 10 张）** |

另有 7 部标注「静帧质量：低（画面重复度偏高）」，表示该上传版本画面变化少（如原声/图集类），可在导出表的「静帧质量」列筛选后人工复核或替换。


## 8. v2 更新（2026-11-16）：合并补充片单 + 错链纠正

### 8.1 合并用户补充的 CSV（120 条 YouTube 检索链接）

- 与库内已有片名去重后，28 条同名跳过，实际新增 71 条可用条目；
- 新增 4 个类目：广告/TVC、教程/产品演示、Vlog/美食、动画；
- 链接策略：Bilibili 优先；YouTube 原生内容（苹果/特斯拉官方片、美食 Vlog、广告等）走 YouTube：
  yt-dlp 检索 → 校验标题/时长 → 解析 YouTube 官方 storyboard 拼图抽 10 张静帧；
- 当前 261 条中：Bilibili 231 条、YouTube 31 条（表格「平台」列可筛）。

### 8.2 错链纠正（scripts/strict_clean.py）

针对「标题像、内容不是原片」的链接，按以下规则复核并重新匹配：

1. 内容词：解说 / 一口气看完 / 评论音轨 / OST / BGM / 剧场版 / 真人秀 / 音频 / 广播剧 / 花絮 / 预告 / 混剪 / 盘点 / 拉片 / 万字解读 / 全流程 / 通关 等；
2. 时长比例：单片 0.86–1.25；剧集需「单集 0.80–1.40」或「整剧合集 0.85–1.15」；短剧放宽；
3. 片名位置：片名必须在标题开头 / 《》/【】中，或英文名命中，否则要求时长高度吻合；
4. 静帧质量：10 张里互不相似少于 5 张 → 判定为静态图/幻灯片；
5. 同名去重：同一部作品只保留优先级最高的类目。

清掉了约 76 条不合格匹配；重新匹配后仍不合格的条目直接从目录移除（宁缺毋滥）。
表格新增「链接可信度」列：高 = 片名在主位且时长吻合；中 = 建议人工复核。

### 8.3 HTML 里看不到静帧的修复

之前 docs/catalog.html 用 ../static/... 相对路径，通过服务或某些预览器打开时解析不到。现在：

- 同时生成 docs/catalog.html（双击本地文件可用）和 static/catalog.html（由 Filmmate 服务提供）；
- 启动 Filmmate 后访问 http://127.0.0.1:8000/catalog 或 /static/catalog.html 即可看到每部 10 张静帧；
- 已验证：/catalog.html 与 frames/catalog/编号/01.jpg 均返回 200。

### 8.4 本版规模

| 种类 | 数量 |
|---|---|
| 电影 | 32 |
| 电视剧 | 35 |
| 长片（纪录/独立/艺术） | 45 |
| 短片 | 50 |
| 竖屏短剧 | 50 |
| 广告/TVC | 17 |
| 教程/产品演示 | 7 |
| Vlog/美食 | 16 |
| 动画 | 9 |
| **合计** | **261（2610 张静帧）** |

> 电影/电视剧数量比上一版减少，是因为「评论音轨 / 音频版 / 解说 / 静态图集 / 错片」被严格剔除；这些条目宁可不要，也不给用户错误链接。

### 8.5 复核与重建命令

    .venv/bin/python scripts/strict_clean.py              # 预览可疑链接
    .venv/bin/python scripts/strict_clean.py --apply      # 清空 + 自动重新匹配
    .venv/bin/python scripts/add_catalog_rows.py CSV路径  # 合并外部补充片单
    .venv/bin/python scripts/build_catalog.py export      # 重新导出表格/HTML


## 9. 在「找灵感」里怎么用这个库（v3）

- 入口：聊天输入区第一个 chip「找灵感」→ 选题材 → 描述感觉（例如「香港、雨夜、孤独」）。
- 检索：catalog.py 的 semantic_candidates(idea, kind) 只在该题材内检索，且带地点线索（香港→甜蜜蜜/花样年华/重庆森林/英雄本色；台北→一一/悲情城市/大佛普拉斯…），保证「选电影就只给电影」。
- 产出结构：风格（为什么契合）→ 主题（从零构思）→ 契合电影（内容 + 3 张静帧 + 原片链接），最多 3 组。
- 下一步：模型会反问是否出完整分镜；用户回复「出分镜」后，用 prompts.PROMPT_STORYBOARD_THEME 生成 8–10 镜分镜表。
- 相关文件：catalog.py（PLACE_HINTS / semantic_candidates）、tools.py（inspiration_films / storyboard_from_theme）、prompts.py（PROMPT_INSPIRATION_FILMS / PROMPT_STORYBOARD_THEME）、filmmate-web/src/components/Composer.tsx（题材选择 UI）。
