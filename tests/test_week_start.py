from datetime import date

from pandomeal import Post


def week_start(title: str, posted: date) -> date:
    return Post("1", title, posted).week_start


def test_same_year():
    assert week_start("주간식단표(11.  2. ~ 11.  8.)", date(2026, 10, 29)) == date(2026, 11, 2)


def test_posted_in_december_for_january():
    assert week_start("주간식단표(1. 4. ~ 1. 10.)", date(2026, 12, 30)) == date(2027, 1, 4)


def test_posted_in_january_for_december():
    assert week_start("주간식단표(12. 28. ~ 1. 3.)", date(2027, 1, 2)) == date(2026, 12, 28)
