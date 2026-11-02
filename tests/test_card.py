import json
from datetime import date
from pathlib import Path

from pandomeal import APP_SLUG, build_card

MANIFEST = json.loads((Path(__file__).parents[1] / "tntworks" / "manifest.json").read_text())


def make_week():
    days = []
    for i, wd in enumerate("월화수목금토일"):
        d = date(2026, 11, 2 + i).isoformat()
        if wd == "금":
            days.append({"date": d, "weekday": wd, "lunch": ["휴관"], "dinner": ["휴관"]})
        else:
            days.append({"date": d, "weekday": wd,
                         "lunch": ["잡곡밥/백미밥", "황태미역국", "깻잎콩불고기", "배추김치"],
                         "dinner": ["백미밥", "등촌샤브칼국수", "배추김치"]})
    return {"week_start": "2026-11-02", "source_url": "https://example.com/post?postIdx=1", "days": days}


def test_slug_matches_manifest():
    assert MANIFEST["slug"] == APP_SLUG
    assert set(MANIFEST["scopes"]) >= {"attachments:write"}


def test_today_highlighted():
    card = build_card(make_week(), date(2026, 11, 3))
    meta = card["meta"]
    assert card["kind"] == "pandomeal" and card["url"] == "https://example.com/post?postIdx=1"
    assert meta["status"] == {"label": "오늘 11/3(화)", "tone": "info"}
    assert meta["attributes"][0] == {"name": "오늘 중식", "value": "잡곡밥/백미밥, 황태미역국, 깻잎콩불고기, 배추김치"}
    assert meta["messages"][1]["subject"] == "11/3 (화) · 오늘"
    assert len(meta["messages"]) == 7


def test_holiday():
    meta = build_card(make_week(), date(2026, 11, 6))["meta"]
    assert meta["status"] == {"label": "오늘 휴관", "tone": "warning"}
    assert meta["attributes"] == []


def test_within_tntworks_limits():
    week = make_week()
    week["days"][0]["lunch"] = ["아주긴메뉴이름" * 20] * 10
    meta = build_card(week, date(2026, 11, 2))["meta"]
    assert len(meta["title"]) <= 200 and len(meta["status"]["label"]) <= 40
    assert len(meta["attributes"]) <= 12
    assert all(len(a["name"]) <= 40 and len(a["value"]) <= 200 for a in meta["attributes"])
    assert len(meta["messages"]) <= 20
    assert all(len(m["subject"]) <= 200 and len(m["body"]) <= 4000 and len(m["timestamp"]) <= 40
               for m in meta["messages"])
