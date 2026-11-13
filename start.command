#!/bin/bash
# Filmmate 一键启动（macOS）—— 等价于 Windows 的 start.bat。
# 用法：在 Finder 里双击本文件；或在终端运行 ./start.command
# 关闭本终端窗口 / 按 Ctrl+C 会同时停掉后端和前端。

cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo "❌ 找不到 .venv（后端虚拟环境）。先执行："
  echo "   python3 -m venv .venv"
  echo "   .venv/bin/pip install -r requirements.txt"
  read -n 1 -s -r -p "按任意键退出…"
  exit 1
fi

if [ ! -d "filmmate-web/node_modules" ]; then
  echo "❌ 找不到 filmmate-web/node_modules。先执行： cd filmmate-web && npm install"
  read -n 1 -s -r -p "按任意键退出…"
  exit 1
fi

# 本机 pip/npm 缓存目录权限有问题时，把 npm 缓存放进仓库（已在 .gitignore）
export npm_config_cache="${npm_config_cache:-$PWD/.npm-cache}"

echo "🎬 Filmmate 启动中…"
echo "   后端  http://127.0.0.1:8000"
echo "   前端  http://localhost:5173"
echo ""

.venv/bin/python app.py &
BACK_PID=$!

( cd filmmate-web && npm run dev -- --open ) &
FRONT_PID=$!

cleanup() {
  echo ""
  echo "正在停止…"
  kill "$FRONT_PID" "$BACK_PID" 2>/dev/null
  wait "$FRONT_PID" "$BACK_PID" 2>/dev/null
  echo "已停止。"
}
trap cleanup INT TERM EXIT

wait
