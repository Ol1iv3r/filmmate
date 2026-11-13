# 🎬 Filmmate · 影视创作 AI 助理

> **📁 仓库导航**：本目录是 2026-11-05 的 Python 原型（FastAPI + 原生 HTML/JS）。
> 团队正式栈（Tauri 2 + React + Vite + TS，Phase 1 聊天 UI + Phase 2 语音输入 + Phase 3 会话落盘 +
> Phase 4 工具调用可视化）在 **[`filmmate-web/`](filmmate-web/README.md)**，前后端消息契约在
> **[`filmmate-web/docs/CONTRACT.md`](filmmate-web/docs/CONTRACT.md)**。
> Phase 2 / Phase 3 的 Python 后端模块（`voice_input_api.py`、`chat_storage*.py`）在本目录根部，
> 由 `app.py` 一并注册。

**COMP4431 Artificial Intelligence (2026/27) Group Project — Domain-specific Chatbot**

一个面向影视/视频创作者的领域专属 AI 助理。定位是**辅助创作者做决策**,而不是替代创作:
帮创作者 **检查剧本漏洞 → 设计分镜 → 排拍摄 Rundown → 规划拍摄日程 → 找参考案例**,并回答
镜头语言、灯光、收音、剪辑等专业问题(中英双语)。

---

## 👥 组员信息(提交前填写)

| 姓名(Name) | 学号(Student ID) | 负责部分 |
|---|---|---|
| (你的名字) | (你的学号) | 后端 / LLM 集成 |
| (组员 2) | (学号) | RAG 知识库与案例库 |
| (组员 3) | (学号) | 前端 UI 与语音 |
| (组员 4,可选) | (学号) | 演示与测试 |

---

## ✨ 功能清单

### 基本功能(3/10)
1. **领域内沟通**:只围绕影视创作领域回答,领域外问题礼貌拒答并引导回创作话题;
2. **典型查询处理**:中英双语回答镜头语言(景别/机位/运镜)、灯光、收音、剪辑、拍摄流程、设备、香港取景地等专业问题;
3. **领域核心任务**:剧本检查、分镜建议、Rundown、日程规划等辅助任务。

### 附加功能(7/10)及实现方式

#### 1. RAG 知识库检索增强(双库检索)
- **专业知识库**(`knowledge/knowledge.json`,78 条):景别、机位、运镜、灯光、收音、剪辑、拍摄流程、香港取景、设备;
- **作品案例库**(`cases/cases.json`,10 部完整案例):每部含剧本梗概、分镜要点、拍摄 Rundown、设备清单与经验教训;
- 检索实现(`rag.py` / `case_store.py`):中文用 jieba 分词 + **Okapi BM25** 关键词检索;
  安装 `sentence-transformers` 后自动升级为 **dense 向量 + 余弦相似度**检索(向量缓存到 `*/vectors/` 下);
- 回答**附带来源引用**(知识条目 / 参考案例),不编造。

#### 2. 模型自主工具调用(Agent / Function Calling)
- 后端向 DeepSeek 声明两个检索工具 `search_knowledge` / `search_cases`(`llm.py` 的 `TOOLS_SCHEMA`);
- **模型自己决定**何时调用哪个工具、用什么关键词,后端执行真实检索,结果回填后模型再生成最终回答;
- 前端实时展示调用过程(🔧 search_cases(…)),演示时可直观看到 Agent 工作流;
- 无 API 时由规则路由器等价降级(离线模式)。

#### 3. 基于案例的生成(案例库 → 提示词)
- 用户用"分镜/Rundown/日程/灵感/审稿"时,先检索相关案例,把案例作为**高质量样本注入提示词**,
  模型借鉴其结构与经验、适配用户需求后输出(`tools.py` 中 case_ctx 注入);
- 离线模式下同样把案例附在结果中,并据案例填充设备/地点。

#### 4. 语音识别与合成
- 语音输入:浏览器 **Web Speech API(SpeechRecognition)**,支持普通话/粤语/英语,点 🎤 说话输入;
- 语音输出:**SpeechSynthesis** 朗读 AI 回答(每条回答带 🔊 按钮);
- 完全免费、无需训练、无需第三方服务。

#### 5. 结构化工具输出 + 友好界面
- 剧本检查:评分 + 漏洞卡片(严重程度/类型/原文引用/修改建议)+ 优点 + 下一步建议;
- 分镜建议:每个镜头一张 **SVG 简笔画草图**(按景别/机位自动生成构图)+ 景别/机位/运镜/时长标注;
- Rundown / 日程:**表格化呈现 + 一键导出 CSV**(带 BOM,Excel 直接打开);
- 灵感:概念卡片(梗概/钩子/反转);
- 电影风格深色 UI、流式输出(SSE)、聊天历史上下文(最近 6 轮)。

#### 6. 工程可靠性
- **离线演示模式**:未配置 API Key 时全部功能仍可用(本地检索 + 启发式剧本检查 + 模板生成),现场断网不翻车;
- JSON 输出自动校验/修复/重试;在线失败自动回退离线。

---

## 🏗️ 架构

```
浏览器 (static/ HTML+CSS+JS)
  ├─ 语音输入 SpeechRecognition · 语音合成 SpeechSynthesis
  └─ POST /api/chat (SSE 流式)
        │
        ▼
FastAPI 后端 (app.py)
  ├─ 意图路由 (tools.detect_tool): 问答 / 剧本检查 / 分镜 / rundown / 日程 / 灵感 / 案例
  ├─ Agent 循环 (llm.chat_with_tools): 模型自主调用检索工具
  │     ├─ search_knowledge ──► rag.py  ──► knowledge.json (BM25 / dense 向量)
  │     └─ search_cases     ──► case_store.py ──► cases.json   (BM25 / dense 向量)
  ├─ 创作工具 (tools.py): 检索案例 → 注入提示词 → DeepSeek 结构化 JSON → 前端渲染
  └─ 离线降级: 本地检索 + 启发式规则(时间线/人物去向/伏笔/对白检查) + 模板生成
        │
        ▼
DeepSeek API (deepseek-chat, OpenAI 兼容接口;httpx 异步)
```

---

## 🚀 运行方法

要求:Python 3.9+,联网(在线模式需要)。

```bash
# 1. 安装依赖(核心依赖都很轻量)
pip install -r requirements.txt

# 2. (可选)配置 API Key —— 两种方式任选:
#    a) 复制 .env.example 为 .env,填入 DEEPSEEK_API_KEY=sk-...
#    b) 不配置,启动后在网页右上角 ⚙️ 设置里粘贴 Key(仅存本机浏览器)
#    不配置 Key 也能运行:自动进入"离线演示模式",全部功能可用

# 3. 启动
python app.py
# 浏览器打开 http://127.0.0.1:8000
```

可选:开启向量检索模式(默认自动检测)
```bash
pip install sentence-transformers   # 首次运行会下载多语言模型并缓存向量
```

### 7 分钟演示脚本建议
1. **剧本医生**(约 1.5 min):发送一段埋了 3 个漏洞的剧本(时间跳变、角色消失、伏笔未回收)
   → AI 逐一找出,按严重程度分类 + 原文引用 + 修改建议(强调"辅助人决策"的定位);
2. **分镜建议**(约 1.5 min):点"分镜建议"→ 展示 SVG 分镜卡片(景别/机位/运镜),指出它借鉴了哪个参考案例;
3. **语音问答**(约 1 min):点 🎤 说"拍夜景需要准备什么灯光?" → RAG 回答 + 知识库引用 + 🔊 朗读;
4. **参考案例**(约 1 min):输入"有没有校园爱情短片案例" → 展示模型调用 search_cases 的过程与案例卡片;
5. **Rundown/日程**(约 1 min):生成通告单 + 导出 CSV;
6. 讲实现(RAG 双库、Agent 工具调用、提示词注入案例)+ 挑战与限制(约 1.5 min)。

---

## 📁 文件结构

```
├── app.py               # FastAPI 入口,SSE 流式 /api/chat
├── config.py            # 配置(读 .env / 环境变量)
├── llm.py               # DeepSeek 客户端 + Agent 工具调用循环
├── prompts.py           # 系统提示词与各工具 JSON 规范
├── rag.py               # 专业知识库检索(BM25 / dense)
├── case_store.py        # 案例库检索 + 案例上下文构建
├── tools.py             # 意图识别 + 五个创作工具(在线/离线双实现)
├── voice_input_api.py   # Phase 2:语音转写 /api/transcribe(whisper-1)
├── chat_storage.py      # Phase 3:会话 JSON 存储(原子写/加锁/损坏隔离)
├── chat_storage_api.py  # Phase 3:/api/conversations REST(5 个路由)
├── chat_storage_langchain.py # Phase 3:LangChain 消息 ↔ dict(预留,未接线)
├── requirements.txt
├── .env.example
├── knowledge/knowledge.json   # 专业知识库(78 条)
├── cases/cases.json           # 作品案例库(10 部)
├── data/conversations/        # Phase 3 运行后生成(已 .gitignore)
└── static/
    ├── index.html       # 聊天界面
    ├── style.css        # 电影风深色主题
    └── app.js           # SSE 渲染、语音、分镜 SVG、CSV 导出
```

---

## ⚠️ 已知限制

- 离线模式的剧本检查基于启发式规则(时间线/人物去向/对白长度/伏笔),无法做动机、潜台词层面的深度审阅;
- 本 README 的语音输入指 `static/` 原型用的浏览器 Web Speech API;Tauri/React 版的语音输入是 whisper-1(经 `voice_input_api.py`),见 `filmmate-web/README.md`;
- 语音识别依赖浏览器支持(推荐 Chrome),首次使用需授权麦克风;
- BM25 检索对同义词不敏感,装了 sentence-transformers 的向量模式效果更好;
- 聊天上下文保留最近 6 轮;案例库为示例数据(10 部),可按同样格式继续扩充;
- 航拍等法规信息以官方发布为准。
