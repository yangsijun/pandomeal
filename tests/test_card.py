import json
from datetime import date, datetime
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


def test_lunch_before_1330_dinner_after():
    week = make_week()
    lunch = build_card(week, datetime(2026, 11, 3, 9, 0))
    assert lunch["kind"] == "pandomeal" and lunch["url"] == "https://example.com/post?postIdx=1"
    meta = lunch["meta"]
    assert meta["title"] == "중식 · 깻잎콩불고기"
    assert meta["status"] == {"label": "11/3(화)", "tone": "info"}
    assert meta["messages"] == [{"subject": "11/3(화) 중식", "body": "- 황태미역국\n- 깻잎콩불고기"}]  # 밥·김치 제외

    dinner = build_card(week, datetime(2026, 11, 3, 13, 30))["meta"]
    assert dinner["title"] == "석식 · 등촌샤브칼국수"
    assert dinner["messages"][0]["body"] == "- 등촌샤브칼국수"


def test_holiday():
    meta = build_card(make_week(), datetime(2026, 11, 6, 9, 0))["meta"]
    assert meta["title"] == "11/6(금) 휴관"
    assert meta["status"] == {"label": "휴관", "tone": "warning"}
    assert meta["messages"] == []


def test_within_tntworks_limits():
    week = make_week()
    week["days"][0]["lunch"] = ["아주긴메뉴이름" * 20] * 10
    meta = build_card(week, datetime(2026, 11, 2, 9, 0))["meta"]
    assert len(meta["title"]) <= 200 and len(meta["status"]["label"]) <= 40
    assert len(meta["messages"]) <= 20
    assert all(len(m["subject"]) <= 200 and len(m["body"]) <= 4000 for m in meta["messages"])


# ---- 끼니 댓글

import pandomeal  # noqa: E402
from pandomeal import comment_body, post_meal_comment  # noqa: E402


def test_comment_body_plain_text():
    week = make_week()
    assert comment_body(week["days"][1], "lunch") == "11/3(화) 중식\n황태미역국, 깻잎콩불고기"
    assert comment_body(week["days"][1], "dinner") == "11/3(화) 석식\n등촌샤브칼국수"
    assert comment_body(week["days"][4], "lunch") == "11/6(금) 휴관"


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


def test_comment_once_per_meal_and_deletes_previous(tmp_path, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(pandomeal, "_api", api)
    monkeypatch.setattr(pandomeal, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pandomeal, "COMMENT_STATE", tmp_path / "comment-state.json")
    monkeypatch.setenv("TNTWORKS_ISSUE", "TNT-477")
    week = make_week()
    POST = ("POST", "/api/issues/TNT-477/comments", False)

    assert post_meal_comment(week, datetime(2026, 11, 2, 9, 0)) is True
    assert api.calls == [POST]
    assert post_meal_comment(week, datetime(2026, 11, 2, 11, 0)) is False  # 같은 끼니 재실행
    assert len(api.calls) == 1

    assert post_meal_comment(week, datetime(2026, 11, 2, 13, 30)) is True  # 석식으로 넘어감
    assert api.calls[1:] == [POST, ("DELETE", "/api/issues/TNT-477/comments/c1", True)]
    assert json.loads((tmp_path / "comment-state.json").read_text()) == {"key": "2026-11-02:dinner", "id": "c2"}


def test_holiday_comment_once_a_day(tmp_path, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(pandomeal, "_api", api)
    monkeypatch.setattr(pandomeal, "COMMENT_STATE", tmp_path / "comment-state.json")
    monkeypatch.setenv("TNTWORKS_ISSUE", "TNT-477")
    week = make_week()
    assert post_meal_comment(week, datetime(2026, 11, 6, 9, 0)) is True
    assert post_meal_comment(week, datetime(2026, 11, 6, 13, 30)) is False
