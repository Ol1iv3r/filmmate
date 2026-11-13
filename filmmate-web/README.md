# 🎬 Filmmate Web —— Phase 1（聊天 UI）+ Phase 2（语音输入）+ Phase 3（会话落盘）+ Phase 4（工具调用可视化）

COMP4431 Group 20 · 影视创作 AI 助理的前端。
技术栈：**Tauri 2 + React 19 + Vite + TypeScript**，聊天协议基于 **Vercel AI SDK（`ai` / `@ai-sdk/react`）**。

> 演示直接跑浏览器（`npm run dev`）；Tauri 只是桌面壳包装，配置已就绪（见 §5）。

---

## ✨ 已实现功能（对照分工清单）

### Phase 1 · 基础聊天 UI
- [x] 项目骨架：Tauri 2 + React + Vite + TypeScript
- [x] 消息气泡（user / assistant）、**Markdown 渲染**（GFM 表格/引用/任务列表）、**代码块高亮 + 复制按钮**
- [x] 自动滚底（阅读历史时不打扰，出现「回到最新」按钮）
- [x] 输入区：多行、**Enter 发送 / Shift+Enter 换行**、中文输入法保护（composition 事件）、发送中禁用
- [x] **停止生成**（流式中发送键变停止键）、**重新生成**
- [x] **流式输出**：assistant 逐字出现（走 AI SDK 官方 UIMessageChunk 管线）
- [x] **会话侧栏**：新建（⌘K）/ 切换 / 重命名（内联编辑）/ 删除（两段确认）
  - 列表 UI 在本仓库；**存取走 `ConversationRepository` 接口**（默认 localStorage，设置 `VITE_REMOTE_CONVERSATIONS=1` + `VITE_API_BASE` 后切到 Phase 3 的 JSON 落盘 API）
- [x] 状态处理：加载骨架屏、空会话引导页（**3 个示例 prompt 一键填入**）、**网络错误横幅 + 重试**
- [x] **麦克风按钮**（Phase 2：录音 → whisper-1 → 文本回填输入框，见下节）
- [x] 响应式（移动端抽屉侧栏）+ 深色影院主题（投影仪友好）

### Phase 4 · Tool Call 可视化（拿分点）
- [x] 一条 assistant 消息内 **text / tool-call / reasoning 混排**
- [x] 工具调用卡片：工具名（`searchSamples`）、检索关键词 chips、状态（**检索中→完成，实时耗时**）
- [x] **命中样本预览**：标题、时间段（`00:12–00:18`）、片段描述、**相似度进度条**、关键词、点击展开
- [x] **「打开原片对应时间」链接**：`https://www.youtube.com/watch?v=<id>&t=<秒>`
- [x] **折叠区显示原始 JSON**（含调用参数与完整输出，评委问“是不是假的”直接展开）
- [x] **多个 tool call 按时间线排列**（剧本检查 = searchKnowledge → searchSamples 双调用演示）
- [x] 失败态：红色错误卡片 + 错误信息 + **降级说明**

### Phase 2 · 语音输入（voice input）
点麦克风 → 说话 → 再点一次停止 → 录音送 whisper-1 → **文字回填输入框，永不自动发送**。

- [x] `useVoiceInput` 状态机：`idle → requesting → recording → transcribing`，录音中显示计时
- [x] 录音规则：最长 120 s；短于 400 ms 视为误触；录音时 `Esc` 取消，`Enter` = 停止并转写（不会把半句话发出去）
- [x] 任何退出路径都释放麦克风（`getUserMedia` 的 track 一定 stop）
- [x] 转写结果按光标并入草稿（`voiceInputMerge`），不覆盖已输入内容
- [x] 错误按类型显示在输入框下方：密钥无效 / 限流 / 超过 25 MB / 超时 / 连不上后端 / 未识别到文字
- [x] 密钥只在 Python 后端（`.env`），浏览器只上传音频字节

后端 `POST /api/transcribe`（根目录 `voice_input_api.py`）：

| 项 | 值 |
|---|---|
| 输入 | multipart：`file=<audio>`，可选 `language` |
| 输出 | `{ "text": "..." }` |
| 上游 A（默认） | Vercel AI Gateway `POST /v4/ai/transcription-model`，base64 JSON + `ai-model-id: openai/whisper-1` |
| 上游 B | OpenAI `POST /v1/audio/transcriptions`（标准 multipart） |
| 限制 | 25 MB / 60 s 超时；空音频 400，未配 Key 503 |

> ⚠️ Gateway 的 `/v1/audio/transcriptions` **不存在**（会 404）；转写走独立的 v4 端点，且只收 JSON + base64。
> 另外 `MediaRecorder` 给的 MIME 是 `audio/webm;codecs=opus`，后端会去掉 `;codecs=…` 再转发。

前端只认一个变量：`VITE_TRANSCRIBE_BASE`（留空时回退 `VITE_API_BASE`），所以语音可以先接后端、聊天继续走 Mock。

### Phase 3 · 会话落盘（chat storage）
聊天记录 → 消息对象 → dict → 磁盘 JSON，一个会话一个文件，刷新/重启后仍在。

- [x] `UIMessage[]` 原样落盘（`version / id / title / createdAt / updatedAt / messages`），时间戳为毫秒数字
- [x] 5 个 REST 接口：`GET /api/conversations`、`GET/PUT/PATCH/DELETE /api/conversations/{id}`
- [x] 原子写入（临时文件 + `os.replace`）、按 id 加锁，并发 PUT 不互相覆盖
- [x] 文件名安全（id 正则校验）、损坏文件隔离（不拖垮整个列表）
- [x] `createdAt` 跨多次自动保存保持不变；`PATCH`/`DELETE` 返回 JSON（前端 `req()` 总会 `res.json()`）
- [x] `chat_storage_langchain.py` 预留 `BaseMessage.to_dict()` ↔ dict 转换，接 LangChain 时不用改存储层

开关（`filmmate-web/.env`）：

```ini
VITE_API_BASE=http://127.0.0.1:8000
VITE_REMOTE_CONVERSATIONS=1
```

文件位置：`data/conversations/<id>.json`（已加入 `.gitignore`，不进仓库）。

### 白捡分的附加项
- [x] 浏览器 **SpeechSynthesis 朗读回答**（每条 assistant 消息 🔊）
- [x] 完整 **本地 Mock 演示模式**（无后端、无 API key 也能跑全场演示，断网不翻车）

---

## 🚀 快速开始

以下命令从**仓库根目录**开始。

```bash
# 终端 1：Python 后端（语音输入 / 会话落盘需要；只演示 Phase 1/4 可跳过）
pip install -r requirements.txt
cp .env.example .env                     # 填 AI_GATEWAY_API_KEY 或 OPENAI_API_KEY
python app.py                            # http://127.0.0.1:8000

# 终端 2：前端
cd filmmate-web
npm install
cp .env.example .env                     # 按注释填写 VITE_TRANSCRIBE_BASE 等
npm run dev                              # http://localhost:5173
```

构建 / 测试：

```bash
npm run build        # tsc + vite build → dist/
node scripts/smoke.mjs    # 端到端冒烟（空态→发送→工具卡片→命中→JSON→重生成→持久化）
node scripts/smoke2.mjs   # 多工具时间线 / 停止 / 重命名 / 移动端 / 溢出检查
```

### 三种运行模式（自动切换，零代码改动）

| 模式 | 条件 | 表现 |
|---|---|---|
| **本地演示** | `.env` 未配置 `VITE_API_BASE` | Mock 引擎用真实样本数据（50 部片 / 299 镜头段）流式模拟完整「检索→生成」过程 |
| **API 在线** | `VITE_API_BASE=http://…` | `POST {base}/api/chat` 走 AI SDK 官方 `DefaultChatTransport` |
| **远端会话** | 加 `VITE_REMOTE_CONVERSATIONS=1` | 会话历史走 `{base}/api/conversations` REST（Jacky Phase 3） |

> 语音输入与聊天模式**互相独立**：只要 `.env` 里的 `VITE_TRANSCRIBE_BASE` 指向 Python 后端，
> 即使聊天还在 Mock 模式，麦克风也能用。

### 演示话术（Mock 模式下直接可演示）
1. 「给一个 30 秒可爱宠物零食广告出分镜，参考样本库里类似风格的片子」→ searchSamples → 命中卡片 → 分镜表格
2. 「帮我检查剧本漏洞：第1场 天台 夜 小明：今晚的月亮真圆。第2场 天台 日 小明：你不是出国了吗？」→ **双工具时间线** → 漏洞表
3. 「帮我排一个校园短片 2 小时拍摄 rundown」→ 通告单表格
4. 输入含「**错误演示**」→ 工具失败红色卡片 + 降级说明

---

## 🔌 与 Jacky 的后端对接（兼容性）

消息协议完全遵循 **Vercel AI SDK v5+ UIMessage 流**，同时兼容《团队项目说明》§4.2 的旧版 Part 结构（`tool-call` / `tool-result` 会按 `toolCallId` 自动合并）。字段名容错（`videoId`/`video_id`/`youtube_video_id`、`score`/`similarity`/`distance`、`hits`/`results`/`samples`）。

**约定与细节见 [docs/CONTRACT.md](docs/CONTRACT.md)**（发给 Jacky 的那份协议）。核心类型在 [`src/lib/contract.ts`](src/lib/contract.ts)，渲染层只消费其中的视图模型。

Jacky 后端只需一个标准 AI SDK route：

```ts
// 伪代码（Next.js/任意 AI SDK 后端）
app.post('/api/chat', async (req) => {
  const { messages } = await req.json()          // 与 LangChain message dict 一一对应
  return streamText({ model, system, messages, tools }).toUIMessageStreamResponse()
})
```

**当前进度**：Phase 2 的 `POST /api/transcribe` 与 Phase 3 的 `/api/conversations` 已在本仓库根部实现
（`voice_input_api.py`、`chat_storage*.py`，由 `app.py` 注册）。前端侧已全部对接完成，
剩下的只有把 `/api/chat` 从旧 SSE 换成上面的 `UIMessageStream`。

---

## 📁 目录结构

```
filmmate-web/
├── index.html / vite.config.ts / tsconfig*.json
├── src/
│   ├── App.tsx                    # 侧栏 + 面板骨架、⌘K、会话管理
│   ├── hooks/
│   │   └── useVoiceInput.ts       # Phase 2：录音状态机（requesting/recording/transcribing）
│   ├── lib/
│   │   ├── contract.ts            # ★ 协议契约层（与 Jacky 对齐的唯一文件）
│   │   ├── transport.ts           # Mock / DefaultChatTransport 选择器
│   │   ├── conversations.ts       # 会话存取接口（localStorage / 远端 REST）
│   │   ├── voiceInput.ts          # Phase 2：MIME 选择 / 支持检测 / 时长格式化
│   │   ├── voiceInputApi.ts       # Phase 2：上传 /api/transcribe + 错误分类
│   │   ├── voiceInputMerge.ts     # Phase 2：转写结果并入草稿
│   │   └── utils.ts               # 朗读、复制、时间解析等
│   ├── mock/
│   │   ├── samples.json           # 真实样本数据（50 部片，samples:build 生成）
│   │   └── mockEngine.ts          # 意图识别 + 检索模拟 + 回答生成 + chunk 流
│   ├── components/                # 消息、输入、侧栏、空态、错误横幅
│   │   └── parts/                 # Phase 4：ToolCard / HitRow / RawJson / Reasoning
│   └── styles/                    # 电影风深色主题 + hljs 主题
├── scripts/                       # build-samples.mjs / smoke*.mjs
├── docs/CONTRACT.md               # ★ 消息契约（发 Jacky）
└── src-tauri/                     # Tauri 2 壳配置（演示用不到）
```

仓库根目录（Phase 2 / Phase 3 后端）：

```
├── voice_input_api.py        # POST /api/transcribe → whisper-1
├── chat_storage.py           # 会话 JSON 存储（原子写 / 加锁 / 损坏隔离）
├── chat_storage_api.py       # /api/conversations REST（5 个路由）
├── chat_storage_langchain.py # LangChain BaseMessage ↔ dict（预留，未接线）
└── data/conversations/       # 运行后生成，已 .gitignore
```

---

## 🖥 Tauri 桌面壳（可选，不阻塞演示）

```bash
npm run tauri dev     # 需要本机装 Rust；没装就用浏览器演示，功能完全一致
```

已配置 `tauri.conf.json`（devUrl=5173、frontendDist=../dist、Dark 主题窗口）。`bundle.active=false`，暂不产出安装包（避免打包坑，见任务文档 §8.5）。

---

## ⚠️ 说明与边界

- **Mock 回答是演示级**（规则 + 真实样本拼装），真正的生成质量来自 Jacky 接的 LLM；换后端后 UI 一行不用改。
- **语音输入**已接 whisper-1（不是占位）：录音经 `POST /api/transcribe` 转写，结果只回填输入框、不自动发送；音频不落盘。
- **语音转写走 AI Gateway 的 v4 端点**（`/v4/ai/transcription-model`）。Gateway 的 `/v1/audio/transcriptions` 不存在（404）；直连 OpenAI 时才用标准 multipart `/v1/audio/transcriptions`。`TRANSCRIBE_LANGUAGE` / `TRANSCRIBE_PROMPT` 仅在直连 OpenAI 时生效。
- **会话历史**默认存 localStorage；设置 `VITE_REMOTE_CONVERSATIONS=1` + `VITE_API_BASE` 后落盘到 `data/conversations/<id>.json`（Phase 3）。
- **已知限制**：开启远端会话后，`/api/chat` 需要输出 AI SDK `UIMessageStream`；当前 Python 仍用旧 SSE，assistant 回复会报错，但用户消息仍会正常落盘。
- 语音朗读用浏览器 SpeechSynthesis（评分项 “speech recognition **and synthesis**” 的 synthesis 半）。

## 👥 组员（提交前填全）

| 姓名 | 学号 | 负责 |
|---|---|---|
| Oliver | | Phase 1 + Phase 4（本仓库） |
| Jacky | | Phase 2 + Phase 3 后端 |
| Almosty | | 样本数据（已入 `src/mock/samples.json`） |
| Oscar | | |
