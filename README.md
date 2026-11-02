# pandomeal

판교도서관 구내식당 [주간식단표 게시판](https://www.snlib.go.kr/pg/menu/10511/bbs/20023/bbsPostList.do)에서 새 식단표 이미지를 받아 `images/`에 저장하고, macOS Vision OCR로 요일별 중식/석식을 읽어 `data/<주 시작일>.json`으로 저장한다.

## 요구 사항

- macOS 13 이상 (Vision 한국어 OCR)
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)

## 설치

```sh
git clone https://github.com/yangsijun/pandomeal.git
cd pandomeal
./scripts/install-launchd.sh   # 매일 09:00 자동 실행 등록 (등록 직후 한 번 실행)
```

clone한 위치와 uv 경로는 스크립트가 알아서 넣는다. 폴더를 옮겼으면 스크립트를 다시 실행한다.

## 수동 실행

```sh
uv run python pandomeal.py            # 새 주차만 받기
uv run python pandomeal.py --pages 5  # 과거분까지 (목록 1페이지 = 10주)
uv run python pandomeal.py --force    # 이미 받은 주도 다시 받아 OCR
```

## 관리

```sh
cat logs/crawler.log                                        # 저장/실패 기록
launchctl kickstart -k gui/$(id -u)/kr.pandomeal.crawler    # 자동 실행 작업을 지금 실행
launchctl bootout gui/$(id -u)/kr.pandomeal.crawler && rm ~/Library/LaunchAgents/kr.pandomeal.crawler.plist  # 해제
uv run pytest                                               # 테스트
```

실패해도 알림은 없다. 로그의 `[실패]` 줄로 확인한다.

## OCR 오타 보정

Vision이 반복해서 틀리는 글자(`짱→장`, `짜정→짜장` 등)는 `pandomeal.py`의 `OCR_FIXES`에서 고친다. 원본 이미지와 대조해 확인한 것만 추가한다.
