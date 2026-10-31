"""Standalone sister-business comprehensive inventory capital and channel sales.

Not mixed into original Darma/Dia financial capital calculations.
"""
from fastapi import APIRouter,Depends
from fastapi.responses import JSONResponse
from .app import ROOT,conn_dep,e,fmt
from .effective_costs import capital_snapshot,today,valid_date
from .platform_catalog import sale_summary,PLATFORMS
from .master_v2_ui import page_with_style

router=APIRouter()

@router.get(ROOT+"/api/sister-capital.json")
def capital_data(as_of:str="",conn=Depends(conn_dep)):
    data=capital_snapshot(conn,as_of or None)
    data["platform_sales"]=sale_summary(conn)
    data["historical_stock_reconstructed"]=False
    return JSONResponse(data)

@router.get(ROOT+"/capital-report")
def capital_report(as_of:str="",conn=Depends(conn_dep)):
    try:
        snapshot=capital_snapshot(conn,as_of or None)
    except ValueError as exc:
        return page_with_style("تاریخ نامعتبر",f'<div class="m2-msg">{e(exc)}</div>')
    sales=sale_summary(conn)
    current=today()
    body='<h1>گزارش جامع سرمایه · پنل خواهر</h1><p class="m2-hint">این گزارش مستقل از سرمایه پنل اصلی است. موجودی فعلی خانه و خورشید با بهای تمام‌شده مؤثر در تاریخ انتخاب‌شده ارزش‌گذاری می‌شود.</p>'
    body+=f'<div class="m2-filters"><form action="{ROOT}/capital-report" method="get"><div><label>تاریخ محاسبه بهای تمام‌شده</label><input type="date" name="as_of" value="{e(snapshot["as_of"])}"></div><div><button type="submit">محاسبه سرمایه</button></div></form></div>'
    body+=f'<div class="m2-cards"><div class="m2-card"><h3>ارزش موجودی خانه و خورشید</h3><strong style="font-size:25px">{fmt(snapshot["total_value"]) if snapshot["total_value"] is not None else "نامشخص"} تومان</strong></div>'
    body+=f'<div class="m2-card"><h3>تعداد کل موجودی</h3><strong style="font-size:25px">{fmt(snapshot["units"])} عدد</strong></div>'
    body+=f'<div class="m2-card"><h3>موجودی فاقد بهای تمام‌شده</h3><strong style="font-size:25px">{fmt(snapshot["unknown_units"])} عدد</strong></div></div>'
    body+='<div class="m2-section"><h3>ارزش سرمایه به تفکیک دسته کالا</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>دسته کالا</th><th>موجودی فیزیکی</th><th>ارزش شناخته‌شده (تومان)</th><th>فاقد نرخ</th></tr></thead><tbody>'
    for cat,row in snapshot["categories"].items():
        body+=f'<tr><th>{e(cat)}</th><td>{fmt(row["quantity"])}</td><td>{fmt(row["known_value"]) if not row["missing_cost_units"] else "نامشخص"}</td><td>{fmt(row["missing_cost_units"])}</td></tr>'
    body+='</tbody></table></div></div>'
    if snapshot["as_of"]!=current:
        body+='<div class="m2-msg">تاریخ انتخابی فقط نرخ تمام‌شده را تغییر می‌دهد؛ تعداد موجودی، موجودی فعلی است و مانده انبار در روزهای گذشته بازسازی نشده است. این عدد گزارش تاریخی قطعی سرمایه نیست.</div>'
    body+='<div class="m2-section"><h3>فروش روزانه پلتفرم‌ها · تا امروز</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>پلتفرم</th><th>سفارش</th><th>تعداد کالای فیزیکی</th><th>فروش ناخالص (تومان)</th><th>وضعیت سود</th></tr></thead><tbody>'
    for key in ("basalam","site","mold"):
        row=sales.get(key,{})
        body+=f'<tr><th>{e(PLATFORMS[key])}</th><td>{fmt(row.get("orders",0))}</td><td>{fmt(row.get("units",0))}</td><td>{fmt(row.get("gross",0))}</td><td>کارمزد تعریف نشده، سود قطعی نامشخص</td></tr>'
    body+='</tbody></table></div></div>'
    body+=f'<p><a href="{ROOT}/pricing/cost">تنظیم بهای تمام‌شده با تاریخ اجرا</a> · <a href="{ROOT}/platforms">پلتفرم‌ها</a> · <a href="{ROOT}/master/stock">موجودی کالا</a></p>'
    return page_with_style("گزارش جامع سرمایه",body)
