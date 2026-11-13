# Changelog

## [0.4.0] — 2026-11-13

这一版的重点：**数据必须可核验**、**灵感与参考合并**、**剧本驱动创作工具**、**界面极简**。

### Added

- **剧本上传**：`POST /api/script/parse`，支持 PDF / DOCX / TXT / MD / Fountain（≤15 MB），
  服务端解析（pypdf / python-docx）；剧本检查、分镜、Rundown、日程在无剧本时会先提示上传。
- **剧本 + 原片双源库**：`data/library/films_scripted.json`。
  每部电影必须同时满足 scriptslug 剧本 PDF 可访问、Bilibili 有原片（片长误差 ≤15 分钟、单 P、非解说/原声/游戏）。
  当前 16/36 部匹配成功，未匹配的 20 部写入 `misses`，不硬凑。
- **真实短片库**：`data/library/films_real.json`，78 部 Bilibili 短片/动画元数据 + 504 镜头解析。
- **灵感与参考合并**：删除单独的「参考案例」入口，改为一个「灵感」：
  3 个概念 + 按情绪分组（孤独/温暖/压抑/荒诞/浪漫/紧张…）的真实电影静帧。
- **逐帧静帧**：`scripts/build_frames.py` 从 B 站 `videoshot` 10×10 帧拼图裁出 6 帧/部，
  存 `static/frames/<bvid>/`；卡片用真实画面，点开可看 6 帧大图 + 剧本/原片链接。
- **个人灵感库**：`data/personal/films.json`（本机、gitignore）。
  粘贴 Bilibili 链接 + 情绪标签 + 可选剧本 PDF，自动补全封面/时长/静帧，混入情绪分组并标「我的」。
- **数据工程**：`library.py` 统一加载场面/镜头/通告单模板/样本；`scripts/validate_data.py`、
  `scripts/eval_retrieval.py`（19/19）、`scripts/export_film_database.py`。
- **数据库导出**：`docs/FILM_DATABASE.md`、`docs/film_database.xlsx`、`docs/film_database.csv`，
  16 部片的 B 站 / 剧本页 / PDF 链接均实时核验。
- **界面极简**：只保留顶部 Filmmate logo、中间对话区、底部功能栏与输入框；
  移除顶部导航、状态徽章、设置抽屉、示例剧本卡片。

### Changed

- 问答 Agent 扩到 5 个检索工具：`search_knowledge` / `search_cases` / `search_scenes` /
  `search_shots` / `search_stripboards`。
- Rundown 输出升级为 stripboard（场次/INT-EXT/页数 1/8/company move/meal/cast calls/合计）；
  分镜升级为 shot list（coverage、焦段、光线、声音、目的、转场）；日程升级为 DOOD。
- 离线模式同样生成上述结构，不依赖 API Key。
- 检索修复：短查询（如「香港」）按标题/分类字面命中放行，不再被 BM25 阈值误判。
- `.gitignore` 放行 `data/library/*.json`，继续忽略 `.env`、`data/personal/`、会话数据。

### Removed

- 删除全部虚构案例：原型 10 部 + 生成的 9 部「合成教学案例」（`cases/cases.json`、`cases_extra.json`）。
- 删除「封面当静帧」的做法，改为真实帧。

### Notes

- YouTube 在开发环境不可达，未新增任何未核验的 YouTube 链接。
- 静帧为 B 站播放器预览帧（480×270），不是 1080p 原片截图。
- 剧本为 scriptslug 英文剧本，版权归原作者，仅作学习参考。

---

## [0.3.0] — 2026-11-13

- Phase 2 语音输入（whisper-1）+ Phase 3 会话 JSON 落盘（组员提交）。

## [0.2.0] — 2026-11-12

- Phase 1 聊天 UI + Phase 4 tool-call 可视化（Tauri/React 前端）。
