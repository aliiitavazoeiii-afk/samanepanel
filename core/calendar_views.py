from datetime import date

import jdatetime
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .dateutils import normalize_digits
from .jalali_calendar import jalali_month_data


@login_required
def jalali_picker(request):
    today_j = jdatetime.date.fromgregorian(date=date.today())
    jy, jm = today_j.year, today_j.month

    value = normalize_digits(request.GET.get("value", "")).replace("-", "/").replace(".", "/")
    parts = [p for p in value.split("/") if p]
    if len(parts) >= 2:
        try:
            jy, jm = int(parts[0]), int(parts[1])
        except ValueError:
            pass

    try:
        if request.GET.get("jy"):
            jy = int(request.GET.get("jy"))
        if request.GET.get("jm"):
            jm = int(request.GET.get("jm"))
    except (TypeError, ValueError):
        jy, jm = today_j.year, today_j.month

    data = jalali_month_data(jy, jm)
    data.pop("first_g", None)
    data.pop("next_g", None)
    return JsonResponse(data, json_dumps_params={"ensure_ascii": False})
