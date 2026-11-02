#!/bin/sh
# launchd 에 크롤러를 등록한다. 다시 실행하면 갱신된다. 해제: launchctl bootout gui/$(id -u)/kr.pandomeal.crawler
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
UV=$(command -v uv)
DEST="$HOME/Library/LaunchAgents/kr.pandomeal.crawler.plist"
mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"
sed -e "s#__ROOT__#$ROOT#g" -e "s#__UV__#$UV#g" "$ROOT/scripts/kr.pandomeal.crawler.plist.template" > "$DEST"
launchctl bootout "gui/$(id -u)/kr.pandomeal.crawler" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "등록 완료: $DEST (로그: $ROOT/logs/crawler.log)"
