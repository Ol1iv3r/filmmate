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
  script: null,             // 已上传剧本 {name, text, chars}
  libScript: null,          // 个人灵感库附带的剧本
};

/* ---------------- 初始化 ---------------- */
async function initHealth() {
  try {
    await fetch("/api/health");
  } catch (e) {
    console.warn("后端未启动", e);
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

function addUserMessage(text, scriptName) {
  hideHero();
  const wrap = document.createElement("div");
  wrap.className = "msg user";
  const attach = scriptName ? `<div class="attach-line">📄 ${esc(scriptName)}</div>` : "";
  wrap.innerHTML = `<div class="avatar">🧑‍🎨</div><div class="bubble">${attach}${markdownLite(text)}</div>`;
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
  const script = state.script;
  if ((!text && !script) || state.streaming) return;
  const content = text || "请处理这份剧本";
  state.streaming = true;
  setBusy(true);
  addUserMessage(content, script ? script.name : "");
  state.history.push({ role: "user", content: content.slice(0, 2000) });
  const m = newBotMessage();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: content,
        tool: state.tool || null,
        api_key: state.apiKey,
        script_text: script ? script.text : "",
        script_name: script ? script.name : "",
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
  if (p.genre_benchmark) {
    const gb = document.createElement("p");
    gb.style.cssText = "font-size:13px;color:var(--text-dim);margin-top:10px;border-left:2px solid var(--accent);padding-left:10px;";
    gb.innerHTML = `<strong>类型对标</strong> ${esc(p.genre_benchmark)}`;
    box.appendChild(gb);
  }
  if (p.production_risks && p.production_risks.length) {
    const rTitle = document.createElement("div");
    rTitle.className = "section-title";
    rTitle.textContent = "制作风险";
    box.appendChild(rTitle);
    const riskWrap = document.createElement("div");
    riskWrap.className = "risk-list";
    for (const r of p.production_risks) {
      const item = document.createElement("div");
      item.className = `risk-item sev-${r.severity}`;
      item.innerHTML = `<span class="sev">${esc(r.severity || "中")}</span>
        <span class="risk-name">${esc(r.risk)}</span>
        <span class="risk-fix">→ ${esc(r.mitigation || "")}</span>`;
      riskWrap.appendChild(item);
    }
    box.appendChild(riskWrap);
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
  if (p.scene_plan && p.scene_plan.length) {
    const plan = document.createElement("div");
    plan.className = "scene-plan";
    plan.innerHTML = p.scene_plan.map(sp => `
      <div class="plan-item">
        <span class="plan-scene">${esc(sp.scene || "")}</span>
        <span class="plan-cov">${esc((sp.coverage || []).join(" + "))}</span>
        ${sp.notes ? `<span class="plan-note">${esc(sp.notes)}</span>` : ""}
      </div>`).join("");
    el.appendChild(plan);
  }
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
          <span>${esc(shot.movement)}</span>${shot.lens ? `<span>${esc(shot.lens)}</span>` : ""}<span>${esc(shot.duration)}</span>
        </div>
        <div class="desc">${esc(shot.description || "")}</div>
        ${shot.purpose ? `<div class="shot-row"><b>目的</b>${esc(shot.purpose)}</div>` : ""}
        ${shot.lighting ? `<div class="shot-row"><b>光线</b>${esc(shot.lighting)}</div>` : ""}
        ${shot.sound ? `<div class="shot-row"><b>声音</b>${esc(shot.sound)}</div>` : ""}
        ${shot.transition ? `<div class="shot-row"><b>转场</b>${esc(shot.transition)}</div>` : ""}
        ${shot.dialogue ? `<div class="dlg">🗣 ${esc(shot.dialogue)}</div>` : ""}
      </div>`;
    grid.appendChild(card);
  }
  el.appendChild(grid);
  if (p.coverage_notes) {
    const cn = document.createElement("p");
    cn.className = "coverage-note";
    cn.textContent = "🎯 " + p.coverage_notes;
    el.appendChild(cn);
  }
  if (p.note) {
    const note = document.createElement("p");
    note.style.cssText = "font-size:12px;color:var(--text-dim);margin-top:8px;";
    note.textContent = "ℹ️ " + p.note;
    el.appendChild(note);
  }
  renderReferences(el, p.references);
}

function pagesLabel(n) {
  if (!n) return "—";
  const whole = Math.floor(n / 8), frac = n % 8;
  if (whole && frac) return `${whole} 又 ${frac}/8`;
  return whole ? `${whole} 页` : `${frac}/8`;
}

function minsLabel(m) {
  if (!m) return "—";
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}` : `${m}m`;
}

function sceneRows(scenes) {
  return (scenes || []).map(s => [
    `#${s.scene_no}`, s.int_ext || "", s.heading || "", s.day_night === "NIGHT" ? "夜" : s.day_night === "DAY" ? "日" : (s.day_night || ""),
    (s.cast || []).join("、"), s.location || "", pagesLabel(s.pages_eighths), `${s.est_minutes || 0} 分钟`,
  ]);
}

const SCENE_HEADERS = ["场次", "INT/EXT", "场景标题", "日/夜", "演员", "地点", "页数", "预计"];

function totalsLine(t) {
  if (!t) return "";
  const bits = [
    `总页数 ${pagesLabel(t.pages_eighths)}`,
    `拍摄 ${minsLabel(t.shoot_minutes)}`,
    `转场 ${t.company_moves || 0} 次`,
    `用餐 ${t.meals || 0} 次`,
  ];
  if ((t.shoot_minutes || 0) > 11 * 60) bits.push("⚠️ 超过 11 小时安全线");
  return bits.join(" · ");
}

function renderRundown(el, p) {
  const title = document.createElement("div");
  title.className = "section-title";
  title.textContent = `${p.title || "拍摄通告单"}${p.day ? ` · ${p.day}` : ""}${p.date ? ` · ${p.date}` : ""}`;
  el.appendChild(title);

  const calls = document.createElement("div");
  calls.className = "call-strip";
  calls.innerHTML = [
    ["CREW CALL", p.crew_call], ["CAST CALL", p.cast_call], ["WRAP", p.wrap],
  ].filter(([, v]) => v).map(([k, v]) => `<div class="call-item"><span>${k}</span><b>${esc(v)}</b></div>`).join("")
    + (p.totals ? `<div class="call-item totals"><span>TOTALS</span><b>${esc(totalsLine(p.totals))}</b></div>` : "");
  el.appendChild(calls);

  if (p.scenes && p.scenes.length) {
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = "场次表（重点场次）· Stripboard";
    el.appendChild(h);
    const rows = sceneRows(p.scenes);
    el.appendChild(buildTable(SCENE_HEADERS, rows));
    el.appendChild(exportBtn("stripboard.csv", [SCENE_HEADERS, ...rows]));
  }

  if (p.blocks && p.blocks.length) {
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = "当日时间表 · Call Sheet";
    el.appendChild(h);
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    wrap.innerHTML = `<table class="tbl calltbl"><thead><tr><th>时间</th><th>类型</th><th>内容</th><th>时长</th></tr></thead><tbody>
      ${p.blocks.map(b => `<tr class="blk-${b.type}">
        <td class="mono">${esc(b.time || "")}</td>
        <td>${esc(blockIcon(b.type))} ${esc(b.type)}</td>
        <td>${esc(b.note || "")}</td>
        <td class="mono">${b.est_minutes ? b.est_minutes + "m" : ""}</td></tr>`).join("")}
    </tbody></table>`;
    el.appendChild(wrap);
  }

  if (p.cast_calls && p.cast_calls.length) {
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = "演员通告 · Cast Calls";
    el.appendChild(h);
    el.appendChild(buildTable(["演员", "角色", "到场", "备注"],
      p.cast_calls.map(c => [c.name, c.role || "", c.call || "", c.notes || ""])));
  }

  if (p.safety && p.safety.length) {
    const ul = document.createElement("ul");
    ul.className = "note-list safety";
    ul.innerHTML = p.safety.map(s => `<li>🦺 ${esc(s)}</li>`).join("");
    el.appendChild(ul);
  }
  if (p.notes && p.notes.length) {
    const ul = document.createElement("ul");
    ul.className = "note-list";
    ul.innerHTML = p.notes.map(s => `<li>▸ ${esc(s)}</li>`).join("");
    el.appendChild(ul);
  }
  renderReferences(el, p.references);
}

function blockIcon(type) {
  return ({ crew_call: "⏰", cast_call: "💄", setup: "🔧", scene: "🎬", move: "🚚", meal: "🍽", wrap: "🌙", buffer: "🧯" })[type] || "•";
}

function renderSchedule(el, p) {
  const title = document.createElement("div");
  title.className = "section-title";
  title.textContent = p.title || "拍摄日程";
  el.appendChild(title);
  if (p.strategy) {
    const s = document.createElement("p");
    s.className = "strategy";
    s.textContent = "📋 " + p.strategy;
    el.appendChild(s);
  }
  const allRows = [];
  for (const d of p.days || []) {
    const card = document.createElement("div");
    card.className = "day-card";
    card.innerHTML = `
      <div class="day-head">
        <span class="day-no">${esc(d.day || "")}</span>
        <span class="day-theme">${esc(d.theme || "")}</span>
        <span class="day-time">${esc(d.crew_call || "")}${d.wrap ? " – " + esc(d.wrap) : ""}</span>
        ${d.location ? `<span class="day-loc">📍 ${esc(d.location)}</span>` : ""}
      </div>
      <div class="day-totals">${esc(totalsLine(d.totals))}</div>`;
    el.appendChild(card);

    if (d.scenes && d.scenes.length) {
      const rows = sceneRows(d.scenes);
      allRows.push(...rows.map(r => [d.day, ...r]));
      el.appendChild(buildTable(SCENE_HEADERS, rows));
    } else if (d.tasks && d.tasks.length) {
      el.appendChild(buildTable(["时间", "任务", "地点", "备注"], d.tasks.map(tk => [tk.time, tk.task, tk.location, tk.notes])));
    }
    if (d.blocks && d.blocks.length) {
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      wrap.innerHTML = `<table class="tbl calltbl"><tbody>
        ${d.blocks.map(b => `<tr class="blk-${b.type}"><td class="mono">${esc(b.time || "")}</td>
          <td>${esc(blockIcon(b.type))} ${esc(b.note || "")}</td><td class="mono">${b.est_minutes ? b.est_minutes + "m" : ""}</td></tr>`).join("")}
      </tbody></table>`;
      el.appendChild(wrap);
    }
    for (const tip of (d.tips || (d.tip ? [d.tip] : []))) {
      const t = document.createElement("p");
      t.className = "day-tip";
      t.textContent = "💡 " + tip;
      el.appendChild(t);
    }
  }
  el.appendChild(exportBtn("schedule.csv", [["天", ...SCENE_HEADERS], ...allRows]));

  if (p.cast_schedule && p.cast_schedule.length) {
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = "演员档期 · DOOD";
    el.appendChild(h);
    el.appendChild(buildTable(["演员", "天数", "备注"],
      p.cast_schedule.map(c => [c.name, (c.days || []).map(x => "D" + x).join(", "), c.notes || ""])));
  }
  if (p.risks && p.risks.length) {
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = "风险与备案";
    el.appendChild(h);
    el.appendChild(buildTable(["风险", "缓解方案"], p.risks.map(r => [r.risk, r.mitigation || ""])));
  }
  renderReferences(el, p.references);
}

function renderInspiration(el, p) {
  if (p.moods && p.moods.length) {
    for (const group of p.moods) {
      const head = document.createElement("div");
      head.className = "mood-head";
      head.innerHTML = `<span class="mood-name">${esc(group.mood)}</span><span class="mood-sub">这些片子在「${esc(group.mood)}」这一情绪上可以给你参考</span>`;
      el.appendChild(head);
      const row = document.createElement("div");
      row.className = "mood-films";
      row.innerHTML = (group.films || []).map(f => `
        <div class="mood-film">
          <a href="${esc(f.url)}" target="_blank" rel="noopener" class="mf-cover">
            <img src="${esc((f.frames && f.frames[0]) || f.cover)}" alt="${esc(f.title)}" loading="lazy" referrerpolicy="no-referrer">
            <span>${esc(f.duration || "")}${(f.frames || []).length ? " · 静帧" : ""}</span>
          </a>
          <a class="mf-title" href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}${f.personal ? " · 我的" : ""}</a>
          <div class="mf-meta">${f.script_page ? `<a href="${esc(f.script_page)}" target="_blank" rel="noopener">📄 剧本</a>` : ""}<a href="${esc(f.url)}" target="_blank" rel="noopener">▶ 原片</a></div>
        </div>`).join("");
      row.querySelectorAll(".mood-film").forEach((card, i) => {
        card.addEventListener("click", (ev) => {
          if (ev.target.closest("a")) return;
          openFrameModal(group.films[i]);
        });
      });
      el.appendChild(row);
    }
  }
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
      <p><strong>反转</strong>${esc(c.twist)}</p>
      ${(c.structure || []).length ? `<p><strong>结构</strong></p><ol class="c-struct">${c.structure.map(s => `<li>${esc(s)}</li>`).join("")}</ol>` : ""}
      ${(c.reference_patterns || []).length ? `<p><strong>可借鉴</strong>${esc(c.reference_patterns.join("；"))}</p>` : ""}
      ${c.visual_motif ? `<p><strong>视觉母题</strong>${esc(c.visual_motif)}</p>` : ""}
      ${c.sound_idea ? `<p><strong>声音想法</strong>${esc(c.sound_idea)}</p>` : ""}
      ${c.budget_note ? `<p class="c-budget"><strong>低成本方案</strong>${esc(c.budget_note)}</p>` : ""}
      ${(c.stills || []).length && !(p.moods || []).length ? `<div class="stills">${c.stills.map(st => `
        <a class="still" href="${esc(st.url)}" target="_blank" rel="noopener" title="${esc(st.title)}">
          <img src="${esc(st.cover)}" alt="${esc(st.title)}" loading="lazy" referrerpolicy="no-referrer">
          <span>${esc(st.title)} · ${esc(st.duration || "")}</span>
        </a>`).join("")}</div>` : ""}`;
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
  grid.className = "film-grid";
  for (const c of p.cases || []) {
    const card = document.createElement("div");
    card.className = "film-card";
    const views = c.stat && c.stat.view ? (c.stat.view > 10000 ? (c.stat.view / 10000).toFixed(1) + " 万" : c.stat.view) : "";
    card.innerHTML = `
      <a class="film-cover" href="${esc(c.url || "#")}" target="_blank" rel="noopener">
        <img src="${esc(c.cover || "")}" alt="${esc(c.title)}" loading="lazy" referrerpolicy="no-referrer">
        <span class="film-dur">${esc(c.duration || "")}</span>
      </a>
      <div class="film-body">
        <a class="film-title" href="${esc(c.url || "#")}" target="_blank" rel="noopener">${esc(c.title)}</a>
        <div class="film-meta">${esc(c.type || "短片")}${c.crew ? " · " + esc(c.crew) : ""}${views ? " · " + esc(String(views)) + "播放" : ""}</div>
        ${c.logline ? `<p class="film-desc">${esc(c.logline)}</p>` : ""}
        <div class="film-tags">${(c.tags || []).map(t => `<span>${esc(t)}</span>`).join("")}</div>
        <div class="film-foot">
          <a href="${esc(c.url || "#")}" target="_blank" rel="noopener">▶ 在 Bilibili 打开</a>
          <span class="verified">✓ 来源已核验</span>
        </div>
      </div>`;
    grid.appendChild(card);
  }
  el.appendChild(grid);
  const note = document.createElement("p");
  note.className = "source-note";
  note.textContent = "以上为 Bilibili 公开元数据（标题/时长/UP主/简介/链接），不含虚构的制作数据；版权归原作者。";
  el.appendChild(note);
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
      if (chip.dataset.tool === "library") {
        toggleLibrary();
        return;
      }
      document.querySelectorAll(".chip-tool").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      state.tool = chip.dataset.tool || "";
    });
  });

  $("#sendBtn").addEventListener("click", () => {
    const text = $("#input").value.trim();
    if (!text && !state.script) return;
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

  // 我的灵感库
  $("#libClose").addEventListener("click", () => $("#libraryPanel").classList.add("hidden"));
  $("#fmClose").addEventListener("click", () => $("#frameModal").classList.add("hidden"));
  $("#frameModal").addEventListener("click", (e) => {
    if (e.target === $("#frameModal")) $("#frameModal").classList.add("hidden");
  });
  $("#libAdd").addEventListener("click", addLibraryFilm);
  $("#libScriptBtn").addEventListener("click", () => $("#libScriptFile").click());
  $("#libScriptFile").addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    $("#libScriptName").textContent = "解析中…";
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/script/parse", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "解析失败");
      state.libScript = { name: data.filename, text: data.text };
      $("#libScriptName").textContent = "📄 " + data.filename;
    } catch (err) {
      state.libScript = null;
      $("#libScriptName").textContent = "❌ " + err.message;
    }
  });

  // 剧本上传
  $("#attachBtn").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) uploadScript(file);
    e.target.value = "";
  });
  $("#scriptRemove").addEventListener("click", () => {
    state.script = null;
    renderScriptChip();
  });
}

function openFrameModal(film) {
  $("#fmTitle").textContent = film.title + (film.duration ? " · " + film.duration : "");
  const frames = film.frames || [];
  $("#fmGrid").innerHTML = frames.length
    ? frames.map(u => `<img src="${esc(u)}" loading="lazy" alt="${esc(film.title)}">`).join("")
    : `<img src="${esc(film.cover)}" alt="${esc(film.title)}">`;
  $("#fmLinks").innerHTML = [
    film.script_page ? `<a href="${esc(film.script_page)}" target="_blank" rel="noopener">📄 剧本</a>` : "",
    `<a href="${esc(film.url)}" target="_blank" rel="noopener">▶ 原片</a>`,
  ].join("");
  $("#frameModal").classList.remove("hidden");
}

async function toggleLibrary() {
  const panel = $("#libraryPanel");
  panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden")) refreshLibrary();
}

async function refreshLibrary() {
  const list = $("#libList");
  list.innerHTML = "<div class='lib-empty'>加载中…</div>";
  try {
    const res = await fetch("/api/library/personal");
    const data = await res.json();
    const films = data.films || [];
    if (!films.length) {
      list.innerHTML = "<div class='lib-empty'>还没有收藏。粘贴一条 Bilibili 链接试试。</div>";
      return;
    }
    list.innerHTML = films.map(f => `
      <div class="lib-item">
        ${f.cover ? `<img src="${esc(f.cover)}" referrerpolicy="no-referrer" alt="">` : ""}
        <div class="lib-info">
          <a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}</a>
          <span>${esc((f.moods || []).join(" / "))}</span>
        </div>
        <button class="sc-remove" data-id="${esc(f.id)}">✕</button>
      </div>`).join("");
    list.querySelectorAll("button[data-id]").forEach(btn => {
      btn.addEventListener("click", async () => {
        await fetch("/api/library/personal/" + encodeURIComponent(btn.dataset.id), { method: "DELETE" });
        refreshLibrary();
      });
    });
  } catch (e) {
    list.innerHTML = "<div class='lib-empty'>读取失败</div>";
  }
}

async function addLibraryFilm() {
  const url = $("#libUrl").value.trim();
  const title = $("#libTitle").value.trim();
  const moods = $("#libMoods").value.split(/[,，、\s]+/).filter(Boolean);
  if (!url && !title) return;
  const btn = $("#libAdd");
  btn.disabled = true;
  btn.textContent = "添加中…";
  try {
    const res = await fetch("/api/library/personal", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url, title, moods,
        script_text: state.libScript ? state.libScript.text : "",
        script_name: state.libScript ? state.libScript.name : "",
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "添加失败");
    $("#libUrl").value = ""; $("#libTitle").value = ""; $("#libMoods").value = "";
    state.libScript = null;
    $("#libScriptName").textContent = "";
    refreshLibrary();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "添加";
  }
}

async function uploadScript(file) {
  const chip = $("#scriptChip");
  chip.classList.remove("hidden");
  $("#scriptName").textContent = file.name;
  $("#scriptMeta").textContent = "解析中…";
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/api/script/parse", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "解析失败");
    state.script = { name: data.filename, text: data.text, chars: data.chars };
    renderScriptChip();
  } catch (err) {
    state.script = null;
    $("#scriptMeta").textContent = "❌ " + err.message;
  }
}

function renderScriptChip() {
  const chip = $("#scriptChip");
  if (!state.script) {
    chip.classList.add("hidden");
    $("#scriptName").textContent = "";
    $("#scriptMeta").textContent = "";
    return;
  }
  chip.classList.remove("hidden");
  $("#scriptName").textContent = state.script.name;
  $("#scriptMeta").textContent = `${state.script.chars.toLocaleString()} 字 · 已就绪`;
}

bindEvents();
initHealth();
