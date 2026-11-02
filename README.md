# pandomeal

판교도서관 구내식당 [주간식단표 게시판](https://www.snlib.go.kr/pg/menu/10511/bbs/20023/bbsPostList.do)에서 새 식단표 이미지를 받아 `images/`에 저장하고, macOS Vision OCR로 요일별 중식/석식을 읽어 `data/<주 시작일>.json`으로 저장한다. 토큰을 넣으면 tntworks 이슈 [TNT-477](https://works.tntlabs.dev/issue/TNT-477)에 이번 주 식단 카드를 붙인다.

운영은 tntworks 와 같은 맥 미니에서 한다. tntworks 와 같은 방식으로 숨은 서비스 계정(`pandomeal`)과 시스템 LaunchDaemon(`xyz.tntlab.pandomeal`)을 쓰므로, 아무도 로그인하지 않아도 매일 09:00 에 돈다. FileVault 잠금 화면에서 멈춘 동안은 돌지 않는다 (tntworks `docs/OPERATIONS.md` "재부팅과 FileVault").

| 무엇 | 위치 |
|---|---|
| 코드·데이터 (`data/`, `images/`) | `/Users/pandomeal/app` (홈 700) |
| 환경변수 | `/Users/pandomeal/app/.env` (600) |
| 로그 | `/Users/pandomeal/app/logs/crawler.log` |
| launchd | `/Library/LaunchDaemons/xyz.tntlab.pandomeal.plist` |
| uv | root 소유 `/usr/local/bin/uv` |

## 설치·갱신 (맥 미니)

1. **tntworks 앱 (관리자, 처음 한 번).** 설정 > 앱 > "매니페스트로 설치"에 `tntworks/manifest.json` 을 붙여 넣고, 앱 상세 > 토큰 > 발급. `twk_…` 는 한 번만 보인다.
2. **uv (처음 한 번).**
   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
   ```
3. **설치.** 관리자 계정에서:
   ```sh
   git clone https://github.com/yangsijun/pandomeal.git && cd pandomeal
   sudo ./scripts/install-service.sh
   ```
   계정이 없으면 만들고, 이 clone 의 **커밋된 HEAD** 를 `/Users/pandomeal/app` 에 펼친 뒤 등록하고 바로 한 번 실행한다. `data/`·`images/`·`logs/`·`.env` 는 덮어쓰지 않는다.
4. **토큰.** `sudo nano /Users/pandomeal/app/.env` 에 `TNTWORKS_TOKEN` 을 넣는다 (`TNTWORKS_ISSUE=TNT-477` 은 들어 있다). 비워두면 크롤링만 한다.
5. **확인.** `sudo launchctl kickstart -k system/xyz.tntlab.pandomeal` 후 로그에 `[카드] … 카드 갱신` 이 찍히고 TNT-477 에 카드가 붙으면 끝.

코드를 고친 뒤에는 관리자 clone 에서 `git pull && sudo ./scripts/install-service.sh` 를 다시 실행한다.

## 수동 실행·관리

```sh
sudo launchctl kickstart -k system/xyz.tntlab.pandomeal               # 지금 한 번 실행
sudo tail -f /Users/pandomeal/app/logs/crawler.log                     # 저장·카드·실패 기록
sudo launchctl print system/xyz.tntlab.pandomeal | grep -E 'state|last exit'
# 옵션을 줘서 직접 실행 (--pages 5: 과거 50주까지, --force: 받은 주도 다시 OCR)
sudo -u pandomeal -H sh -c 'cd /Users/pandomeal/app && /usr/local/bin/uv run python pandomeal.py --pages 5'
# 해제 (계정과 데이터는 남는다)
sudo launchctl bootout system/xyz.tntlab.pandomeal && sudo rm /Library/LaunchDaemons/xyz.tntlab.pandomeal.plist
```

실패해도 알림은 없다. 로그의 `[실패]` 줄로 확인한다.

## 개발

macOS 13 이상과 uv 가 있으면 어느 맥에서든 clone 해서 `uv run python pandomeal.py`(크롤링, 토큰은 `.env`)와 `uv run pytest` 를 돌릴 수 있다.

## OCR 오타 보정

Vision이 반복해서 틀리는 글자(`짱→장`, `짜정→짜장` 등)는 `pandomeal.py`의 `OCR_FIXES`에서 고친다. 원본 이미지와 대조해 확인한 것만 추가한다.
