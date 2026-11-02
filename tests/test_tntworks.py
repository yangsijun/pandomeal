import json
from datetime import date, datetime
from pathlib import Path

from pandomeal import APP_SLUG, build_summary

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
    assert set(MANIFEST["scopes"]) >= {"summary:write", "comments:write"}


def test_lunch_summary_shows_dishes_as_metrics():
    s = build_summary(make_week(), datetime(2026, 11, 3, 9, 0))
    assert s["title"] == "11/3(화) 중식"
    assert s["status"] == {"label": "중식", "tone": "info"}
    assert s["metrics"] == [{"label": "국", "value": "황태미역국"}, {"label": "주메뉴", "value": "깻잎콩불고기"}]  # 밥·김치 제외
    assert s["attributes"] == [{"name": "다음 · 11/3(화) 석식", "value": "등촌샤브칼국수"}]
    assert s["links"] == [{"label": "원본 식단표", "url": "https://example.com/post?postIdx=1"}]


def test_dinner_summary_previews_tomorrow_lunch():
    s = build_summary(make_week(), datetime(2026, 11, 5, 13, 30))
    assert s["title"] == "11/5(목) 석식"
    assert s["attributes"] == [{"name": "다음 · 11/6(금) 중식", "value": "휴관"}]


def test_sunday_dinner_uses_next_week():
    week = make_week()
    nxt = make_week()
    nxt["days"] = [dict(nxt["days"][0], date="2026-11-09")]
    s = build_summary(week, datetime(2026, 11, 8, 18, 0), nxt)
    assert s["attributes"][0]["name"] == "다음 · 11/9(월) 중식"
    assert build_summary(week, datetime(2026, 11, 8, 18, 0))["attributes"] == []  # 다음 주 식단이 아직 없음


def test_holiday():
    s = build_summary(make_week(), datetime(2026, 11, 6, 9, 0))
    assert s["title"] == "11/6(금) 휴관"
    assert s["status"] == {"label": "휴관", "tone": "warning"}
    assert s["metrics"] == []


def test_service_corner_tile():
    week = make_week()
    week["days"][0]["lunch"] += ["서비스코너:소면"]
    assert build_summary(week, datetime(2026, 11, 2, 9, 0))["metrics"][-1] == {"label": "서비스코너", "value": "소면"}


def test_within_summary_limits():
    week = make_week()
    week["days"][0]["lunch"] = ["아주긴메뉴이름" * 20] * 10
    s = build_summary(week, datetime(2026, 11, 2, 9, 0))
    assert set(s) <= {"title", "status", "metrics", "attributes", "messages", "links"}  # 모르는 필드는 400
    assert len(s["title"]) <= 200 and len(s["status"]["label"]) <= 40
    assert len(s["metrics"]) <= 8 and all(0 < len(m["value"]) <= 40 and len(m["label"]) <= 40 for m in s["metrics"])
    assert len(s["attributes"]) <= 12 and all(len(a["name"]) <= 40 and len(a["value"]) <= 200 for a in s["attributes"])





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
