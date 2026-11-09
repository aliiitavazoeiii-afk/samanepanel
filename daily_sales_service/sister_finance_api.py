"""Django-embedded sister finance views: platform claims, receipts, payments,
bank accounts and unified sale/cost/commission/profit reporting.
"""
from urllib.parse import quote
from fastapi import APIRouter,Depends,Form
from fastapi.responses import RedirectResponse,JSONResponse

from .app import ROOT,conn_dep,e,fmt
from .effective_costs import today
from .master_v2_ui import page_with_style
from .platform_catalog import PLATFORMS
from .engine import ImportErrorDetail
from .sister_finance_logic import (
    overview,platform_balances,sales_report,accounts,parties,movements,
    add_party,add_account,register_movement,cancel_movement
)

router=APIRouter()

def nav(active=""):
    tabs=[("finance","مرکز مالی"),("finance/accounts","حساب‌ها"),
          ("finance/movements?section=receipt","دریافتی‌ها"),
          ("finance/movements?section=payment","پرداختی‌ها"),
          ("finance/sales","گزارش فروش")]
    html='<div class="m2-tabs">'
    for route,label in tabs:
        base=route.split("?")[0]
        active_here=active==route or active==base and "?" not in route
        html+=f'<a class="{("current" if active_here else "")}" href="{ROOT}/{route}">{e(label)}</a>'
    return html+'</div>'

def tiles(cards):
    html='<div class="m2-finance-cards">'
    for title,value,foot in cards:
        html+=('<div class="m2-card m2-finance-tile"><small>'+e(title)+'</small>'
               '<strong class="m2-finance-value">'+fmt(value)+'</strong>'
               '<span class="m2-unit">'+e(foot)+'</span></div>')
    return html+'</div>'

def error_page(exc,back="finance/movements"):
    return page_with_style("عملیات ناموفق",
        f'<h1>عملیات انجام نشد</h1><div class="m2-msg">{e(exc)}</div>'
        f'<p><a class="m2-btn" href="{ROOT}/{back}">بازگشت</a></p>')

def platform_tiles(conn):
    balances=platform_balances(conn)
    return tiles([(r["title"],r["outstanding"],"طلب از پلتفرم · تومان")
                 for key,r in balances.items()])

@router.get(ROOT+"/finance")
def finance_home(conn=Depends(conn_dep)):
    info=overview(conn);sales=info["sales"]
    body='<h1>مالی و حسابداری</h1><p class="m2-hint">طلب پلتفرم‌ها از فروش‌های تأییدشده محاسبه می‌شود؛ دریافت‌های ثبت‌شده فقط طلب را تسویه می‌کنند.</p>'
    body+=nav("finance")
    body+=tiles([("جمع طلب پلتفرم‌ها",info["total_receivable"],"تومان"),
                 ("جمع موجودی حساب‌های ثبت‌شده",info["cash_balance"],"تومان"),
                 ("فروش ثبت‌شده",sales["gross"],"تومان"),
                 ("کارمزدها",sales["fees"],"تومان"),
                 ("بهای تمام‌شده ثبت‌شده",sales["cogs_known"],"تومان · به‌جز موارد نامشخص"),
                 ("سود پس از هزینه کالا",sales["profit"],"تومان · در صورت تکمیل بها")])
    if sales["unknown_cost_lines"]:
        body+=f'<div class="m2-msg">{sales["unknown_cost_lines"]} ردیف فاقد بهای تمام‌شده است؛ سود کل قطعی نیست.</div>'
    body+='<h3 class="m2-bundle-label">طلب هر پلتفرم</h3>'+platform_tiles(conn)
    body+=f'<div class="m2-finance-actions"><a class="m2-btn" href="{ROOT}/finance/accounts">حساب‌ها و طلب‌ها</a>'
    body+=f'<a class="m2-btn" href="{ROOT}/finance/movements?section=receipt">ثبت دریافتی</a>'
    body+=f'<a class="m2-btn" href="{ROOT}/finance/movements?section=payment">ثبت پرداختی</a>'
    body+=f'<a class="m2-btn" href="{ROOT}/finance/sales">گزارش تفصیلی فروش</a>'
    body+='<a class="m2-btn" href="/calculator/">محاسبه‌گر</a></div>'
    body+='<p class="m2-hint">موجودی حساب بانکی بر اساس مانده اولیه و گردش‌های این دفتر محاسبه می‌شود. موجودی یا مطالبات دفتر قدیمی با این مبالغ جمع نشده‌اند.</p>'
    return page_with_style("مرکز مالی",body)

@router.get(ROOT+"/finance/accounts")
def finance_accounts(conn=Depends(conn_dep)):
    positions=platform_balances(conn)
    banks=accounts(conn)
    body='<h1>حساب‌ها و مطالبات</h1><p class="m2-hint">مانده طلب = فروش ثبت‌شده منهای کارمزد پلتفرم منهای دریافتی ثبت‌شده.</p>'+nav("finance/accounts")
    body+=platform_tiles(conn)
    body+='<section class="m2-card m2-finance-section"><h3>ریز تسویه هر پلتفرم</h3>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>طرف حساب</th><th>خالص فروش پس از کارمزد</th><th>واریزی‌های ثبت‌شده</th><th>طلب فعلی</th></tr></thead><tbody>'
    for x in positions.values():
        body+=f'<tr><th>{e(x["title"])}</th><td>{fmt(x["sales_net"])}</td><td>{fmt(x["received"])}</td><td>{fmt(x["outstanding"])}</td></tr>'
    body+='</tbody></table></div></section>'
    body+='<section class="m2-card m2-finance-section"><h3>حساب‌های بانکی و صندوق</h3>'
    if banks:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>حساب</th><th>مانده افتتاحیه</th><th>خالص گردش</th><th>مانده فعلی</th></tr></thead><tbody>'
        for x in banks:
            body+=f'<tr><th>{e(x["title"])}</th><td>{fmt(x["opening_toman"])}</td><td>{fmt(x["movement_toman"])}</td><td>{fmt(x["balance"])}</td></tr>'
        body+='</tbody></table></div>'
    else:
        body+='<p class="m2-hint">هنوز حسابی تعریف نشده است. قبل از اولین دریافت یا پرداخت، حساب مقصد یا مبدأ را ایجاد کن.</p>'
    body+=f'<form class="m2-fields m2-finance-form" method="post" action="{ROOT}/finance/accounts/add">'
    body+='<div><label>نام حساب جدید (مثلاً ملت، تجارت، صندوق)</label><input name="title" maxlength="100" required></div>'
    body+='<div><label>مانده ابتدای کار (تومان)</label><input name="opening" type="number" min="0" value="0" required></div>'
    body+='<div><button type="submit" class="m2-btn">ثبت حساب جدید</button></div></form>'
    body+='</section>'
    body+='<p class="m2-hint">بهای کالای فروخته‌شده از سود کم می‌شود، نه از طلب پلتفرم. دریافت وجه هم فروش تازه ایجاد نمی‌کند.</p>'
    return page_with_style("حساب‌ها",body)

@router.post(ROOT+"/finance/accounts/add")
def post_account(title:str=Form(...),opening:str=Form("0"),conn=Depends(conn_dep)):
    try:add_account(conn,title,opening)
    except (ImportErrorDetail,ValueError) as exc:return error_page(exc,"finance/accounts")
    return RedirectResponse(ROOT+"/finance/accounts",status_code=303)

@router.get(ROOT+"/finance/movements")
def finance_movements(section:str="receipt",conn=Depends(conn_dep)):
    kind=section if section in ("receipt","payment") else "receipt"
    banks=[a for a in accounts(conn) if a["active"]]
    people=parties(conn)
    heading="دریافتی‌ها" if kind=="receipt" else "پرداختی‌ها"
    prompt="دریافت از" if kind=="receipt" else "پرداخت به"
    source_label="واریز به حساب" if kind=="receipt" else "پرداخت از حساب"
    body=f'<h1>{heading}</h1><p class="m2-hint">هر انتقال وجه فقط یک بار در دفتر ثبت می‌شود. شماره پیگیری برای جلوگیری از تکرار قابل استفاده است.</p>'
    body+=nav("finance/movements?section="+kind)
    body+=f'<section class="m2-card m2-finance-section"><h3>ثبت {e(heading[:-1])}</h3>'
    if not banks:
        body+=f'<div class="m2-msg">حساب بانکی یا صندوقی تعریف نشده؛ ابتدا از <a href="{ROOT}/finance/accounts">حساب‌ها</a> یک حساب بساز.</div>'
    body+=f'<form method="post" action="{ROOT}/finance/movements/add" class="m2-fields m2-finance-form">'
    body+=f'<input type="hidden" name="kind" value="{kind}">'
    body+=f'<div><label>{prompt}</label><select name="party_id" required>'
    body+=''.join(f'<option value="{p["id"]}">{e(p["title"])}</option>' for p in people)
    body+='</select></div>'
    body+=f'<div><label>{source_label}</label><select name="account_id" required>'
    body+=''.join(f'<option value="{bank["id"]}">{e(bank["title"])} · مانده {fmt(bank["balance"])}</option>' for bank in banks)
    body+='</select></div>'
    body+=f'<div><label>تاریخ</label><input type="date" name="movement_date" value="{today()}" required></div>'
    body+='<div><label>مبلغ (تومان)</label><input type="number" name="amount" min="1" required></div>'
    body+='<div><label>شماره پیگیری بانکی (اختیاری)</label><input name="reference" maxlength="100"></div>'
    body+='<div><label>شرح (اختیاری)</label><input name="note" maxlength="500"></div>'
    body+=f'<div><button type="submit" class="m2-btn"'+(" disabled" if not banks else "")+f'>ثبت {e(heading[:-1])}</button></div></form>'
    body+='</section>'
    body+=f'<section class="m2-card m2-finance-section"><h3>افزودن طرف حساب جدید</h3><p class="m2-hint">دیجی‌کالا، باسلام، سایت، قالب‌ها و اسنپ از قبل در فهرست هستند؛ می‌توانی اشخاص یا تأمین‌کنندگان دیگر را هم ثبت کنی.</p>'
    body+=f'<form method="post" action="{ROOT}/finance/parties/add" class="m2-fields m2-finance-form">'
    body+=f'<input type="hidden" name="return_kind" value="{kind}">'
    body+='<div><label>نام شخص یا طرف حساب</label><input name="title" maxlength="100" required></div>'
    body+='<div><button type="submit" class="m2-btn">ثبت طرف حساب</button></div></form></section>'
    rows=movements(conn,kind)
    body+='<section class="m2-card m2-finance-section"><h3>سوابق '+heading+'</h3>'
    if rows:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>از / به</th><th>حساب</th><th>مبلغ</th><th>شرح / پیگیری</th><th>وضعیت</th></tr></thead><tbody>'
        for r in rows:
            body+=f'<tr><th>{e(r["movement_date"])}</th><td>{e(r["party_title"])}</td><td>{e(r["account_title"])}</td>'
            body+=f'<td>{fmt(r["amount_toman"])}</td><td>{e(r["note"] or r["reference"] or "—")}</td><td>'
            if r["cancelled_at"]:
                body+='ابطال‌شده'
            else:
                body+=(f'<form method="post" action="{ROOT}/finance/movements/cancel">'
                       f'<input type="hidden" name="movement_id" value="{r["id"]}">'
                       f'<input type="hidden" name="return_kind" value="{kind}">'
                       '<button class="m2-finance-cancel" type="submit" onclick="return confirm(\'آیا از ابطال این گردش مالی مطمئن هستید؟\')">ابطال</button></form>')
            body+='</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">هنوز گردش مالی در این بخش ثبت نشده است.</p>'
    body+='</section>'
    return page_with_style(heading,body)

@router.post(ROOT+"/finance/parties/add")
def post_party(title:str=Form(...),return_kind:str=Form("receipt"),conn=Depends(conn_dep)):
    try:add_party(conn,title)
    except (ImportErrorDetail,ValueError) as exc:return error_page(exc,"finance/movements")
    kind=return_kind if return_kind in ("receipt","payment") else "receipt"
    return RedirectResponse(ROOT+"/finance/movements?section="+kind,status_code=303)

@router.post(ROOT+"/finance/movements/add")
def post_movement(kind:str=Form(...),party_id:str=Form(...),account_id:str=Form(...),
                  amount:str=Form(...),movement_date:str=Form(...),
                  reference:str=Form(""),note:str=Form(""),conn=Depends(conn_dep)):
    try:register_movement(conn,kind,party_id,account_id,amount,movement_date,reference,note)
    except (ImportErrorDetail,ValueError) as exc:return error_page(exc,"finance/movements")
    return RedirectResponse(ROOT+"/finance/movements?section="+quote(kind),status_code=303)

@router.post(ROOT+"/finance/movements/cancel")
def post_cancel(movement_id:str=Form(...),return_kind:str=Form("receipt"),conn=Depends(conn_dep)):
    try:cancel_movement(conn,movement_id)
    except (ImportErrorDetail,ValueError) as exc:return error_page(exc,"finance/movements")
    kind=return_kind if return_kind in ("receipt","payment") else "receipt"
    return RedirectResponse(ROOT+"/finance/movements?section="+kind,status_code=303)

@router.get(ROOT+"/finance/sales")
def all_sales(channel:str="",from_date:str="",to_date:str="",conn=Depends(conn_dep)):
    if channel not in PLATFORMS:channel=""
    try:report=sales_report(conn,channel or None,from_date or None,to_date or None)
    except (ImportErrorDetail,ValueError) as exc:return error_page(exc,"finance/sales")
    body='<h1>گزارش جامع فروش</h1><p class="m2-hint">آمار واقعی فروش ثبت‌شده در تمام پلتفرم‌ها؛ بهای تمام‌شده و کارمزدها جدا محاسبه شده‌اند.</p>'
    body+=nav("finance/sales")
    body+=f'<section class="m2-filters"><form action="{ROOT}/finance/sales" method="get">'
    body+='<div><label>پلتفرم</label><select name="channel"><option value="">همه پلتفرم‌ها</option>'
    body+=''.join(f'<option value="{c}"'+(" selected" if channel==c else "")+f'>{e(t)}</option>' for c,t in PLATFORMS.items())+'</select></div>'
    body+=f'<div><label>از تاریخ</label><input type="date" name="from_date" value="{e(from_date)}"></div>'
    body+=f'<div><label>تا تاریخ</label><input type="date" name="to_date" value="{e(to_date)}"></div>'
    body+='<div><button class="m2-btn" type="submit">نمایش گزارش</button></div></form></section>'
    body+=tiles([("سفارش ثبت‌شده",report["orders"],"ردیف"),
                 ("تعداد بسته",report["packs"],"بسته"),
                 ("فروش ناخالص",report["gross"],"تومان"),
                 ("هزینه پلتفرم",report["fees"],"تومان"),
                 ("خالص قابل دریافت",report["net"],"تومان"),
                 ("بهای تمام‌شده",report["cogs_known"],"تومان · ثبت‌شده"),
                 ("سود",report["profit"],"تومان · پس از کارمزد و بهای کالا")])
    if report["unknown_cost_lines"]:body+=f'<div class="m2-msg">{report["unknown_cost_lines"]} ردیف فاقد بهای تمام‌شده است؛ سود کل نامشخص است.</div>'
    body+='<section class="m2-card m2-finance-section"><h3>ریز فروش‌ها</h3>'
    if report["lines"]:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>پلتفرم</th><th>محصول</th><th>بسته</th><th>عدد کالا</th><th>فروش</th><th>هزینه پلتفرم</th><th>بهای کالا</th><th>طلب ایجادشده</th><th>سود</th></tr></thead><tbody>'
        for r in report["lines"]:
            body+=f'<tr><th>{e(r["sale_date"])}</th><td>{e(PLATFORMS.get(r["source"],r["source"]))}</td><td>{e(r["title"])}</td>'
            body+=f'<td>{fmt(r["packs"])}</td><td>{fmt(r["units"])}</td><td>{fmt(r["gross"])}</td><td>{fmt(r["fees"])}</td><td>{fmt(r["cogs"])}</td><td>{fmt(r["net"])}</td><td>{fmt(r["profit"])}</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">در این بازه فروشی ثبت نشده است.</p>'
    body+='</section>'
    return page_with_style("گزارش جامع فروش",body)

@router.get(ROOT+"/api/sister-finance.json")
def finance_json(conn=Depends(conn_dep)):
    return JSONResponse(overview(conn))
