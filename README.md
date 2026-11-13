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

### ⚡ 一键启动:双击 `start.bat`(Windows,推荐)

`start.bat` 会同时拉起 **Python 后端**(`app.py`)和 **React 前端**(`npm run dev`),
关闭窗口或按 `Ctrl+C` 时两个进程一起结束。

首次准备(只需一次):

```bash
# 1) 仓库根目录:Python 虚拟环境 + 后端依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 前端依赖
cd filmmate-web
npm install
cd ..
```

配置 Key(**语音输入必须**,聊天按需):

```ini
# 仓库根目录 .env(复制 .env.example 后填写)
AI_GATEWAY_API_KEY=vck_...     # 默认:经 Vercel AI Gateway 调用 openai/whisper-1
# 或直连 OpenAI:
OPENAI_API_KEY=sk-...
```

```ini
# filmmate-web/.env(复制 filmmate-web/.env.example 后填写)
VITE_TRANSCRIBE_BASE=http://127.0.0.1:8000   # 语音输入后端
VITE_API_BASE=http://127.0.0.1:8000          # 聊天 / 会话落盘后端(可留空 = Mock 演示)
VITE_REMOTE_CONVERSATIONS=1                  # 1 = 会话落盘;0 = 浏览器 localStorage
```

然后**双击 `start.bat`**,浏览器打开 **http://localhost:5173**:

| 进程 | 地址 | 提供 |
|---|---|---|
| Python 后端 | http://127.0.0.1:8000 | `/api/chat`、`/api/transcribe`、`/api/conversations` |
| Vite 前端 | http://localhost:5173 | Tauri 2 + React 聊天界面 |

> macOS / Linux 没有 `start.bat`,手动开两个终端:根目录 `python app.py`,`filmmate-web` 里 `npm run dev`。

### 🐍 只跑 Python 原型(任意系统)

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

## 🎙️ Phase 2 · 语音输入(voice input)

点麦克风 → 说话 → 再点一次停止 → whisper-1 转写 → **文字回填输入框,永不自动发送**。

### 文件分工

| 文件 | 角色 |
|---|---|
| `voice_input_api.py` | 后端 `POST /api/transcribe`:校验音频 → 转发上游 → 返回 `{"text": "..."}`;密钥只在服务端 |
| `filmmate-web/src/hooks/useVoiceInput.ts` | 录音状态机 `idle → requesting → recording → transcribing`;持有 MediaRecorder,任何退出路径都释放麦克风 |
| `filmmate-web/src/lib/voiceInput.ts` | 选择录音 MIME(webm/opus 优先)、检测环境支持、格式化计时 |
| `filmmate-web/src/lib/voiceInputApi.ts` | 浏览器端上传音频,把 401/413/429/504 等错误翻译成用户可读文案 |
| `filmmate-web/src/lib/voiceInputMerge.ts` | 把转写文本并入已有草稿(只补一个空格,不覆盖已输入内容) |
| `filmmate-web/src/components/MicButton.tsx` | 麦克风按钮:idle / 录音中(显示计时)/ 转写中 |
| `filmmate-web/src/components/Composer.tsx` | 接线:`onTranscript` → `mergeTranscript` → 写入输入框 |

### 工作流程

1. 点麦克风 → `getUserMedia` 申请权限 → `MediaRecorder` 以 32 kbps 开始录音(`webm/opus`);
2. 再点一次 / 按 `Enter` → 停止录音,得到音频 `Blob`;
3. `transcribeAudio()` → `POST {VITE_TRANSCRIBE_BASE}/api/transcribe`(multipart,`file=<audio>`);
4. 后端检查空音频与 25 MB 上限 → 转发上游 → 返回 `{ "text": "..." }`;
5. 前端 `mergeTranscript()` 把文字补到光标处,**不发送**,由用户自己按 Enter;
6. 录音中按 `Esc` 取消;短于 400 ms 视为误触;最长 120 s 自动停止。

### 使用的模型

| 项 | 值 |
|---|---|
| 模型 | `openai/whisper-1`(Gateway 默认)/ `whisper-1`(直连 OpenAI) |
| 默认上游 | Vercel AI Gateway `POST /v4/ai/transcription-model`(JSON + base64) |
| 备选上游 | OpenAI `POST /v1/audio/transcriptions`(标准 multipart) |
| 语言 | `TRANSCRIBE_LANGUAGE`(如 `zh` / `en` / `yue`),不填自动识别 |
| 术语提示 | `TRANSCRIBE_PROMPT`(仅直连 OpenAI 生效) |
| 限制 | 25 MB / 60 s 超时 |

> ⚠️ AI Gateway 的 `/v1/audio/transcriptions` 不存在(会 404),转写必须走 v4 端点;
> `MediaRecorder` 给的 `audio/webm;codecs=opus` 会先去掉 `;codecs=…` 再转发。

---

## 💾 Phase 3 · 会话落盘(chat storage)

聊天记录 → `UIMessage[]` → dict → **每个会话一个 JSON 文件**,刷新 / 重启后仍在。

### 文件分工

| 文件 | 角色 |
|---|---|
| `chat_storage.py` | 存储核心:原子写入(`.tmp` + `os.replace`)、按会话 id 加锁、id 正则校验、损坏文件隔离、标题推导 |
| `chat_storage_api.py` | 5 个 REST 路由 + Pydantic 校验,把存储异常翻译成 400 / 404 / 500 |
| `chat_storage_langchain.py` | 预留:LangChain `BaseMessage.to_dict()` ↔ dict(未接线,未加入 requirements) |
| `filmmate-web/src/lib/conversations.ts` | `ConversationRepository` 接口:`LocalRepository`(localStorage)/ `RemoteRepository`(REST),按环境变量选择 |
| `app.py` | 注册 `/api/transcribe` 与 `/api/conversations` 两个 router |

### 工作流程

1. **新建会话** → `PUT /api/conversations/<id>`,body `{"messages": []}` → 生成 `<id>.json`,标题暂为「新对话」;
2. **自动保存** → 发送消息后 500 ms debounce,以及回复结束(`ready` / `error`)时强制保存 → `PUT` 全量 `messages` → 原子重写文件;标题自动取第一条 user 消息(截 24 字);
3. **侧栏列表** → `GET /api/conversations` → 读取目录下所有 JSON 的 `id / title / createdAt / updatedAt`,按 `updatedAt` 倒序;
4. **打开会话** → `GET /api/conversations/<id>` → 返回 `{ messages }`;
5. **重命名** → `PATCH /api/conversations/<id>`;**删除** → `DELETE /api/conversations/<id>`。

### 落盘格式

`data/conversations/<id>.json`:

```json
{
  "version": 1,
  "id": "conv-m3k2j1-a1b2c3",
  "title": "第四場夜戲,先拍全景再切近景。",
  "createdAt": 1762900000000,
  "updatedAt": 1762900131000,
  "messages": [
    { "id": "m1", "role": "user",
      "parts": [{ "type": "text", "text": "第四場夜戲,先拍全景再切近景。" }] },
    { "id": "m2", "role": "assistant",
      "parts": [{ "type": "text", "text": "收到,先 wide shot 再 close-up。" }] }
  ]
}
```

- `messages` 就是前端 `UIMessage[]` 原样落盘(text / tool-call / reasoning 等 part 都保留);
- `createdAt` / `updatedAt` 是**毫秒时间戳**(number),与前端 `ConversationMeta` 一致;
- `version` 用于 schema 演进:未知版本只跳过,不擅自改写。

### 存储位置

| 项 | 值 |
|---|---|
| 默认目录 | 仓库根目录 `data/conversations/`(可用 `CONVERSATIONS_DIR` 覆盖) |
| 文件命名 | `<conversation-id>.json`,一个会话一个文件 |
| 是否进仓库 | 目录保留(`data/conversations/.gitkeep`),会话 JSON 不提交(`.gitignore`) |
| 开启方式 | `filmmate-web/.env`:`VITE_API_BASE=http://127.0.0.1:8000` + `VITE_REMOTE_CONVERSATIONS=1` |
| 关闭方式 | `VITE_REMOTE_CONVERSATIONS=0`(退回浏览器 localStorage,不产生文件) |

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
├── start.bat                  # Windows 一键启动(后端 + 前端)
├── start-filmmate.ps1         # start.bat 调用的 PowerShell 脚本(负责启停两个进程)
├── knowledge/knowledge.json   # 专业知识库(78 条)
├── cases/cases.json           # 作品案例库(10 部)
├── data/conversations/        # Phase 3 会话存储目录(目录保留,会话 JSON 已 .gitignore)
├── filmmate-web/              # Tauri 2 + React 19 + Vite 前端(见其 README)
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
