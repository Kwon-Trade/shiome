"""月次/日次のループに使う共通ユーティリティ。"""
from __future__ import annotations

import datetime as dt


def month_range(start: dt.date, end: dt.date):
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)


def day_range(start: dt.date, end: dt.date):
    cur = start
    one_day = dt.timedelta(days=1)
    while cur <= end:
        yield cur
        cur += one_day
