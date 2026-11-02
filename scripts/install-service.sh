#!/bin/bash
# 맥 미니에 크롤러를 시스템 서비스로 설치·갱신한다 (여러 번 실행해도 된다). 관리자 계정의 clone 에서:
#   sudo ./scripts/install-service.sh
# - 숨은 서비스 계정 pandomeal 을 만든다 (로그인 불가, 홈 700). tntworks·tntagent 와 같은 방식.
# - 이 clone 의 커밋된 HEAD 를 /Users/pandomeal/app 에 펼친다. data·images·logs·.env 는 건드리지 않는다.
# - /Library/LaunchDaemons/xyz.tntlab.pandomeal.plist 로 등록하고 바로 한 번 실행한다.
set -euo pipefail

SVC=pandomeal
LABEL=xyz.tntlab.pandomeal
SVC_HOME=/Users/$SVC
APP=$SVC_HOME/app
UV=/usr/local/bin/uv
SRC=$(cd "$(dirname "$0")/.." && pwd)
PLIST=/Library/LaunchDaemons/$LABEL.plist

die() { echo "오류: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] && [ -n "${SUDO_USER:-}" ] || die "관리자 계정에서 sudo 로 실행하세요"
[ -x "$UV" ] || die "$UV 가 없습니다. 설치: curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh"
if [ -n "$(sudo -u "$SUDO_USER" git -C "$SRC" status --porcelain)" ]; then
  echo "주의: 커밋하지 않은 변경은 설치되지 않습니다 (커밋된 HEAD 만 펼친다)" >&2
fi

if ! dscl . -read "/Users/$SVC" >/dev/null 2>&1; then
  uid=""
  for u in $(seq 450 499); do dscl . -search /Users UniqueID "$u" | grep -q . || { uid=$u; break; }; done
  [ -n "$uid" ] || die "450~499 에 빈 UID 가 없습니다"
  dscl . -create "/Users/$SVC"
  dscl . -create "/Users/$SVC" UniqueID "$uid"
  dscl . -create "/Users/$SVC" PrimaryGroupID 20
  dscl . -create "/Users/$SVC" RealName "pandomeal Service"
  dscl . -create "/Users/$SVC" NFSHomeDirectory "$SVC_HOME"
  dscl . -create "/Users/$SVC" UserShell /usr/bin/false
  dscl . -create "/Users/$SVC" Password '*'
  dscl . -create "/Users/$SVC" IsHidden 1
  echo "계정 $SVC (UID $uid) 생성"
fi

mkdir -p "$APP/logs"
# git 은 저장소 주인(관리자)으로 실행한다: root 로 남의 저장소를 읽으면 git 이 거부한다.
sudo -u "$SUDO_USER" git -C "$SRC" archive HEAD | tar -x -C "$APP"
[ -f "$APP/.env" ] || cp "$APP/.env.example" "$APP/.env"
touch "$APP/logs/crawler.log"  # launchd 가 root 소유로 만들지 않게 미리 만든다
chown -R "$SVC:staff" "$SVC_HOME"
chmod 700 "$SVC_HOME"
chmod 600 "$APP/.env"

install -o root -g wheel -m 644 "$APP/scripts/$LABEL.plist" "$PLIST"
launchctl bootout "system/$LABEL" 2>/dev/null || true
launchctl bootstrap system "$PLIST"

echo "설치 완료: $APP ($(sudo -u "$SUDO_USER" git -C "$SRC" rev-parse --short HEAD))"
grep -q '^TNTWORKS_TOKEN=.' "$APP/.env" || echo "tntworks 카드를 쓰려면: sudo nano $APP/.env 에 TNTWORKS_TOKEN 을 넣고 이 스크립트를 다시 실행"
echo "로그: sudo tail $APP/logs/crawler.log"
