"""Read-only unified sister sales calendar, reports and dashboard data.

The sister-sales SQLite ledger is the sole source for these screens.
Legacy Darma sales are kept out of the aggregates to avoid double-counting.
"""
import json
from datetime import date, timedelta
import jdatetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from .dateutils import format_jalali
from .jalali_calendar import jalali_month_data, PERSIAN_MONTHS

CHANNELS = (
    ("digikala", "دیجی‌کالا", "/sales/digikala/?sale_date="),
    ("site", "سایت", "/sales/site/?day="),
    ("basalam", "باسلام", "/sales/basalam/?day="),
    ("mold", "قالب", "/sales/ghaleb/?day="),
)
CHANNEL_LABELS = dict((k, label) for k,label,_ in CHANNELS)


def sister_summary(request, start, end, channel=""):
    """Use the existing authenticated Django->private FastAPI bridge."""
    from .sister_sales import digikala_proxy
    from urllib.parse import urlencode
    tail = "api/sales-overview.json"
    # Do not mutate request.GET or lose Django session authentication.
    params = urlencode({"start": start, "end": end, "channel": channel})
    previous = request.META.get("QUERY_STRING", "")
    try:
        request.META["QUERY_STRING"] = params
        response = digikala_proxy(request, tail)
    finally:
        request.META["QUERY_STRING"] = previous
    if response.status_code != 200:
        raise RuntimeError("دریافت گزارش فروش از سرویس اصلی ممکن نشد.")
    try:
        data = json.loads(response.content)
    except (ValueError,UnicodeDecodeError):
        raise RuntimeError("پاسخ سرویس فروش معتبر نیست.")
    if not isinstance(data,dict) or "total" not in data:
        raise RuntimeError("ساختار گزارش فروش معتبر نیست.")
    for key in ("days", "day_channels"):
        for row in data.get(key, []):
            day = date.fromisoformat(row["date"])
            row["jalali"] = format_jalali(day)
    return data


def _month_from_query(request):
    today = timezone.localdate()
    jd = jdatetime.date.fromgregorian(date=today)
    try:
        jy = int(request.GET.get("jy", jd.year))
        jm = int(request.GET.get("jm", jd.month))
        if not (1300 <= jy <= 1500 and 1 <= jm <= 12):
            raise ValueError
    except (TypeError,ValueError):
        jy,jm = jd.year,jd.month
    return jy,jm


@login_required
def sales_calendar(request):
    jy,jm = _month_from_query(request)
    cal = jalali_month_data(jy,jm)
    start=cal["first_g"].isoformat()
    end=(cal["next_g"]-timedelta(days=1)).isoformat()
    data=None; error=""
    try:
        data=sister_summary(request,start,end)
    except RuntimeError as exc:
        error=str(exc)
    day_map = {d["date"]: d for d in data["days"]} if data else {}
    source_map={}
    if data:
        for x in data["day_channels"]:
            source_map.setdefault(x["date"],[]).append(x["label"])
    selected=request.GET.get("jd","")
    selected_date=None
    try:
        d=int(selected)
        if not 1<=d<=31:raise ValueError
        selected_date=jdatetime.date(jy,jm,d).togregorian()
    except (ValueError,TypeError):
        pass
    for week in cal["weeks"]:
        for cell in week:
            if cell is None:continue
            g=jdatetime.date(jy,jm,cell["day"]).togregorian()
            info=day_map.get(g.isoformat())
            cell["has_sales"]=bool(info and info["orders"])
            cell["gross"]=info["gross"] if info else 0
            cell["sources"]=source_map.get(g.isoformat(),[])
            cell["selected"]=selected_date==g
            cell["url"]=f"/sales/?jy={jy}&jm={jm}&jd={cell['day']}"
    links=[]
    if selected_date:
        iso=selected_date.isoformat()
        links=[{"key":key,"name":label,"url":base+iso} for key,label,base in CHANNELS]
    return render(request,"core/sister_sales_calendar_v1.html",{
        "jy":jy,"jm":jm,"calendar":cal,"selected_date":selected_date,
        "selected_jalali":format_jalali(selected_date) if selected_date else "",
        "selected_stats":day_map.get(selected_date.isoformat()) if selected_date else None,
        "links":links,"error":error,"summary":data["total"] if data else None,
    })


@login_required
def sales_report(request):
    jy,jm=_month_from_query(request)
    cal=jalali_month_data(jy,jm)
    start=cal["first_g"].isoformat()
    end=(cal["next_g"]-timedelta(days=1)).isoformat()
    channel=request.GET.get("channel","")
    if channel not in ("","digikala","site","basalam","mold"):
        channel=""
    try:
        data=sister_summary(request,start,end,channel)
        error=""
    except RuntimeError as exc:
        data=None;error=str(exc)
    return render(request,"core/sister_sales_report_v1.html",{
        "jy":jy,"jm":jm,"month_name":cal["month_name"],
        "channels":CHANNELS,"selected_channel":channel,
        "months": [(index, name) for index,name in enumerate(PERSIAN_MONTHS,1)],
        "data":data,"error":error
    })


def dashboard_periods(request):
    """Two date ranges, with the same accounting logic as the calendar/report."""
    today=timezone.localdate()
    j=jdatetime.date.fromgregorian(date=today)
    start=jdatetime.date(j.year,j.month,1).togregorian()
    today_data=sister_summary(request,today.isoformat(),today.isoformat())
    month_data=sister_summary(request,start.isoformat(),today.isoformat())
    return today_data, month_data
