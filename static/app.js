/* Filmmate 前端逻辑:SSE 流式渲染、语音输入/合成、分镜 SVG 草图、CSV 导出 */
"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  tool: "",                 // 当前选中的工具(空=智能问答)
  history: [],
  streaming: false,
  apiKey: localStorage.getItem("filmmate_api_key") || "",
  voiceLang: localStorage.getItem("filmmate_voice_lang") || "zh-CN",
  ttsLang: localStorage.getItem("filmmate_tts_lang") || "zh-CN",
  current: null,            // 当前 bot 消息渲染句柄
};

/* ---------------- 初始化 ---------------- */
async function initHealth() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    const badge = $("#modeBadge");
    if (d.online) {
      badge.textContent = "在线 · DeepSeek API";
      badge.className = "badge badge-online";
    } else {
      badge.textContent = "离线演示模式(未配置 Key)";
      badge.className = "badge badge-offline";
    }
    $("#apiKey").value = state.apiKey;
    $("#voiceLang").value = state.voiceLang;
    $("#ttsLang").value = state.ttsLang;
  } catch (e) {
    $("#modeBadge").textContent = "后端未启动";
  }
}

/* ---------------- 消息渲染基础 ---------------- */
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function markdownLite(text) {
  let html = esc(text);
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const lines = html.split("\n");
  let out = [], inList = false;
  for (const line of lines) {
    if (/^\s*[-•]\s+/.test(line)) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${line.replace(/^\s*[-•]\s+/, "")}</li>`);
    } else {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<p>${line || "&nbsp;"}</p>`);
    }
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

function addUserMessage(text) {
  hideHero();
  const wrap = document.createElement("div");
  wrap.className = "msg user";
  wrap.innerHTML = `<div class="avatar">🧑‍🎨</div><div class="bubble">${markdownLite(text)}</div>`;
  $("#messages").appendChild(wrap);
  scrollBottom();
}

function newBotMessage() {
  hideHero();
  const wrap = document.createElement("div");
  wrap.className = "msg bot";
  wrap.innerHTML = `
    <div class="avatar">🎬</div>
    <div class="bubble">
      <div class="steps" style="display:none"></div>
      <div class="text"><span class="typing"><i></i><i></i><i></i></span></div>
      <div class="citations" style="display:none"></div>
      <div class="data"></div>
    </div>`;
  $("#messages").appendChild(wrap);
  scrollBottom();
  return {
    el: wrap,
    stepsEl: wrap.querySelector(".steps"),
    textEl: wrap.querySelector(".text"),
    citEl: wrap.querySelector(".citations"),
    dataEl: wrap.querySelector(".data"),
    text: "",
    done: false,
  };
}

function finishBotMessage(m) {
  m.done = true;
  if (m.stepsEl.style.display === "none") m.stepsEl.style.display = "none";
  if (m.text && m.text.trim()) {
    const speakBtn = document.createElement("button");
    speakBtn.className = "export-btn";
    speakBtn.textContent = "🔊 朗读";
    speakBtn.title = "语音合成朗读";
    speakBtn.onclick = () => speakText(m.text);
    m.textEl.appendChild(speakBtn);
  }
  scrollBottom();
}

function scrollBottom() {
  const c = $("#chat");
  c.scrollTop = c.scrollHeight;
}

function hideHero() {
  const hero = $("#hero");
  if (hero) hero.remove();
}

/* ---------------- SSE 流 ---------------- */
function handleBlock(block, m) {
  const lines = block.split("\n");
  let event = "message", dataStr = "";
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
  }
  let data = {};
  try { data = JSON.parse(dataStr); } catch (e) { return; }

  switch (event) {
    case "start": {
      m.textEl.innerHTML = `<span class="mode-tag ${data.mode === "online" ? "mode-online" : "mode-offline"}">${data.label} · ${data.mode === "online" ? "在线" : "离线"}</span> <span class="typing"><i></i><i></i><i></i></span>`;
      break;
    }
    case "steps": {
      const steps = data.steps || [];
      m.stepsEl.style.display = "flex";
      m.stepsEl.innerHTML = steps.map(s =>
        `<span class="step">🔧 <span class="fn">${esc(s.tool)}</span>(${esc(s.query || "")})</span>`
      ).join("") || '<span class="step">🔧 检索工具…</span>';
      break;
    }
    case "citations": {
      m.citEl.style.display = "flex";
      const kindCls = data.kind === "cases" ? "cases" : "knowledge";
      const label = data.kind === "cases" ? "🎬 案例" : "📚 知识库";
      for (const it of data.items || []) {
        const chip = document.createElement("span");
        chip.className = `cit ${kindCls}`;
        chip.textContent = `${label} · ${it.title}${it.category ? `(${it.category})` : ""}`;
        chip.title = it.logline || "";
        m.citEl.appendChild(chip);
      }
      break;
    }
    case "delta": {
      m.text += data.text || "";
      if (m.textEl.querySelector(".typing")) m.textEl.innerHTML = "";
      const hasModeTag = m.textEl.querySelector(".mode-tag");
      m.textEl.innerHTML = (hasModeTag ? `<span class="mode-tag ${m.textEl.querySelector(".mode-tag").className.includes("mode-online") ? "mode-online" : "mode-offline"}">${m.textEl.querySelector(".mode-tag").textContent}</span> ` : "") + markdownLite(m.text);
      scrollBottom();
      break;
    }
    case "tool_data": {
      if (m.textEl.querySelector(".typing")) m.textEl.innerHTML = "";
      renderToolData(m, data.tool, data.payload);
      break;
    }
    case "done": {
      finishBotMessage(m);
      state.streaming = false;
      setBusy(false);
      if (m.text) state.history.push({ role: "assistant", content: m.text.slice(0, 2000) });
      break;
    }
    case "error": {
      m.textEl.innerHTML = `<p style="color:var(--danger)">⚠️ ${esc(data.message || "出错了")}</p>`;
      finishBotMessage(m);
      state.streaming = false;
      setBusy(false);
      break;
    }
  }
}

async function send(text) {
  if (!text || state.streaming) return;
  state.streaming = true;
  setBusy(true);
  addUserMessage(text);
  state.history.push({ role: "user", content: text });
  const m = newBotMessage();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        tool: state.tool || null,
        api_key: state.apiKey,
        history: state.history.slice(-6, -1),
      }),
    });
    if (!res.ok || !res.body) throw new Error("HTTP " + res.status);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        handleBlock(block, m);
      }
    }
  } catch (e) {
    m.textEl.innerHTML = `<p style="color:var(--danger)">⚠️ 请求失败:${esc(e.message)}(后端是否已启动?)</p>`;
    finishBotMessage(m);
    state.streaming = false;
    setBusy(false);
  }
}

function setBusy(busy) {
  const btn = $("#sendBtn");
  btn.disabled = busy;
  btn.textContent = busy ? "生成中…" : "发送 ↵";
}

/* ---------------- 工具结果渲染 ---------------- */
function renderToolData(m, tool, payload) {
  const el = m.dataEl;
  el.innerHTML = "";
  if (tool === "review") return renderReview(el, payload);
  if (tool === "storyboard") return renderStoryboard(el, payload);
  if (tool === "rundown") return renderRundown(el, payload);
  if (tool === "schedule") return renderSchedule(el, payload);
  if (tool === "inspiration") return renderInspiration(el, payload);
  if (tool === "cases") return renderCases(el, payload);
  if (payload.references) renderReferences(el, payload.references);
}

function renderReferences(el, refs) {
  if (!refs || !refs.length) return;
  const box = document.createElement("div");
  box.className = "citations";
  box.style.display = "flex";
  for (const r of refs) {
    const chip = document.createElement("span");
    chip.className = "cit cases";
    chip.textContent = `🎬 参考案例 · ${r.title}`;
    chip.title = r.logline || "";
    box.appendChild(chip);
  }
  el.appendChild(box);
}

function renderReview(el, p) {
  const high = (p.issues || []).filter(i => i.severity === "高").length;
  const box = document.createElement("div");
  box.className = "review-block";
  const scoreColor = p.score >= 7 ? "var(--ok)" : p.score >= 5 ? "var(--warn)" : "var(--danger)";
  box.innerHTML = `
    <div class="review-head">
      <div class="score-ring" style="border-color:${scoreColor}">
        <span class="num" style="color:${scoreColor}">${p.score ?? "—"}</span><span class="cap">/10</span>
      </div>
      <div class="review-summary">${markdownLite(p.summary || "")}</div>
    </div>
    <div class="strengths">${(p.strengths || []).map(s => `<span class="cit">✨ ${esc(s)}</span>`).join("")}</div>`;
  const issuesWrap = document.createElement("div");
  for (const it of p.issues || []) {
    const div = document.createElement("div");
    div.className = `issue sev-${it.severity}`;
    div.innerHTML = `
      <div class="issue-head">
        <span class="sev">${esc(it.severity)}</span>
        <span>${esc(it.type || "其他")}</span>
        <span>📍 ${esc(it.location || "")}</span>
      </div>
      ${it.quote ? `<div class="quote">“${esc(it.quote)}”</div>` : ""}
      <div class="problem">${markdownLite(it.problem || "")}</div>
      <div class="suggestion">💡 ${markdownLite(it.suggestion || "")}</div>`;
    issuesWrap.appendChild(div);
  }
  box.appendChild(issuesWrap);
  if (p.next_steps) {
    const ns = document.createElement("div");
    ns.className = "section-title";
    ns.textContent = "下一步建议";
    const np = document.createElement("p");
    np.innerHTML = markdownLite(p.next_steps);
    box.appendChild(ns);
    box.appendChild(np);
  }
  el.appendChild(box);
  renderReferences(el, p.references);
  if (p.mode) {
    const tag = document.createElement("span");
    tag.className = `mode-tag ${p.mode === "online" ? "mode-online" : "mode-offline"}`;
    tag.textContent = p.mode === "online" ? "DeepSeek 审阅" : "离线启发式检查";
    el.appendChild(tag);
  }
}

/* SVG 分镜草图:按景别/机位生成简约构图 */
function sketchSVG(shot) {
  const id = shot.id || 1;
  const t = shot.shot_type || "中景";
  const a = shot.angle || "平视";
  const palettes = [
    { s1: "#1c2743", s2: "#d97a3a", g: "#12141d", night: false },
    { s1: "#0d1a2b", s2: "#2b4d6e", g: "#0c0f16", night: true },
    { s1: "#2c3754", s2: "#9a724f", g: "#141821", night: false },
    { s1: "#0f1e2e", s2: "#3f7d8c", g: "#10151f", night: true },
    { s1: "#242d40", s2: "#c08d4e", g: "#131722", night: false },
  ];
  const p = palettes[id % palettes.length];
  let hy = 50; // 地平线
  if (a.includes("俯")) hy = 24;
  else if (a.includes("仰")) hy = 66;
  else if (a.includes("鸟")) hy = 10;
  let fh = 34, headOnly = false;
  if (t.includes("远")) fh = 12;
  else if (t.includes("全")) fh = 26;
  else if (t.includes("中")) fh = 40;
  else if (t.includes("近")) fh = 52;
  else if (t.includes("特")) { fh = 64; headOnly = true; }
  if (t.includes("大特")) fh = 76;
  const fx = 82, fy = hy + 8;
  const fw = fh * 0.34;
  let figure = "";
  if (headOnly) {
    figure = `<circle cx="${fx}" cy="${hy + 10}" r="${fh * 0.34}" fill="#0a0c12"/>
              <path d="M${fx - fw} ${hy + 34} Q${fx} ${hy + 6} ${fx + fw} ${hy + 34} L${fx + fw} 92 L${fx - fw} 92 Z" fill="#0a0c12"/>`;
  } else {
    const headR = fh * 0.16;
    figure = `<circle cx="${fx}" cy="${fy - fh + headR}" r="${headR}" fill="#0a0c12"/>
              <path d="M${fx - fw / 2} ${fy - fh + headR * 2} Q${fx} ${fy - fh + headR * 1.6} ${fx + fw / 2} ${fy - fh + headR * 2} L${fx + fw / 2} ${fy} L${fx - fw / 2} ${fy} Z" fill="#0a0c12"/>`;
  }
  const moon = p.night ? `<circle cx="138" cy="20" r="7" fill="#e8e2c8" opacity=".9"/><circle cx="136" cy="18" r="6.5" fill="${p.s1}" opacity=".55"/>` : `<circle cx="138" cy="20" r="7" fill="#f2c98a" opacity=".85"/>`;
  const grid = `<line x1="53.3" y1="8" x2="53.3" y2="82" stroke="#ffffff" stroke-opacity=".05"/><line x1="106.6" y1="8" x2="106.6" y2="82" stroke="#ffffff" stroke-opacity=".05"/><line x1="8" y1="30" x2="152" y2="30" stroke="#ffffff" stroke-opacity=".05"/><line x1="8" y1="60" x2="152" y2="60" stroke="#ffffff" stroke-opacity=".05"/>`;
  return `<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg">
    <defs><linearGradient id="sk${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p.s1}"/><stop offset="1" stop-color="${p.s2}"/></linearGradient></defs>
    <rect width="160" height="90" fill="url(#sk${id})"/>
    ${moon}
    <rect y="${hy}" width="160" height="${90 - hy}" fill="${p.g}"/>
    ${a.includes("过肩") ? `<path d="M0 ${hy + 2} Q30 ${hy - 18} 46 ${hy + 6} L46 92 L0 92 Z" fill="#07080d"/>` : ""}
    ${figure}
    ${grid}
    <rect width="160" height="7" fill="#05060a"/><rect y="83" width="160" height="7" fill="#05060a"/>
  </svg>`;
}

function renderStoryboard(el, p) {
  const grid = document.createElement("div");
  grid.className = "shots-grid";
  for (const shot of p.shots || []) {
    const card = document.createElement("div");
    card.className = "shot-card";
    card.innerHTML = `
      ${sketchSVG(shot)}
      <div class="shot-info">
        <div class="tags">
          <span>${esc(shot.scene)}</span><span>${esc(shot.shot_type)}</span><span>${esc(shot.angle)}</span>
          <span>${esc(shot.movement)}</span><span>${esc(shot.duration)}</span>
        </div>
        <div class="desc">${esc(shot.description || "")}</div>
        ${shot.dialogue ? `<div class="dlg">🗣 ${esc(shot.dialogue)}</div>` : ""}
      </div>`;
    grid.appendChild(card);
  }
  el.appendChild(grid);
  if (p.note) {
    const note = document.createElement("p");
    note.style.cssText = "font-size:12px;color:var(--text-dim);margin-top:8px;";
    note.textContent = "ℹ️ " + p.note;
    el.appendChild(note);
  }
  renderReferences(el, p.references);
}

function renderRundown(el, p) {
  const title = document.createElement("div");
  title.className = "section-title";
  title.textContent = `${p.title || "拍摄通告单"}${p.date ? ` · ${p.date}` : ""}`;
  el.appendChild(title);
  const rows = (p.items || []).map(it => [it.time, it.item, it.location, it.cast, it.equipment, it.notes]);
  el.appendChild(buildTable(["时间", "项目", "地点", "人员", "设备", "备注"], rows));
  el.appendChild(exportBtn("rundown.csv", [["时间", "项目", "地点", "人员", "设备", "备注"], ...rows]));
  renderReferences(el, p.references);
}

function renderSchedule(el, p) {
  const title = document.createElement("div");
  title.className = "section-title";
  title.textContent = p.title || "拍摄日程";
  el.appendChild(title);
  const allRows = [];
  for (const d of p.days || []) {
    const head = document.createElement("div");
    head.className = "section-title";
    head.textContent = `${d.day} · ${d.theme || ""}`;
    el.appendChild(head);
    const rows = (d.tasks || []).map(tk => [d.day, tk.time, tk.task, tk.location, tk.notes]);
    allRows.push(...rows);
    el.appendChild(buildTable(["时间", "任务", "地点", "备注"], rows.map(r => r.slice(1))));
    if (d.tip) {
      const tip = document.createElement("p");
      tip.style.cssText = "font-size:12px;color:var(--warn);margin:4px 0 10px;";
      tip.textContent = "💡 " + d.tip;
      el.appendChild(tip);
    }
  }
  el.appendChild(exportBtn("schedule.csv", [["天", "时间", "任务", "地点", "备注"], ...allRows]));
  renderReferences(el, p.references);
}

function renderInspiration(el, p) {
  const grid = document.createElement("div");
  grid.className = "concept-grid";
  for (const c of p.concepts || []) {
    const card = document.createElement("div");
    card.className = "concept-card";
    card.innerHTML = `
      <div class="c-title">${esc(c.title)}</div>
      <div class="c-genre">${esc(c.genre)}</div>
      <p><strong>梗概</strong>${esc(c.logline)}</p>
      <p><strong>开场钩子</strong>${esc(c.hook)}</p>
      <p><strong>反转</strong>${esc(c.twist)}</p>`;
    grid.appendChild(card);
  }
  el.appendChild(grid);
  if (p.note) {
    const note = document.createElement("p");
    note.style.cssText = "font-size:12px;color:var(--text-dim);margin-top:8px;";
    note.textContent = "ℹ️ " + p.note;
    el.appendChild(note);
  }
  renderReferences(el, p.references);
}

function renderCases(el, p) {
  const grid = document.createElement("div");
  grid.className = "concept-grid";
  for (const c of p.cases || []) {
    const card = document.createElement("div");
    card.className = "case-card";
    const rundownRows = (c.rundown || []).slice(0, 4).map(r => `<tr><td>${esc(r.time)}</td><td>${esc(r.item)}</td></tr>`).join("");
    card.innerHTML = `
      <div class="c-title">🎬 ${esc(c.title)}</div>
      <div class="c-meta">${esc(c.type)} · ${esc(c.genre)} · ${esc(c.duration)} · ${esc(c.budget)}</div>
      <p><span class="c-label">梗概:</span>${esc(c.logline)}</p>
      <p><span class="c-label">拍摄地:</span>${esc((c.locations || []).join("、"))}</p>
      <p><span class="c-label">设备:</span>${esc((c.equipment || []).join("、"))}</p>
      <p><span class="c-label">Rundown(节选):</span></p>
      <table class="tbl"><tr><th>时间</th><th>项目</th></tr>${rundownRows}</table>
      <p style="margin-top:6px"><span class="c-label">经验教训:</span>${esc(c.lessons || "")}</p>`;
    grid.appendChild(card);
  }
  el.appendChild(grid);
}

function buildTable(headers, rows) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.innerHTML = `<table class="tbl"><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  return wrap;
}

function exportBtn(filename, rows) {
  const wrap = document.createElement("div");
  wrap.className = "export-row";
  const btn = document.createElement("button");
  btn.className = "export-btn";
  btn.textContent = "⬇️ 导出 CSV";
  btn.onclick = () => exportCSV(filename, rows);
  wrap.appendChild(btn);
  return wrap;
}

function exportCSV(filename, rows) {
  const csv = "\uFEFF" + rows.map(r => r.map(c => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------------- 语音 ---------------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, recActive = false;

function toggleMic() {
  if (!SR) { alert("此浏览器不支持语音识别(建议用 Chrome)"); return; }
  if (recActive) { rec.stop(); return; }
  rec = new SR();
  rec.lang = state.voiceLang;
  rec.interimResults = true;
  rec.continuous = false;
  let finalText = "";
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
      else interim += e.results[i][0].transcript;
    }
    $("#input").value = (finalText + interim).trim();
    autoResize();
  };
  rec.onend = () => { recActive = false; $("#micBtn").classList.remove("recording"); };
  rec.onerror = () => { recActive = false; $("#micBtn").classList.remove("recording"); };
  try {
    rec.start();
    recActive = true;
    $("#micBtn").classList.add("recording");
  } catch (e) { /* 已开启时忽略 */ }
}

function speakText(text) {
  if (!state.ttsLang) return;
  if (!window.speechSynthesis) return;
  const clean = text.replace(/\*\*/g, "").replace(/[#\[\]()]/g, "").slice(0, 300);
  const u = new SpeechSynthesisUtterance(clean);
  u.lang = state.ttsLang;
  u.rate = 1.02;
  const voices = speechSynthesis.getVoices().filter(v => v.lang.startsWith(state.ttsLang.split("-")[0]));
  if (voices.length) u.voice = voices[0];
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

/* ---------------- UI 事件 ---------------- */
function autoResize() {
  const ta = $("#input");
  ta.style.height = "auto";
  ta.style.height = Math.min(140, ta.scrollHeight) + "px";
}

function bindEvents() {
  // 工具 chips
  document.querySelectorAll(".chip-tool").forEach(chip => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip-tool").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      state.tool = chip.dataset.tool || "";
    });
  });

  $("#sendBtn").addEventListener("click", () => {
    const text = $("#input").value.trim();
    if (!text) return;
    $("#input").value = "";
    autoResize();
    send(text);
  });

  $("#input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#sendBtn").click();
    }
  });
  $("#input").addEventListener("input", autoResize);

  $("#micBtn").addEventListener("click", toggleMic);

  $("#useSample").addEventListener("click", () => {
    $("#input").value = $("#sampleScript").textContent;
    autoResize();
    document.querySelectorAll(".chip-tool").forEach(c => c.classList.remove("active"));
    const reviewChip = [...document.querySelectorAll(".chip-tool")].find(c => c.dataset.tool === "review");
    if (reviewChip) reviewChip.classList.add("active");
    state.tool = "review";
    $("#sendBtn").click();
  });

  // 设置抽屉
  $("#settingsBtn").addEventListener("click", () => $("#settingsOverlay").classList.remove("hidden"));
  $("#closeSettings").addEventListener("click", () => $("#settingsOverlay").classList.add("hidden"));
  $("#settingsOverlay").addEventListener("click", (e) => {
    if (e.target === $("#settingsOverlay")) $("#settingsOverlay").classList.add("hidden");
  });
  $("#saveSettings").addEventListener("click", () => {
    state.apiKey = $("#apiKey").value.trim();
    state.voiceLang = $("#voiceLang").value;
    state.ttsLang = $("#ttsLang").value;
    localStorage.setItem("filmmate_api_key", state.apiKey);
    localStorage.setItem("filmmate_voice_lang", state.voiceLang);
    localStorage.setItem("filmmate_tts_lang", state.ttsLang);
    $("#settingsOverlay").classList.add("hidden");
    initHealth();
  });
}

bindEvents();
initHealth();
