"""판교도서관 구내식당 주간식단표 크롤러.

게시판 목록에서 아직 저장하지 않은 주간식단표 글을 찾아 첨부 이미지를
images/<주 시작일(월요일)>.<확장자> 로 받고, macOS Vision OCR로 표를 읽어
data/<주 시작일>.json 으로 저장한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.snlib.go.kr"
LIST_URL = f"{BASE}/pg/menu/10511/bbs/20023/bbsPostList.do"
DETAIL_URL = f"{BASE}/pg/menu/10511/bbs/20023/bbsPostDetail.do"
DOWNLOAD_URL = f"{BASE}/cmmn/file/fileDownload.do"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
IMAGE_DIR = ROOT / "images"

WEEKDAYS = "월화수목금토일"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

# Vision이 이 식단표에서 반복해서 틀리는 글자. 실제 이미지와 대조해 확인한 것만 넣는다.
OCR_FIXES = [
    (re.compile(r"짱"), "장"),  # 된짱나물, 쌈짱나물 등. 메뉴명에 '짱'이 실제로 쓰일 일은 거의 없다.
    (re.compile(r"된자국"), "된장국"),
    (re.compile(r"양배주"), "양배추"),
    (re.compile(r"짜정"), "짜장"),
    (re.compile(r"쌈자$"), "쌈장"),
]

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (pandomeal menu crawler)"


# ---------------------------------------------------------------- 게시판


@dataclass
class Post:
    idx: str
    title: str
    posted: date  # 작성일

    @property
    def week_start(self) -> date:
        # 제목 예: "주간식단표(11.  2. ~ 11.  8.)". 연도는 작성일에서 가져오되,
        # 12월 말에 올라온 1월 첫 주 식단처럼 해가 바뀌는 경우를 보정한다.
        m = re.search(r"\(\s*(\d{1,2})\.\s*(\d{1,2})\.", self.title)
        if not m:
            raise ValueError(f"제목에서 날짜를 찾을 수 없음: {self.title!r}")
        month, day = int(m[1]), int(m[2])
        year = self.posted.year
        if month < self.posted.month - 6:
            year += 1
        elif month > self.posted.month + 6:
            year -= 1
        return date(year, month, day)


def fetch_posts(page: int = 1) -> list[Post]:
    r = session.get(LIST_URL, params={"currentPageNo": page}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    posts = []
    for a in soup.select("td.title a[onclick*=fnDetail]"):
        title = a.get_text(strip=True)
        if "식단" not in title:
            continue
        idx = re.search(r"fnDetail\('(\d+)'\)", a["onclick"])[1]
        posted_td = a.find_parent("tr").find(string=re.compile(r"\d{4}-\d{2}-\d{2}"))
        posted = datetime.strptime(posted_td.strip(), "%Y-%m-%d").date()
        posts.append(Post(idx, title, posted))
    return posts


def fetch_image_attachment(post: Post) -> tuple[bytes, str]:
    """글의 첫 번째 이미지 첨부파일 (내용, 확장자)."""
    r = session.get(DETAIL_URL, params={"postIdx": post.idx}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for p in soup.select("p.attach"):
        name = p.get_text(" ", strip=True)
        link = p.select_one("a[onclick*=fnFileDownload]")
        ext = next((e for e in IMAGE_EXTS if e in name.lower()), None)
        if not link or not ext:
            continue
        file_idx, file_sn = re.search(r"fnFileDownload\('(\d+)',\s*'(\d+)'\)", link["onclick"]).groups()
        d = session.get(DOWNLOAD_URL, params={"fileIdx": file_idx, "fileSn": file_sn}, timeout=60)
        d.raise_for_status()
        return d.content, ".jpg" if ext == ".jpeg" else ext
    raise RuntimeError(f"이미지 첨부파일 없음: {post.title} (postIdx={post.idx})")


# ---------------------------------------------------------------- OCR / 표 복원


@dataclass
class Box:
    text: str
    x: float  # 왼쪽, 0~1
    y: float  # 위쪽, 0~1 (위에서 아래로 증가)
    w: float
    h: float

    @property
    def xc(self) -> float:
        return self.x + self.w / 2

    @property
    def yc(self) -> float:
        return self.y + self.h / 2


def ocr(image_path: Path) -> list[Box]:
    from ocrmac import ocrmac  # macOS 전용이라 OCR이 필요할 때만 불러온다

    results = ocrmac.OCR(
        str(image_path), language_preference=["ko-KR", "en-US"], recognition_level="accurate"
    ).recognize()
    # Vision 좌표는 왼쪽 아래 원점이라 위쪽 원점으로 뒤집는다.
    return [Box(t, x, 1 - y - h, w, h) for t, _conf, (x, y, w, h) in results]


def parse_table(boxes: list[Box], year: int) -> list[dict]:
    """OCR 결과 박스를 요일별 중식/석식 목록으로 바꾼다.

    열: "11월02일" 같은 날짜 헤더의 x 위치. 행: 요일 행 아래부터 "*원산지" 주석 위까지.
    중식/석식 경계: 두 구역 사이에 항상 빈 행이 있으므로 행 간격이 가장 넓은 곳.
    """
    headers = []
    for b in boxes:
        # OCR이 이웃한 헤더 둘을 "09월18일 09월19일"처럼 한 박스로 읽기도 해서 폭을 나눈다.
        found = re.findall(r"(\d{1,2})월(\d{1,2})일", b.text.replace(" ", ""))
        if not found or re.sub(r"[\d월일\s]", "", b.text):
            continue
        w = b.w / len(found)
        for k, (mon, day) in enumerate(found):
            headers.append((Box(b.text, b.x + k * w, b.y, w, b.h), date(year, int(mon), int(day))))
    if not headers:
        raise ValueError("날짜 헤더(예: 11월02일)를 찾지 못함")
    headers.sort(key=lambda h: h[0].xc)
    if len(headers) > 1:
        half_col = statistics.median(b.xc - a.xc for (a, _), (b, _) in zip(headers, headers[1:])) / 2
    else:
        half_col = 0.08

    header_bottom = max(b.y + b.h for b, _ in headers)
    weekday_row = [b for b in boxes if b.text.strip() in WEEKDAYS and b.y >= header_bottom - 0.01]
    top = max((b.y + b.h for b in weekday_row), default=header_bottom + 0.03)
    # 원산지 주석은 "*" 로 시작하고 표 너비만큼 길다. OCR 이 "*" 를 "1" 로 읽기도 해서(11/9 주) 폭으로도 찾는다.
    bottom = min((b.y for b in boxes if b.y > top and (b.text.startswith("*") or b.w > 4 * half_col)), default=1.0)

    columns: dict[int, list[Box]] = {i: [] for i in range(len(headers))}
    for b in boxes:
        if not (top < b.yc < bottom):
            continue
        i = min(range(len(headers)), key=lambda i: abs(headers[i][0].xc - b.xc))
        if abs(headers[i][0].xc - b.xc) <= half_col:
            columns[i].append(b)

    split_y = _section_split([b.yc for col in columns.values() for b in col])

    days = []
    for i, (_, day) in enumerate(headers):
        col = sorted(columns[i], key=lambda b: b.y)
        days.append({
            "date": day.isoformat(),
            "weekday": WEEKDAYS[day.weekday()],
            "lunch": [_clean(b.text) for b in col if b.yc < split_y and _clean(b.text)],
            "dinner": [_clean(b.text) for b in col if b.yc >= split_y and _clean(b.text)],
        })
    return days


def _section_split(ycs: list[float]) -> float:
    rows = _cluster(sorted(ycs), tol=0.01)
    if len(rows) < 3:
        return float("inf")
    gaps = [(b - a, (a + b) / 2) for a, b in zip(rows, rows[1:])]
    widest, mid = max(gaps)
    # 가장 넓은 간격이 평소 행 간격과 비슷하면 구역이 하나뿐(석식 없음)이라고 본다.
    if widest < 1.5 * statistics.median(g for g, _ in gaps):
        return float("inf")
    return mid


def _cluster(values: list[float], tol: float) -> list[float]:
    groups: list[list[float]] = []
    for v in values:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [statistics.mean(g) for g in groups]


def _clean(text: str) -> str:
    # 메뉴명에는 띄어쓰기가 없는데 OCR이 "야채 계란볶음밥"처럼 공백을 넣기도 한다.
    text = re.sub(r"\s+", "", text)
    for pattern, repl in OCR_FIXES:
        text = pattern.sub(repl, text)
    return text


# ---------------------------------------------------------------- tntworks 앱 요약·댓글

APP_SLUG = "pandomeal"  # tntworks/manifest.json 의 slug 와 같아야 한다 (요약 API 경로에 들어간다)


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE 줄만 읽는다. 이미 설정된 환경변수가 우선한다."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _closed(day: dict) -> str | None:
    """휴관일이면 그 사유("휴관", "추석연휴" 등). 휴관일은 중식·석식 칸이 합쳐져 같은 글자 하나만 나온다."""
    if len(day["lunch"]) <= 1 and day["lunch"] == day["dinner"]:
        return (day["lunch"] or ["휴무"])[0]
    return None


# 이 시각부터 요약·댓글이 석식으로 바뀐다. 실행 시각(plist 의 10:00·17:00)과 맞춘다.
DINNER_FROM = time(17, 0)
MEAL_NAME = {"lunch": "중식", "dinner": "석식"}
# 매일 나와서 볼 필요가 없는 항목. 빼야 그날 달라지는 메뉴가 눈에 들어온다.
STAPLES = {"잡곡밥/백미밥", "백미밥", "배추김치", "백김치", "깍두기"}


def meal_at(now: datetime) -> str:
    return "lunch" if now.time() < DINNER_FROM else "dinner"


def dishes(day: dict, meal: str) -> list[str]:
    return [x for x in day[meal] if x not in STAPLES]


def _day_label(day: dict) -> str:
    return f"{_md(date.fromisoformat(day['date']))}({day['weekday']})"


def _day_of(week: dict | None, d: date) -> dict | None:
    return next((x for x in (week or {}).get("days", []) if x["date"] == d.isoformat()), None)


def build_summary(week: dict, now: datetime, next_week: dict | None = None) -> dict:
    """앱 페이지(사이드바 › 앱)에 올릴 요약. 지금 끼니 메뉴를 보여준다.

    요약은 보낼 때마다 통째로 바뀌므로 매번 전체를 만든다. next_week 는 내일이 다음 주일 때(일요일 석식 이후) 쓴다.
    """
    day = _day_of(week, now.date())
    meal = meal_at(now)
    # 메뉴마다 지표 타일 하나: 앱 페이지에서 가장 큰 글씨(20px)다. 식단표에 분류가 없으므로 이름표는 끼니 이름만 붙인다.
    if _closed(day):
        title, status, metrics = _closed(day), {"label": _day_label(day), "tone": "warning"}, []
    else:
        title = f"{_day_label(day)} {MEAL_NAME[meal]}"
        status = {"label": MEAL_NAME[meal], "tone": "info"}
        metrics = [{"label": MEAL_NAME[meal], "value": x[:40]} for x in dishes(day, meal)[:8]]

    # 다음 끼니 미리보기: 중식 때는 오늘 석식, 석식 때는 내일 중식.
    if meal == "lunch":
        nxt, nxt_meal = day, "dinner"
    else:
        tomorrow = now.date() + timedelta(days=1)
        nxt, nxt_meal = _day_of(week, tomorrow) or _day_of(next_week, tomorrow), "lunch"
    attributes = []
    if nxt:
        value = _closed(nxt) or ", ".join(dishes(nxt, nxt_meal)) or "-"
        attributes.append({"name": f"다음 · {_day_label(nxt)} {MEAL_NAME[nxt_meal]}", "value": value[:200]})

    return {
        "title": title[:200],
        "status": status,
        "metrics": metrics,
        "attributes": attributes,
        "links": [{"label": "원본 식단표", "url": week["source_url"]}],
    }


def current_week(today: date) -> dict | None:
    # 주 식단 파일(YYYY-MM-DD.json)만 본다. 같은 폴더의 comment-state.json 은 식단이 아니다.
    for path in sorted(DATA_DIR.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"), reverse=True):
        week = json.loads(path.read_text())
        if any(d["date"] == today.isoformat() for d in week["days"]):
            return week
    return None


def comment_body(day: dict, meal: str) -> str:
    """끼니 댓글. 구독자 푸시에는 앞 200자만 보이고 마크다운이 그대로 나오므로 평문으로 쓴다."""
    if _closed(day):
        return f"{_day_label(day)} {_closed(day)}"
    return f"{_day_label(day)} {MEAL_NAME[meal]}\n{', '.join(dishes(day, meal))}"


def _api(method: str, path: str, body: dict | None = None, allow_404: bool = False) -> requests.Response:
    base = os.environ.get("TNTWORKS_URL", "https://api.tntlabs.dev").rstrip("/")
    r = session.request(
        method, f"{base}{path}", json=body,
        headers={"Authorization": f"Bearer {os.environ['TNTWORKS_TOKEN']}"}, timeout=30,
    )
    if not r.ok and not (allow_404 and r.status_code == 404):
        raise RuntimeError(f"tntworks {method} {path} {r.status_code}: {r.text[:300]}")
    return r


def post_summary(week: dict, now: datetime) -> None:
    next_week = current_week(now.date() + timedelta(days=1))
    _api("PUT", f"/api/apps/{APP_SLUG}/summary", build_summary(week, now, next_week))


COMMENT_STATE = DATA_DIR / "comment-state.json"


def post_meal_comment(week: dict, now: datetime) -> bool:
    """지금 끼니 댓글을 끼니마다 한 번 달고 직전 댓글은 지운다. 이미 달았으면 False.

    새 댓글을 먼저 단 뒤 지운다: 순서를 바꾸면 작성이 실패했을 때 댓글이 하나도 없게 된다.
    """
    issue = os.environ["TNTWORKS_ISSUE"]
    meal = meal_at(now)
    day = next(d for d in week["days"] if d["date"] == now.date().isoformat())
    key = f"{day['date']}:{meal}"
    state = json.loads(COMMENT_STATE.read_text()) if COMMENT_STATE.exists() else {}
    if state.get("key") == key:
        return False
    if _closed(day) and state.get("key", "").startswith(day["date"]):
        return False  # 휴관 알림은 하루 한 번이면 된다
    new_id = _api("POST", f"/api/issues/{issue}/comments", {"body": comment_body(day, meal)}).json()["id"]
    DATA_DIR.mkdir(exist_ok=True)
    COMMENT_STATE.write_text(json.dumps({"key": key, "id": new_id}) + "\n")
    if state.get("id"):
        _api("DELETE", f"/api/issues/{issue}/comments/{state['id']}", allow_404=True)  # 이미 지워졌으면 무시
    return True


# ---------------------------------------------------------------- 실행


def process(post: Post, force: bool = False) -> Path | None:
    start = post.week_start
    out = DATA_DIR / f"{start.isoformat()}.json"
    if out.exists() and not force:
        return None

    # 이미지만 받아둔 주는 다시 내려받지 않고 OCR만 한다.
    existing = sorted(IMAGE_DIR.glob(f"{start.isoformat()}.*"))
    if existing and not force:
        image_path = existing[0]
    else:
        content, ext = fetch_image_attachment(post)
        IMAGE_DIR.mkdir(exist_ok=True)
        image_path = IMAGE_DIR / f"{start.isoformat()}{ext}"
        image_path.write_bytes(content)

    days = parse_table(ocr(image_path), start.year)
    # 12월 마지막 주처럼 주 안에서 해가 바뀌면 1월 날짜를 다음 해로 보정
    for d in days:
        if date.fromisoformat(d["date"]) < start:
            d["date"] = date.fromisoformat(d["date"]).replace(year=start.year + 1).isoformat()

    DATA_DIR.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "week_start": start.isoformat(),
        "title": post.title,
        "post_idx": post.idx,
        "source_url": f"{DETAIL_URL}?postIdx={post.idx}",
        "image": str(image_path.relative_to(ROOT)),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
    }, ensure_ascii=False, indent=2) + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", type=int, default=1, help="확인할 목록 페이지 수 (과거분 수집 시 늘린다)")
    ap.add_argument("--force", action="store_true", help="이미 저장된 주도 다시 받는다")
    args = ap.parse_args()
    load_env()

    failed = 0
    for page in range(1, args.pages + 1):
        for post in fetch_posts(page):
            try:
                out = process(post, force=args.force)
            except Exception as e:  # 한 주가 실패해도 나머지는 계속
                failed += 1
                print(f"[실패] {post.title}: {e}", file=sys.stderr)
                continue
            if out:
                print(f"[저장] {post.title} -> {out.relative_to(ROOT)}")

    # 토큰이 없으면 크롤링만 한다.
    if os.environ.get("TNTWORKS_TOKEN") and os.environ.get("TNTWORKS_ISSUE"):
        now = datetime.now()
        week = current_week(now.date())
        if week is None:
            print(f"[요약] {now.date()} 이 들어 있는 주 식단이 아직 없음")
        else:
            try:
                post_summary(week, now)
                print(f"[요약] 앱 페이지를 {now.date()} {MEAL_NAME[meal_at(now)]}으로 갱신")
            except Exception as e:
                failed += 1
                print(f"[실패] 앱 요약: {e}", file=sys.stderr)
            try:
                if post_meal_comment(week, now):
                    print(f"[댓글] {os.environ['TNTWORKS_ISSUE']} 에 {now.date()} {MEAL_NAME[meal_at(now)]} 댓글 (직전 댓글 삭제)")
            except Exception as e:
                failed += 1
                print(f"[실패] 댓글: {e}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
