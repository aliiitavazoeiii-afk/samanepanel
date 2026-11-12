"""Sister-only comprehensive capital: physical stock + earned receivables + cash.

Recording a sale withdraws stock at COGS and creates an asset (platform net
receivable). Their net asset change equals recognized sale profit; do NOT add
profit again to total capital. Receipt moves a receivable into a cash account
with zero effect on total capital. No legacy Darma/Dia balances are imported.
"""
from fastapi import APIRouter,Depends
from fastapi.responses import JSONResponse
from .app import ROOT,conn_dep,e,fmt
from .effective_costs import capital_snapshot,today
from .platform_catalog import PLATFORMS
from .sister_finance_logic import overview
from .master_v2_ui import page_with_style

router=APIRouter()

def financial_capital(conn,as_of=None):
    stock=capital_snapshot(conn,as_of)
    finance=overview(conn)
    inventory=stock["total_value"]
    cash=finance["cash_balance"]
    outstanding=finance["total_receivable"]
    result={**stock,
            "cash_balance":cash,
            "platform_receivables":finance["platforms"],
            "total_receivable":outstanding,
            "total_capital":(inventory+cash+outstanding) if inventory is not None else None,
            "sales_profit":finance["sales"]["profit"],
            "sales_gross":finance["sales"]["gross"],
            "sales_fees":finance["sales"]["fees"],
            "sales_cogs_known":finance["sales"]["cogs_known"],
            "unknown_sold_cost_lines":finance["sales"]["unknown_cost_lines"],
            "historical_stock_reconstructed":False}
    return result

@router.get(ROOT+"/api/sister-capital.json")
def capital_data(as_of:str="",conn=Depends(conn_dep)):
    return JSONResponse(financial_capital(conn,as_of or None))

@router.get(ROOT+"/capital-report")
def capital_report(as_of:str="",conn=Depends(conn_dep)):
    try:stat=financial_capital(conn,as_of or None)
    except ValueError as exc:
        return page_with_style("تاریخ نامعتبر",f'<div class="m2-msg">{e(exc)}</div>')
    current=today()
    body='<h1>گزارش جامع سرمایه · پنل مستقل</h1>'
    body+='<p class="m2-hint">جمع واقعی دارایی‌های این پنل از ارزش موجودی فیزیکی، طلب خالص پلتفرم‌ها و مانده حساب‌های ثبت‌شده ساخته می‌شود.</p>'
    body+=f'<div class="m2-filters"><form action="{ROOT}/capital-report" method="get"><div><label>تاریخ نرخ بهای تمام‌شده</label><input type="date" name="as_of" value="{e(stat["as_of"])}"></div><div><button class="m2-btn" type="submit">محاسبه</button></div></form></div>'
    cards=[
      ("جمع سرمایه اصلی",stat["total_capital"],"تومان · بدون دوباره‌شماری سود"),
      ("ارزش موجودی انبارها",stat["total_value"],"تومان · خانه و خورشید"),
      ("طلب از پلتفرم‌ها",stat["total_receivable"],"تومان · پس از کارمزد و دریافتی"),
      ("مانده حساب‌ها و صندوق",stat["cash_balance"],"تومان · مانده افتتاحیه و گردش"),
      ("سود فروش تحقق‌یافته",stat["sales_profit"],"تومان · سهم سود در سرمایه، نه دارایی مجزا"),
      ("فروش کل ثبت‌شده",stat["sales_gross"],"تومان · همه پلتفرم‌ها"),
    ]
    body+='<div class="m2-finance-cards">'
    for title,value,subtitle in cards:
        body+='<div class="m2-card m2-finance-tile"><small>'+e(title)+'</small>'
        body+='<strong class="m2-finance-value">'+(fmt(value) if value is not None else "نامشخص")+'</strong>'
        body+='<span class="m2-unit">'+e(subtitle)+'</span></div>'
    body+='</div>'
    body+='<div class="m2-card m2-finance-section"><h3>فرمول محاسبه سرمایه</h3>'
    body+='<p class="m2-hint">سرمایه = موجودی کالا به قیمت تمام‌شده + طلب تسویه‌نشده از پلتفرم‌ها + مانده حساب‌های بانکی/صندوق.</p>'
    body+='<p class="m2-hint">هنگام فروش، بهای کالا از موجودی کم می‌شود و مبلغ قابل‌دریافت بعد از کارمزد به طلب افزوده می‌شود؛ تفاوت این دو همان سود فروش است. دریافت پول صرفاً طلب را به مانده بانک منتقل می‌کند؛ سرمایه دوباره زیاد نمی‌شود.</p></div>'
    if stat["unknown_units"]:
        body+=f'<div class="m2-msg">برای {fmt(stat["unknown_units"])} عدد موجودی نرخ تمام‌شده مشخص نیست؛ جمع نهایی سرمایه تا تکمیل نرخ‌ها نامشخص است. ارزش شناخته‌شده موجودی: {fmt(stat["known_value"])} تومان.</div>'
    if stat["unknown_sold_cost_lines"]:
        body+=f'<div class="m2-msg">{fmt(stat["unknown_sold_cost_lines"])} ردیف فروش بهای تمام‌شده ندارد؛ محاسبه سود کل قطعی نیست. مبلغ طلب این ردیف‌ها همچنان درست و مستقل از هزینه کالا است.</div>'
    if stat["as_of"]!=current:
        body+='<div class="m2-msg">تاریخ گذشته فقط برای انتخاب نرخ بهای تمام‌شده موجودی فعلی است. این صفحه گردش تاریخی موجودی و حساب‌های بانکی در آن تاریخ را بازسازی نمی‌کند.</div>'
    body+='<div class="m2-section"><h3>موجودی به تفکیک کالا</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>دسته کالا</th><th>تعداد موجودی فیزیکی</th><th>ارزش شناخته‌شده</th><th>کالای فاقد نرخ</th></tr></thead><tbody>'
    for cat,row in stat["categories"].items():
        body+=f'<tr><th>{e(cat)}</th><td>{fmt(row["quantity"])}</td><td>{fmt(row["known_value"])}</td><td>{fmt(row["missing_cost_units"])}</td></tr>'
    body+='</tbody></table></div></div>'
    body+='<div class="m2-section"><h3>طلب هر پلتفرم</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>پلتفرم</th><th>فروش پس از کارمزد</th><th>دریافت‌ها</th><th>طلب</th></tr></thead><tbody>'
    for code,row in stat["platform_receivables"].items():
        body+=f'<tr><th>{e(PLATFORMS.get(code,row["title"]))}</th><td>{fmt(row["sales_net"])}</td><td>{fmt(row["received"])}</td><td>{fmt(row["outstanding"])}</td></tr>'
    body+='</tbody></table></div></div>'
    body+=f'<p><a href="{ROOT}/finance/accounts">حساب‌ها و طلب‌ها</a> · <a href="{ROOT}/finance/movements?section=receipt">ثبت دریافتی</a> · <a href="{ROOT}/">فروش روزانه دیجی‌کالا</a> · <a href="{ROOT}/master/stock">موجودی کالا</a></p>'
    return page_with_style("گزارش جامع سرمایه",body)
