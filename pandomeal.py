"""판교도서관 구내식당 주간식단표 크롤러.

게시판 목록에서 아직 저장하지 않은 주간식단표 글을 찾아 첨부 이미지를
images/<주 시작일(월요일)>.<확장자> 로 받고, macOS Vision OCR로 표를 읽어
data/<주 시작일>.json 으로 저장한다.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime
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
    bottom = min((b.y for b in boxes if b.text.startswith("*") and b.y > top), default=1.0)

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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
