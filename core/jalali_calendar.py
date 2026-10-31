from datetime import date

import holidays
import jdatetime

PERSIAN_WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
PERSIAN_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def _holiday_calendar(first_g, next_g):
    years = list(range(first_g.year, next_g.year + 1))
    try:
        return holidays.country_holidays("IR", years=years, language="fa")
    except Exception:
        return {}


def jalali_month_data(jy, jm):
    jy = int(jy)
    jm = int(jm)
    if not 1 <= jm <= 12:
        raise ValueError("ماه شمسی نامعتبر است.")

    first_j = jdatetime.date(jy, jm, 1)
    first_g = first_j.togregorian()
    next_j = jdatetime.date(jy + 1, 1, 1) if jm == 12 else jdatetime.date(jy, jm + 1, 1)
    next_g = next_j.togregorian()
    days_count = (next_g - first_g).days
    leading = (first_g.weekday() + 2) % 7
    ir_holidays = _holiday_calendar(first_g, next_g)

    cells = [None] * leading
    for day_num in range(1, days_count + 1):
        g = jdatetime.date(jy, jm, day_num).togregorian()
        official_name = str(ir_holidays.get(g, "") or "")
        is_friday = g.weekday() == 4
        holiday_name = official_name or ("جمعه" if is_friday else "")
        cells.append({
            "day": day_num,
            "value": f"{jy:04d}/{jm:02d}/{day_num:02d}",
            "is_today": g == date.today(),
            "is_friday": is_friday,
            "is_holiday": bool(is_friday or official_name),
            "holiday_name": holiday_name,
        })
    while len(cells) % 7:
        cells.append(None)

    if jm == 1:
        prev_y, prev_m = jy - 1, 12
    else:
        prev_y, prev_m = jy, jm - 1
    if jm == 12:
        next_y, next_m = jy + 1, 1
    else:
        next_y, next_m = jy, jm + 1

    return {
        "jy": jy,
        "jm": jm,
        "month_name": PERSIAN_MONTHS[jm - 1],
        "weekdays": PERSIAN_WEEKDAYS,
        "weeks": [cells[i:i + 7] for i in range(0, len(cells), 7)],
        "prev_y": prev_y,
        "prev_m": prev_m,
        "next_y": next_y,
        "next_m": next_m,
        "first_g": first_g,
        "next_g": next_g,
    }
