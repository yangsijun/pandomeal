"""실제 식단표 이미지로 OCR → 표 복원 결과를 검증한다 (macOS 전용)."""

from pathlib import Path

import pytest

from pandomeal import ocr, parse_table

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def week_1102():
    return parse_table(ocr(FIXTURES / "2026-11-02.jpg"), 2026)


@pytest.fixture(scope="module")
def week_0914():
    return parse_table(ocr(FIXTURES / "2026-09-14.jpg"), 2026)


def test_seven_days_with_dates(week_1102):
    assert [d["date"] for d in week_1102] == [f"2026-11-0{i}" for i in range(2, 9)]
    assert [d["weekday"] for d in week_1102] == list("월화수목금토일")


def test_lunch_and_dinner_split(week_1102):
    mon = week_1102[0]
    assert mon["lunch"] == [
        "잡곡밥/백미밥", "황태미역국", "깻잎콩불고기", "도토리묵참나물무침",
        "애호박나물", "배추김치", "서비스코너:소면",
    ]
    assert mon["dinner"] == ["백미밥", "등촌샤브칼국수", "치킨유린기", "청경채계란볶음", "유채나물", "배추김치"]


def test_sunday_without_service_corner(week_1102):
    sun = week_1102[6]
    assert len(sun["lunch"]) == 6 and sun["lunch"][-1] == "배추김치"
    assert sun["dinner"][0] == "백미밥"


def test_spaces_removed(week_1102):
    assert "야채계란볶음밥" in week_1102[2]["dinner"]


def test_known_ocr_typos_fixed(week_1102, week_0914):
    # Vision 원문: 양배주샐러드, 시래기된짱나물, 팽이버섯된자국, 짜정덮밥, 양배추찜&쌈자
    assert week_1102[1]["lunch"][-1] == "서비스코너:양배추샐러드"
    assert "시래기된장나물" in week_1102[3]["dinner"]
    assert "팽이버섯된장국" in week_1102[5]["dinner"]
    assert "짜장덮밥" in week_0914[5]["lunch"]
    assert "양배추찜&쌈장" in week_0914[0]["dinner"]


def test_two_headers_in_one_ocr_box(week_0914):
    # 이 이미지는 OCR이 "09월18일 09월19일"을 한 박스로 읽는다.
    assert [d["date"][5:] for d in week_0914] == ["09-14", "09-15", "09-16", "09-17", "09-18", "09-19", "09-20"]
    assert week_0914[4]["lunch"][1] == "콩비지찌개"
    assert week_0914[5]["lunch"][1] == "아욱된장국"


def test_footnote_star_misread_as_1():
    # 회귀(11/9 주): 첫 원산지 주석의 "*" 를 OCR 이 "1" 로 읽어 주석이 표 안으로 들어오고 석식이 중식에 섞였다.
    week = parse_table(ocr(FIXTURES / "2026-11-09.jpg"), 2026)
    thu = week[3]
    assert thu["lunch"][-1] == "서비스코너:소면" and "고추장제육볶음" not in thu["lunch"]
    assert thu["dinner"] == ["백미밥", "시래기된장국", "고추장제육볶음", "교자물만두&초간정", "참나물무침", "배추김치"]
    assert all("국내산" not in x for d in week for x in d["lunch"] + d["dinner"])
