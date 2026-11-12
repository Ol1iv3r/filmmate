# 🎬 Filmmate Web —— Phase 1（聊天 UI）+ Phase 4（工具调用可视化）

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
  - 列表 UI 在本仓库；**存取走 `ConversationRepository` 接口**（现在是 localStorage，Jacky Phase 3 的 JSON 落盘 API 好了之后改一个环境变量即切换）
- [x] 状态处理：加载骨架屏、空会话引导页（**3 个示例 prompt 一键填入**）、**网络错误横幅 + 重试**
- [x] **麦克风按钮占位**（idle / 录音中 / 转写中三态 + 脉冲动画，Phase 2 接 whisper-1）
- [x] 响应式（移动端抽屉侧栏）+ 深色影院主题（投影仪友好）

### Phase 4 · Tool Call 可视化（拿分点）
- [x] 一条 assistant 消息内 **text / tool-call / reasoning 混排**
- [x] 工具调用卡片：工具名（`searchSamples`）、检索关键词 chips、状态（**检索中→完成，实时耗时**）
- [x] **命中样本预览**：标题、时间段（`00:12–00:18`）、片段描述、**相似度进度条**、关键词、点击展开
- [x] **「打开原片对应时间」链接**：`https://www.youtube.com/watch?v=<id>&t=<秒>`
- [x] **折叠区显示原始 JSON**（含调用参数与完整输出，评委问“是不是假的”直接展开）
- [x] **多个 tool call 按时间线排列**（剧本检查 = searchKnowledge → searchSamples 双调用演示）
- [x] 失败态：红色错误卡片 + 错误信息 + **降级说明**

### 白捡分的附加项
- [x] 浏览器 **SpeechSynthesis 朗读回答**（每条 assistant 消息 🔊）
- [x] 完整 **本地 Mock 演示模式**（无后端、无 API key 也能跑全场演示，断网不翻车）

---

## 🚀 快速开始

```bash
cd filmmate-web
npm install
npm run dev          # http://localhost:5173
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

```bash
cp .env.example .env   # 按注释填写
```

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

---

## 📁 目录结构

```
filmmate-web/
├── index.html / vite.config.ts / tsconfig*.json
├── src/
│   ├── App.tsx                    # 侧栏 + 面板骨架、⌘K、会话管理
│   ├── lib/
│   │   ├── contract.ts            # ★ 协议契约层（与 Jacky 对齐的唯一文件）
│   │   ├── transport.ts           # Mock / DefaultChatTransport 选择器
│   │   ├── conversations.ts       # 会话存取接口（localStorage / 远端 REST）
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

---

## 🖥 Tauri 桌面壳（可选，不阻塞演示）

```bash
npm run tauri dev     # 需要本机装 Rust；没装就用浏览器演示，功能完全一致
```

已配置 `tauri.conf.json`（devUrl=5173、frontendDist=../dist、Dark 主题窗口）。`bundle.active=false`，暂不产出安装包（避免打包坑，见任务文档 §8.5）。

---

## ⚠️ 说明与边界

- **Mock 回答是演示级**（规则 + 真实样本拼装），真正的生成质量来自 Jacky 接的 LLM；换后端后 UI 一行不用改。
- 麦克风按钮目前是占位（三态可视化），Phase 2 接 whisper-1 时替换 `MicButton.tsx` 的 `toggle()` 即可。
- 会话历史现在存 localStorage；Jacky Phase 3 的 JSON 落盘接口约定见 CONTRACT.md §3。
- 语音朗读用浏览器 SpeechSynthesis（评分项 “speech recognition **and synthesis**” 的 synthesis 半）。

## 👥 组员（提交前填全）

| 姓名 | 学号 | 负责 |
|---|---|---|
| Oliver | | Phase 1 + Phase 4（本仓库） |
| Jacky | | Phase 2 + Phase 3 后端 |
| Almosty | | 样本数据（已入 `src/mock/samples.json`） |
| Oscar | | |
