from datetime import date, datetime

import jdatetime

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_digits(value):
    return str(value or "").translate(_DIGITS).strip()


def parse_jalali_date(value):
    raw = normalize_digits(value).replace("-", "/").replace(".", "/")
    parts = [p for p in raw.split("/") if p != ""]
    if len(parts) != 3:
        raise ValueError("تاریخ باید به شکل ۱۴۰۵/۰۵/۳۱ وارد شود.")
    try:
        year, month, day = map(int, parts)
        return jdatetime.date(year, month, day).togregorian()
    except (TypeError, ValueError, OverflowError):
        raise ValueError("تاریخ شمسی معتبر نیست.")


def format_jalali(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        return ""
    jd = jdatetime.date.fromgregorian(date=value)
    return f"{jd.year:04d}/{jd.month:02d}/{jd.day:02d}"
