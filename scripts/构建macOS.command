#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'echo "构建失败，请查看上方错误。按回车关闭。"; read -r' ERR
command -v python3
command -v ffmpeg
python3 -m venv .desktop-build
.desktop-build/bin/python -m pip install -e '.[build,local]'
.desktop-build/bin/python scripts/build_desktop.py
open dist
