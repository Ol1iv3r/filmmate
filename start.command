#!/bin/bash
# Filmmate 一键启动（macOS）
# 用法：在 Finder 里双击本文件；或在终端运行 ./start.command
# 启动 Python 服务，在 http://127.0.0.1:8000 提供已构建的 React 界面。
# 关闭此终端窗口或按 Ctrl+C 会停止服务。

set -u
cd "$(dirname "$0")" || exit 1

ROOT="$PWD"
LOG="$ROOT/start.log"
URL="http://127.0.0.1:8000"
PAUSE="${NO_PAUSE:-0}"

say() { printf '%s\n' "$*" | tee -a "$LOG"; }

pause_exit() {
  local code="${1:-0}"
  if [ "$PAUSE" != "1" ]; then
    echo ""
    read -n 1 -s -r -p "按任意键关闭窗口…"
  fi
  exit "$code"
}

: > "$LOG"
say "🎬 Filmmate 启动中…"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  say "❌ 找不到 .venv（Python 虚拟环境）"
  say "   先在项目目录执行："
  say "   python3 -m venv .venv"
  say "   .venv/bin/pip install -r requirements.txt"
  pause_exit 1
fi

health() { /usr/bin/curl -fsS -m 2 "$URL/api/health" >/dev/null 2>&1; }

# 已经启动过：直接打开，不重复占端口
if health; then
  say "✅ 服务已经在运行：$URL"
  /usr/bin/open "$URL" 2>/dev/null
  pause_exit 0
fi

if [ ! -f "$ROOT/filmmate-web/dist/index.html" ] || [ ! -d "$ROOT/filmmate-web/dist/assets" ]; then
  say "❌ Build the React frontend first: cd filmmate-web && npm ci && npm run build"
  pause_exit 1
fi

# 启动后端（日志写 start.log，终端也能看到）
"$ROOT/.venv/bin/python" "$ROOT/app.py" >>"$LOG" 2>&1 &
PID=$!

cleanup() {
  say ""
  say "正在停止…"
  kill "$PID" 2>/dev/null
  wait "$PID" 2>/dev/null
  say "已停止。"
}
trap 'cleanup; exit 0' INT TERM HUP

say "等待服务就绪…"
READY=0
for _ in $(seq 1 40); do
  if health; then READY=1; break; fi
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  sleep 0.5
done

if [ "$READY" != "1" ]; then
  say "❌ 启动失败，日志末尾："
  tail -20 "$LOG" | tee -a "$LOG"
  say ""
  say "常见原因：8000 端口被占用，或依赖没装全（.venv/bin/pip install -r requirements.txt）"
  pause_exit 1
fi

say "✅ 已启动：$URL"
/usr/bin/open "$URL" 2>/dev/null
say "关闭此窗口或按 Ctrl+C 停止服务。"
wait "$PID"
