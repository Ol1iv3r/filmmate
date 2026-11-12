#!/bin/bash
# Filmmate 前端一键启动（自动处理本机 npm 缓存目录问题）
cd "$(dirname "$0")"
export npm_config_cache="${npm_config_cache:-$PWD/../.npm-cache}"
echo "启动 Filmmate 前端 → http://localhost:5173（Ctrl+C 停止）"
npm run dev
