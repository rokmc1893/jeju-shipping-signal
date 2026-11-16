#!/bin/bash
# macOS에서 더블클릭해 갤럭시 크기의 Android 앱으로 개발한다.
set -e
cd "$(dirname "$0")"
.venv/bin/python scripts/mobile_dev.py
