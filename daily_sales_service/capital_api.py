"""Sister comprehensive capital: connected goods, accounts, receivables, extras.

Stock is from master SKU counts and dated COGS; marketplace claims are derived
from confirmed sales net of fees and receipts. Never count sale profit again.
Unpriced stock remains explicitly unvalued rather than falsely shown as zero.
"""
from fastapi import APIRouter,Depends,Form
from fastapi.responses import JSONResponse,RedirectResponse

from .app import ROOT,conn_dep,e,fmt
from .effective_costs import capital_snapshot,today
from .platform_catalog import PLATFORMS
from .sister_finance_logic import overview,accounts
from .capital_components import TYPES,components,save_component
from .master_v2_ui import page_with_style

router=APIRouter()

def financial_capital(conn,as_of=None):
    stock=capital_snapshot(conn,as_of)
    finance=overview(conn)
    extras=components(conn)
    cash=int(finance["cash_balance"])
    claim=int(finance["total_receivable"])
    customer_claim=int(finance["invoice_receivable"])
    mehr_claim=int(finance["mehr_net_receivable"])
    business_debt=int(finance["total_liabilities_recorded"])
    equipment=sum(int(extras.get(k) or 0) for k in ("raw_materials","equipment","other_assets"))
    liabilities=int(extras.get("other_liabilities") or 0)
    invoice_pending=bool(conn.execute("SELECT COUNT(*) FROM sister_invoices").fetchone()[0])
    purchases_pending=bool(conn.execute("SELECT COUNT(*) FROM sister_purchase_orders").fetchone()[0])
    inventory=stock["total_value"]
    known_total=(int(stock["known_value"])+cash+claim+customer_claim+mehr_claim
                 +equipment-liabilities-business_debt)
    result={**stock,
            "cash_balance":cash,
            "platform_receivables":finance["platforms"],
            "total_receivable":claim,
            "customer_receivable":customer_claim,
            "mehr_receivable":mehr_claim,
            "mehr_payable":int(finance["mehr_net_payable"]),
            "mehr_gross_purchase_debt":int(finance["mehr_payable"]),
            "mehr_customer_funds_held":int(finance["mehr_receivable"]),
            "supplier_payable":int(finance["supplier_payable"]),
            "customer_advances":int(finance["customer_advances"]),
            "business_liabilities":business_debt,
            "all_recorded_receivables":claim+customer_claim+mehr_claim,
            "manual_balances":extras,
            "raw_materials":extras.get("raw_materials"),
            "equipment":extras.get("equipment"),
            "other_assets":extras.get("other_assets"),
            "liabilities":extras.get("other_liabilities"),
            "known_components_total":known_total,
            "total_capital":known_total if inventory is not None and not invoice_pending and not purchases_pending else None,
            "invoice_accounting_pending":invoice_pending,
            "supplier_purchase_accounting_pending":purchases_pending,
            "sales_profit":finance["sales"]["profit"],
            "sales_gross":finance["sales"]["gross"],
            "sales_fees":finance["sales"]["fees"],
            "sales_cogs_known":finance["sales"]["cogs_known"],
            "mold_sales_profit":finance["sales"]["mold_profit"],
            "mold_sales_gross":finance["sales"]["mold_gross"],
            "unknown_sold_cost_lines":finance["sales"]["unknown_cost_lines"],
            "historical_stock_reconstructed":False}
    return result

@router.get(ROOT+"/api/sister-capital.json")
def capital_data(as_of:str="",conn=Depends(conn_dep)):
    return JSONResponse(financial_capital(conn,as_of or None))

@router.get(ROOT+"/capital-report")
def capital_report(as_of:str="",saved:str="",conn=Depends(conn_dep)):
    try:stat=financial_capital(conn,as_of or None)
    except ValueError as exc:
        return page_with_style("تاریخ نامعتبر",f'<div class="m2-msg">{e(exc)}</div>')
    body='<h1>گزارش جامع سرمایه</h1>'
    body+='<p class="m2-hint">خلاصه دارایی‌های ثبت‌شده، طلب پلتفرم‌ها، مانده حساب‌ها و ارزش کالای آماده. هیچ بدهی تأمین‌کننده‌ای از پنل‌های دیگر وارد نمی‌شود.</p>'
    if stat["supplier_purchase_accounting_pending"]:
        body+='<div class="m2-msg">بدهی خریدهای ثبت‌شده تأمین‌کنندگان در جمع اقلام شناخته‌شده لحاظ می‌شود، اما مانده افتتاحیه و اختلاف بهای ارزش‌گذاری موجودی هنوز تطبیق نشده است؛ سرمایه کل قطعی نیست.</div>'
    if stat["invoice_accounting_pending"]:
        body+='<div class="m2-msg">سود فاکتورهای ارسال‌شده قالب، طلب مشتری و طلب/بدهی ثبت‌شده مه هر در گزارش لحاظ شده‌اند؛ مانده‌های افتتاحیه تاریخی هنوز تطبیق نشده و سرمایه کل قطعی نیست.</div>'
    if saved=="1":body+='<div class="m2-dk-success">مانده دارایی یا بدهی تکمیلی ذخیره شد.</div>'
    if stat["unknown_units"]:
        body+=f'<div class="m2-msg"><strong>ارزش کل موجودی هنوز کامل نیست.</strong> {fmt(stat["unknown_units"])} عدد کالا بهای تمام‌شده ندارد. رقم «جمع اقلام ارزش‌گذاری‌شده» فقط قسمت قابل محاسبه را نشان می‌دهد و سرمایه کل قطعی نیست. <a href="{ROOT}/pricing/cost">تکمیل بهای تمام‌شده</a></div>'
    card_total=stat["total_capital"] if stat["total_capital"] is not None else stat["known_components_total"]
    total_title="سرمایه کل ثبت‌شده" if stat["total_capital"] is not None else "جمع اقلام ارزش‌گذاری‌شده (ناقص)"
    cards=[
      (total_title,card_total,"تومان · دارایی‌ها منهای بدهی‌ها"),
      ("کالای آماده",stat["total_value"] if stat["total_value"] is not None else stat["known_value"],
       "تومان · "+fmt(stat["units"])+" عدد کالا"+(" · ارزش ناقص" if stat["unknown_units"] else "")),
      ("حساب‌ها و صندوق",stat["cash_balance"],"تومان · مانده واقعی حساب‌های ثبت‌شده"),
      ("طلب از پلتفرم‌ها",stat["total_receivable"],"تومان · پس از کارمزد و دریافتی‌ها"),
      ("طلب از مشتریان فاکتورها",stat["customer_receivable"],"تومان · مانده فاکتورهای ارسال‌شده"),
      ("طلب خالص از مه هر",stat["mehr_receivable"],"تومان · فقط مازاد وجوه نزد مهر نسبت به بدهی"),
      ("بدهی خالص به مه هر",stat["mehr_payable"],"تومان · پس از کسر وجوه مشتری"),
      ("بدهی به سایر تأمین‌کنندگان",stat["supplier_payable"],"تومان · خریدهای این پنل"),
      ("پیش‌دریافت مشتریان",stat["customer_advances"],"تومان · فاکتورهای هنوز ارسال‌نشده"),
      ("مواد اولیه",stat["raw_materials"],"تومان · مانده ثبت‌شده مستقل"),
      ("اموال و تجهیزات",stat["equipment"],"تومان · دارایی سرمایه‌ای"),
      ("سایر دارایی‌ها",stat["other_assets"],"تومان · مانده ثبت‌شده"),
      ("بدهی‌ها",stat["liabilities"],"تومان · صرفاً بدهی‌های همین پنل"),
    ]
    body+='<p class="m2-hint">ریز حساب مهر (فقط جهت اطلاع): بدهی خرید ثبت‌شده '+fmt(stat["mehr_gross_purchase_debt"])+' تومان، وجوه مشتری نزد مهر '+fmt(stat["mehr_customer_funds_held"])+' تومان. در جمع سرمایه فقط مانده خالص مهر یک بار حساب می‌شود.</p>'
    body+='<div class="m2-finance-cards">'
    for title,value,subtitle in cards:
        display=fmt(value) if value is not None else "ثبت نشده"
        body+='<div class="m2-card m2-finance-tile"><small>'+e(title)+'</small>'
        body+='<strong class="m2-finance-value">'+display+'</strong>'
        body+='<span class="m2-unit">'+e(subtitle)+'</span></div>'
    body+='</div>'
    body+='<div class="m2-card m2-finance-section"><h3>فروش و سود</h3>'
    body+='<div class="m2-finance-cards" style="margin-bottom:0">'
    for title,key in (("فروش کل ثبت‌شده","sales_gross"),
                      ("هزینه پلتفرم‌ها","sales_fees"),
                      ("سود فروش تحقق‌یافته","sales_profit"),
                      ("سود کل قالب‌ها","mold_sales_profit")):
        value=stat[key]
        body+='<div class="m2-card m2-finance-tile"><small>'+e(title)+'</small>'
        body+='<strong class="m2-finance-value">'+(fmt(value) if value is not None else "نامشخص")+'</strong></div>'
    body+='</div><p class="m2-hint">سود از فروش، پس از هزینه پلتفرم و بهای کالا محاسبه می‌شود و دوباره به ارزش سرمایه اضافه نمی‌شود.</p></div>'
    if stat["unknown_sold_cost_lines"]:
        body+=f'<div class="m2-msg">{fmt(stat["unknown_sold_cost_lines"])} ردیف فروش بهای تمام‌شده ثبت‌شده ندارد؛ سود فروش قطعی نیست. طلب از پلتفرم همچنان از فروش و کارمزد واقعی محاسبه می‌شود.</div>'
    body+='<div class="m2-card m2-finance-section"><h3>طلب پلتفرم‌های فروش</h3>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>پلتفرم</th><th>فروش خالص پس از هزینه</th><th>دریافتی</th><th>طلب مانده</th></tr></thead><tbody>'
    for code,row in stat["platform_receivables"].items():
        body+=(f'<tr><th>{e(PLATFORMS.get(code,row["title"]))}</th><td>{fmt(row["sales_net"])}</td>'
               f'<td>{fmt(row["received"])}</td><td>{fmt(row["outstanding"])}</td></tr>')
    body+='</tbody></table></div></div>'
    active_accounts=accounts(conn)
    body+='<div class="m2-card m2-finance-section"><h3>حساب‌ها و صندوق</h3>'
    if active_accounts:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>حساب</th><th>مانده (تومان)</th></tr></thead><tbody>'
        for bank in active_accounts:
            body+=f'<tr><th>{e(bank["title"])}</th><td>{fmt(bank["balance"])}</td></tr>'
        body+='</tbody></table></div>'
    else:
        body+=f'<p class="m2-hint">هنوز حسابی ثبت نشده است. <a href="{ROOT}/finance/accounts">تعریف حساب و مانده اولیه</a></p>'
    body+='</div>'
    body+='<details class="m2-card m2-finance-section"><summary style="cursor:pointer;font-weight:800">ثبت یا اصلاح مواد اولیه، تجهیزات و سایر دارایی‌ها/بدهی‌ها</summary>'
    body+='<p class="m2-hint">فقط مبالغی را وارد کن که در موجودی کالای آماده، حساب‌های بانکی یا طلب پلتفرم‌ها حساب نشده‌اند. ثبت تکراری، سرمایه را بیش از واقعیت نشان می‌دهد.</p>'
    for key,label in TYPES.items():
        existing=stat["manual_balances"][key]
        body+=f'<form method="post" action="{ROOT}/capital-report/component/save" class="m2-fields" style="margin:12px 0">'
        body+=f'<input type="hidden" name="kind" value="{e(key)}">'
        body+=f'<div><label>{e(label)} (تومان)</label><input type="number" name="amount" min="0" value="{e(existing if existing is not None else "")}" required></div>'
        body+='<div><button class="m2-btn" type="submit">ثبت مبلغ</button></div></form>'
    body+='</details>'
    body+='<details class="m2-card m2-finance-section"><summary style="cursor:pointer">نحوه محاسبه و تاریخ ارزش‌گذاری</summary>'
    body+='<p class="m2-hint">سرمایه = موجودی کالا + حساب‌ها + طلب پلتفرم‌ها + طلب مشتریان + طلب از مه هر + سایر دارایی‌ها − بدهی مه هر − بدهی تأمین‌کنندگان − پیش‌دریافت مشتریان − سایر بدهی‌ها. فروش‌ها به میزان سود سرمایه را افزایش می‌دهند، اما سود جداگانه به دارایی اضافه نمی‌شود.</p>'
    body+=f'<form action="{ROOT}/capital-report" method="get" class="m2-fields"><div><label>تاریخ نرخ بهای تمام‌شده</label><input type="date" name="as_of" value="{e(stat["as_of"])}"></div><div><button class="m2-btn">محاسبه</button></div></form>'
    if stat["as_of"]!=today():
        body+='<p class="m2-msg">تاریخ گذشته فقط نرخ بهای تمام‌شده موجودی فعلی را تغییر می‌دهد؛ گردش موجودی و حساب در آن تاریخ بازسازی نشده است.</p>'
    body+='</details>'
    return page_with_style("گزارش جامع سرمایه",body)

@router.post(ROOT+"/capital-report/component/save")
def save_capital_component(kind:str=Form(...),amount:str=Form(...),conn=Depends(conn_dep)):
    from .app import fail
    from .engine import ImportErrorDetail
    try:save_component(conn,kind,amount)
    except (ValueError,ImportErrorDetail) as exc:return fail(exc)
    return RedirectResponse(ROOT+"/capital-report?saved=1",status_code=303)
