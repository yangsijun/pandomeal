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


# ---- 매일 댓글

import pandomeal  # noqa: E402
from pandomeal import comment_body, post_daily_comment  # noqa: E402


def test_comment_body_plain_text():
    week = make_week()
    assert comment_body(week["days"][1]) == (
        "11/3(화) 중식: 잡곡밥/백미밥, 황태미역국, 깻잎콩불고기, 배추김치\n석식: 백미밥, 등촌샤브칼국수, 배추김치"
    )
    assert comment_body(week["days"][4]) == "11/6(금) 휴관"


class FakeApi:
    def __init__(self):
        self.calls = []
        self.next_id = 0

    def __call__(self, method, path, body=None, allow_404=False):
        self.calls.append((method, path, allow_404))
        self.next_id += 1
        outer = self

        class R:
            def json(self):
                return {"id": f"c{outer.next_id}"}
        return R()


def test_daily_comment_once_per_day_and_deletes_previous(tmp_path, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(pandomeal, "_api", api)
    monkeypatch.setattr(pandomeal, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pandomeal, "COMMENT_STATE", tmp_path / "comment-state.json")
    monkeypatch.setenv("TNTWORKS_ISSUE", "TNT-477")
    week = make_week()

    assert post_daily_comment(week, date(2026, 11, 2)) is True
    assert api.calls == [("POST", "/api/issues/TNT-477/comments", False)]

    assert post_daily_comment(week, date(2026, 11, 2)) is False  # 같은 날 두 번째 실행
    assert len(api.calls) == 1

    assert post_daily_comment(week, date(2026, 11, 3)) is True
    assert api.calls[1:] == [
        ("POST", "/api/issues/TNT-477/comments", False),
        ("DELETE", "/api/issues/TNT-477/comments/c1", True),
    ]
    assert json.loads((tmp_path / "comment-state.json").read_text()) == {"date": "2026-11-03", "id": "c2"}
