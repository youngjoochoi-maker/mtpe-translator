#!/bin/bash
# 인터넷에서 받은 앱은 macOS 가 '손상됨'으로 막는 경우가 있습니다.
# 이 파일을 더블클릭(안 열리면: 우클릭 → 열기)하면 같은 폴더의 .app 에서 차단 표시를 제거하고 실행합니다.
cd "$(dirname "$0")"
APP=$(ls -d *.app 2>/dev/null | head -1)
if [ -z "$APP" ]; then echo "같은 폴더에 .app 이 없습니다."; read -p "엔터를 누르면 닫힙니다."; exit 1; fi
echo "차단 표시 제거: $APP"
xattr -cr "$APP"
echo "실행합니다…"
open "$APP"
