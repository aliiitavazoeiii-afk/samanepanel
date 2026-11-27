"""Django-embedded sister finance views: platform claims, receipts, payments,
bank accounts and unified sale/cost/commission/profit reporting.
"""
import uuid
from .sister_finance_bankless_v1 import receipt_history,record_receipt,cancel_receipt
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
    add_party,add_account,register_movement,cancel_movement,business_sales_report
)

from .sister_outgoings import (EXPENSES,SUPPLIER_SHORTCUTS,record_outgoing,
    cancel_outgoing,outgoing_history,expense_total,unmatched_supplier_total)
from .sister_invoices import settlement as settle_mehr,mehr_open_items,mehr_balance

router=APIRouter()

def nav(active=""):
    tabs=[("finance","مرکز مالی"),("finance/accounts","حساب‌ها"),
          ("invoices/mehr","حساب مه هر"),
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
    if conn.execute("SELECT COUNT(*) FROM sister_purchase_orders").fetchone()[0]:
        body+='<div class="m2-msg">بدهی خرید تأمین‌کنندگان در جمع‌های مالی ثبت‌شده لحاظ می‌شود؛ مانده‌های قدیمی منتقل نشده‌اند و باید تطبیق داده شوند.</div>'
    if conn.execute("SELECT COUNT(*) FROM sister_invoices").fetchone()[0]:
        body+='<div class="m2-msg">سود فاکتورهای ارسال‌شده قالب در فروش کل لحاظ شده است. طلب مشتری و حساب مه هر هم در کارت‌های مالی هستند؛ برای جزئیات، صفحات مربوط را باز کن.</div>'
    body+=nav("finance")
    body+='<p><a class="m2-btn" href="'+ROOT+'/finance/open-invoices">فاکتورهای باز و مانده‌های پرداخت‌نشده</a></p>'
    body+=tiles([("جمع طلب پلتفرم‌ها",info["total_receivable"],"تومان"),
                 ("طلب مشتریان فاکتورها",info["invoice_receivable"],"تومان"),
                 ("بدهی خالص من به مه هر",max(0,info["mehr_payable"]-info["mehr_receivable"]),"تومان · پس از کسر وجوه مشتری"),
                 ("طلب خالص من از مه هر",max(0,info["mehr_receivable"]-info["mehr_payable"]),"تومان · اگر وجوه نزد مهر بیشتر از بدهی باشد"),
                 ("بدهی سایر تأمین‌کنندگان",info["supplier_payable"],"تومان"),
                 ("پیش‌دریافت فاکتورهای ارسال‌نشده",info["customer_advances"],"تومان"),
                 ("جمع موجودی حساب‌های ثبت‌شده",info["cash_balance"],"تومان"),
                 ("فروش ثبت‌شده",sales["gross"],"تومان"),
                 ("کارمزدها",sales["fees"],"تومان"),
                 ("بهای تمام‌شده ثبت‌شده",sales["cogs_known"],"تومان · به‌جز موارد نامشخص"),
                 ("سود پس از هزینه کالا",sales["profit"],"تومان · در صورت تکمیل بها"),
                 ("سود کل قالب‌ها",sales["mold_profit"],"تومان · فروش قالب و فاکتورهای ارسال‌شده"),
                 ("هزینه‌های جاری ثبت‌شده",expense_total(conn),"تومان · پست، اسنپ، بسته‌بندی و سایر هزینه‌ها"),
                 ("سود فروش پس از هزینه‌های جاری",
                  (sales["profit"]-expense_total(conn) if sales["profit"] is not None else None),
                  "تومان · بدون دوباره‌شماری پرداخت خرید کالا")])
    body+='<p class="m2-hint">ریز حساب مهر: بدهی خرید '+fmt(info["mehr_payable"])+' تومان، وجوه مشتری نزد مهر '+fmt(info["mehr_receivable"])+' تومان؛ کارت طلب فقط مازاد خالص را نشان می‌دهد.</p>'
    if sales["unknown_cost_lines"]:
        body+=f'<div class="m2-msg">{sales["unknown_cost_lines"]} ردیف فاقد بهای تمام‌شده است؛ سود کل قطعی نیست.</div>'
    body+='<p class="m2-hint">سود قالب‌ها شامل فاکتورهای ارسال‌شده و فروش‌های کانال قالب است؛ هر فروش باید فقط یک بار در سیستم ثبت شود. پرداخت خرید کالا دوباره هزینه حساب نمی‌شود. هزینه‌های جاری بدون تعیین بانک فقط در دفتر هزینه ثبت می‌شوند و تا زمان انتساب حساب، از مانده بانک کسر نمی‌شوند.</p>'
    body+='<p><a class="m2-btn" href="'+ROOT+'/invoices/mehr">جزئیات حساب مه هر و تهاتر</a></p>'
    body+='<h3 class="m2-bundle-label">طلب هر پلتفرم</h3>'+platform_tiles(conn)
    body+=f'<div class="m2-finance-actions"><a class="m2-btn" href="{ROOT}/finance/accounts">حساب‌ها و طلب‌ها</a>'
    body+=f'<a class="m2-btn" href="{ROOT}/finance/movements?section=receipt">ثبت دریافتی</a>'
    body+=f'<a class="m2-btn" href="{ROOT}/finance/movements?section=payment">ثبت پرداختی</a>'
    body+=f'<a class="m2-btn" href="{ROOT}/finance/sales">گزارش تفصیلی فروش</a>'
    body+='<a class="m2-btn" href="/calculator/">محاسبه‌گر</a></div>'
    body+='<p class="m2-hint">موجودی حساب بانکی بر اساس مانده اولیه و گردش‌های این دفتر محاسبه می‌شود. موجودی یا مطالبات دفتر قدیمی با این مبالغ جمع نشده‌اند.</p>'
    return page_with_style("مرکز مالی",body)


@router.get(ROOT+"/finance/open-invoices")
def open_invoice_balances(conn=Depends(conn_dep)):
    from .sister_invoices import open_customer_invoices,mehr_balance
    from .sister_purchases import suppliers
    from .calendar_jalali import label as jal_label
    rows=open_customer_invoices(conn)
    supplier_rows=[x for x in suppliers(conn) if int(x["due"])>0]
    mehr=mehr_balance(conn)
    unallocated=conn.execute("""SELECT COALESCE(SUM(amount),0),COUNT(*)
        FROM sister_invoice_receipts WHERE destination='mine' AND account_id IS NULL""").fetchone()
    body='<h1>فاکتورهای باز و مانده حساب‌ها</h1>'
    body+='<p class="m2-hint">مانده مشتریان، بدهی تأمین‌کنندگان و دریافت‌های بانک‌نامشخص از یکدیگر جدا هستند. پرداخت‌های فاکتور را دوباره در مالی ثبت نکن.</p>'
    body+=nav("finance")
    body+=tiles([("مانده مشتریان",sum(int(x["gross"])-int(x["paid"]) for x in rows),"تومان · فاکتورهای ارسال‌شده"),
                 ("دریافت ثبت‌شده با بانک نامشخص",int(unallocated[0]),"تومان · "+str(int(unallocated[1]))+" دریافت؛ خارج از مانده بانک"),
                 ("بدهی خالص من به مه هر",max(0,-mehr["net"]),"تومان · پس از کسر وجوه مشتری"),
                 ("طلب خالص من از مه هر",max(0,mehr["net"]),"تومان · در صورت مازاد نزد مهر"),
                 ("بدهی سایر تأمین‌کنندگان",sum(int(x["due"]) for x in supplier_rows),"تومان")])
    body+='<p class="m2-hint">ریز حساب مهر: کل بدهی خرید '+fmt(mehr["debt"])+' تومان؛ وجوه مشتری نزد مهر '+fmt(mehr["credit"])+' تومان. این دو مبلغ برای محاسبه مانده خالص فقط یک‌بار در مقابل هم قرار می‌گیرند.</p>'
    body+='<section class="m2-card"><h3>فاکتورهای باز مشتریان</h3>'
    if rows:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>شماره</th><th>مشتری</th><th>تاریخ</th><th>جمع</th><th>دریافتی</th><th>مانده</th></tr></thead><tbody>'
        for r in rows[:200]:
            body+='<tr><td><a href="'+ROOT+'/invoices/'+str(r["id"])+'">#'+str(r["id"])+'</a></td><td>'+e(r["name"])+'</td><td>'+jal_label(r["invoice_date"])+'</td><td>'+fmt(r["gross"])+'</td><td>'+fmt(r["paid"])+'</td><td>'+fmt(r["gross"]-r["paid"])+'</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">فاکتور ارسال‌شدهٔ تسویه‌نشده‌ای ثبت نشده است.</p>'
    body+='</section>'
    body+='<section class="m2-card"><h3>بدهی باز تأمین‌کنندگان</h3>'
    if supplier_rows:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تأمین‌کننده</th><th>خرید</th><th>پرداخت</th><th>مانده بدهی</th></tr></thead><tbody>'
        for r in supplier_rows:
            body+='<tr><td>'+e(r["name"])+'</td><td>'+fmt(r["purchased"])+'</td><td>'+fmt(r["paid"])+'</td><td>'+fmt(r["due"])+'</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">بدهی ثبت‌شدهٔ بازی برای تأمین‌کنندگان دیگر وجود ندارد.</p>'
    body+='</section>'
    body+='<p class="m2-hint">بدهی مه هر در دفتر جداگانه اوست و جزئیات پرداخت و تهاتر را از <a href="'+ROOT+'/invoices/mehr">حساب مه هر</a> ثبت کن. مانده‌های افتتاحیه قدیمی هنوز تطبیق نهایی نشده‌اند.</p>'
    return page_with_style("فاکتورهای باز",body)

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

def outgoing_payment_page(conn):
    from .calendar_jalali import label as jal_label
    rows=outgoing_history(conn)
    mehr_items=mehr_open_items(conn)
    mehr_open=[r for r in mehr_items if r["remaining"]>0]
    mehr_net=mehr_balance(conn)
    mehr_payments=[dict(r) for r in conn.execute("""SELECT id,occurred_on,debt_delta,notes
        FROM sister_mehr_ledger WHERE kind='paid_to_mehr' ORDER BY id DESC LIMIT 150""")]
    body='<h1>پرداختی‌ها و هزینه‌ها</h1>'
    body+='<p class="m2-hint">این صفحه برای پرداخت به تأمین‌کننده و هزینه‌های جاری مثل پست، اسنپ، کارتن و بسته‌بندی است؛ نه پلتفرم‌های فروش. انتخاب حساب بانکی لازم نیست.</p>'
    body+=nav("finance/movements?section=payment")
    body+='<section class="m2-card m2-finance-section"><h3>ثبت پرداخت جدید</h3>'
    body+='<form method="post" action="'+ROOT+'/finance/outgoings/add" class="m2-fields m2-finance-form">'
    body+='<input type="hidden" name="request_key" value="'+uuid.uuid4().hex+'">'
    body+='<div><label>بابت چه چیزی پرداخت شده؟</label><select name="purpose" id="outgoing-purpose" required>'
    body+='<optgroup label="تأمین‌کننده / خرید"><option value="supplier:mehr">مهر (تسویه بدهی قالب)</option>'
    for code,label in SUPPLIER_SHORTCUTS:
        body+='<option value="supplier:'+e(code)+'">'+e("هولدر (تسویه فاکتورهای مهر)" if code=="holder" else label)+'</option>'
    body+='<option value="supplier:other">تأمین‌کننده دیگر</option></optgroup><optgroup label="هزینه‌های جاری">'
    for code,label in EXPENSES:
        body+='<option value="expense:'+e(code)+'">'+e(label)+'</option>'
    body+='</optgroup></select></div>'
    body+='<div id="outgoing-other-supplier" style="display:none"><label>نام تأمین‌کننده دیگر</label><input name="other_supplier" maxlength="120"></div>'
    body+='<div id="outgoing-mehr-target"><label>بدهی یا فاکتور هولدر برای تسویه</label><select name="mehr_target" id="outgoing-mehr-target-select"><option value="">انتخاب فاکتور یا خرید</option>'
    for item in mehr_open:
        body+='<option value="'+e(item["target"])+'" data-remaining="'+str(item["remaining"])+'">'+e(item["label"])+' · مانده '+fmt(item["remaining"])+' تومان</option>'
    body+='</select><small class="m2-hint">پرداخت به مهر به همین سند متصل می‌شود و مانده آن کاهش می‌یابد.</small></div>'
    body+='<div><label>مبلغ پرداختی (تومان)</label><input name="amount" id="outgoing-amount" type="text" inputmode="numeric" dir="ltr" placeholder="مثلاً 18000000" required autocomplete="off"></div>'
    body+='<div><label>تاریخ پرداخت</label><input name="paid_on" type="date" value="'+today()+'" required></div>'
    body+='<div><label>توضیحات (اختیاری)</label><input name="notes" maxlength="350"></div>'
    body+='<div><button class="m2-btn" type="submit">ثبت پرداخت</button></div></form>'
    body+='<p class="m2-hint">مانده خالص بدهی فعلی به مهر: '+fmt(max(0,-mehr_net["net"]))+' تومان. مبلغ انتخابی نباید از مانده سند یا بدهی خالص بیشتر باشد. وجوهی که مشتری مستقیم به مهر داده قبلاً از مانده فاکتور کسر شده‌اند.</p>'
    body+='<p class="m2-hint">پرداخت مهر در دفتر اختصاصی خودش ثبت می‌شود. پرداخت به سایر تأمین‌کنندگان فقط وقتی خودکار از بدهی کم می‌شود که نام دقیقاً با یک تأمین‌کننده خرید مطابقت داشته باشد و مانده کافی باشد؛ در غیر این صورت به‌عنوان پرداختِ نیازمند تطبیق می‌ماند. از موجودی بانک مبلغی کم نمی‌شود تا حساب واقعی مشخص شود.</p>'
    body+='</section>'
    body+='<section class="m2-card m2-finance-section"><h3>سوابق پرداخت‌های بدون تعیین بانک</h3>'
    if rows:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>بابت</th><th>مبلغ</th><th>وضعیت</th><th>شرح</th><th>عملیات</th></tr></thead><tbody>'
        for r in rows:
            purpose=(dict(EXPENSES).get(r["category"],"هزینه") if r["kind"]=="expense" else "پرداخت به "+r["party_title"])
            status=("ابطال‌شده" if r["cancelled_at"] else
                    ("هزینه ثبت‌شده" if r["kind"]=="expense" else
                     ("کسر از بدهی خرید" if r["linked_supplier_id"] else "پرداخت نیازمند تطبیق خرید")))
            body+='<tr><td>'+jal_label(r["paid_on"])+'</td><td>'+e(purpose)+'</td><td>'+fmt(r["amount_toman"])+'</td><td>'+e(status)+'</td><td>'+e(r["notes"])+'</td><td>'
            if not r["cancelled_at"]:
                body+='<form method="post" action="'+ROOT+'/finance/outgoings/cancel"><input type="hidden" name="outgoing_id" value="'+str(r["id"])+'"><button class="m2-finance-cancel" onclick="return confirm(\'این پرداخت ابطال شود؟\')">ابطال</button></form>'
            else:body+='—'
            body+='</td></tr>'
        body+='</tbody></table></div>'
    else:
        body+='<p class="m2-hint">پرداخت جدیدی در دفتر بدون بانک ثبت نشده است.</p>'
    body+='</section>'
    body+='<section class="m2-card m2-finance-section"><h3>پرداخت‌های ثبت‌شده به مهر</h3>'
    if mehr_payments:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>بابت</th><th>مبلغ</th><th>توضیحات</th></tr></thead><tbody>'
        for r in mehr_payments:
            body+='<tr><td>'+jal_label(r["occurred_on"])+'</td><td>تسویه بدهی مهر</td><td>'+fmt(-r["debt_delta"])+'</td><td>'+e(r["notes"])+'</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">هنوز پرداخت به مهر ثبت نشده است.</p>'
    body+='</section>'
    body+='<p class="m2-hint">سوابق قدیمی پرداخت‌های بانکی حذف نشده‌اند. برای دیدن پرداخت‌های قبل از این تغییر، به <a href="'+ROOT+'/finance/accounts">حساب‌ها</a> مراجعه کن.</p>'
    body+='<script>(function(){var f=document.getElementById("outgoing-purpose"),a=document.getElementById("outgoing-other-supplier"),m=document.getElementById("outgoing-mehr-target"),t=document.getElementById("outgoing-mehr-target-select"),x=document.getElementById("outgoing-amount");if(!f)return;function show(){a.style.display=f.value==="supplier:other"?"":"none";m.style.display=(f.value==="supplier:mehr"||f.value==="supplier:holder")?"":"none";t.required=(f.value==="supplier:mehr"||f.value==="supplier:holder");}f.addEventListener("change",show);show();var form=f.closest("form");form.addEventListener("submit",function(ev){var v=x.value.replace(/[۰-۹]/g,function(n){return String(n.charCodeAt(0)-1776);}).replace(/[٠-٩]/g,function(n){return String(n.charCodeAt(0)-1632);}).replace(/[٬,\\s]/g,"");if(!/^\\d+$/.test(v)||Number(v)<=0){ev.preventDefault();alert("مبلغ پرداختی معتبر نیست.");return;}x.value=v;});})();</script>'
    return page_with_style("پرداختی‌ها",body)

@router.post(ROOT+"/finance/outgoings/add")
def add_outgoing(purpose:str=Form(...),amount:str=Form(...),paid_on:str=Form(...),
                 request_key:str=Form(...),notes:str=Form(""),other_supplier:str=Form(""),
                 mehr_target:str=Form(""),conn=Depends(conn_dep)):
    try:
        if purpose in ("supplier:mehr","supplier:holder"):
            if not mehr_target:
                raise ImportErrorDetail("فاکتور یا خرید هولدر را برای تسویه انتخاب کن.")
            settle_mehr(conn,"paid_to_mehr",amount,paid_on,request_key,notes=notes,target=mehr_target)
        else:
            record_outgoing(conn,purpose,amount,paid_on,request_key,notes,other_supplier)
    except (ImportErrorDetail,ValueError,TypeError) as exc:
        return error_page(exc,"finance/movements?section=payment")
    return RedirectResponse(ROOT+"/finance/movements?section=payment",status_code=303)

@router.post(ROOT+"/finance/outgoings/cancel")
def void_outgoing(outgoing_id:str=Form(...),conn=Depends(conn_dep)):
    try:cancel_outgoing(conn,outgoing_id)
    except (ImportErrorDetail,ValueError,TypeError) as exc:
        return error_page(exc,"finance/movements?section=payment")
    return RedirectResponse(ROOT+"/finance/movements?section=payment",status_code=303)

@router.get(ROOT+"/finance/movements")
def finance_movements(section:str="receipt",conn=Depends(conn_dep)):
    kind=section if section in ("receipt","payment") else "receipt"
    if kind=="payment":
        return outgoing_payment_page(conn)
    people=[p for p in parties(conn) if p["code"] in ("digikala","basalam","site","mold")]
    balances=platform_balances(conn)
    rows=receipt_history(conn)
    body='<h1>دریافتی از پلتفرم‌ها</h1>'
    body+='<p class="m2-hint">برای ثبت دریافتی دیجی‌کالا، باسلام، سایت یا قالب فقط پلتفرم، تاریخ و مبلغ را وارد کن. حساب بانکی لازم نیست.</p>'
    body+=nav("finance/movements?section=receipt")
    body+='<div class="m2-msg">دریافتی فقط مانده طلب پلتفرم را کم می‌کند؛ فروش یا سود تازه نمی‌سازد و چون حساب بانکی مشخص نیست، مانده هیچ حسابی را تغییر نمی‌دهد. دریافت فاکتور مشتری را فقط داخل همان فاکتور ثبت کن.</div>'
    body+=tiles([(x["title"],x["outstanding"],"مانده طلب · تومان")
                  for x in balances.values()])
    body+=f'<section class="m2-card m2-finance-section"><h3>ثبت دریافتی جدید</h3>'
    body+=f'<form method="post" action="{ROOT}/finance/receipts/add" class="m2-fields m2-finance-form">'
    body+=f'<input type="hidden" name="request_key" value="{uuid.uuid4().hex}">'
    body+='<div><label>دریافت از</label><select name="party_id" required>'
    for p in people:
        current=balances[p["code"]]
        body+=f'<option value="{p["id"]}">{e(p["title"])} · طلب {fmt(current["outstanding"])} تومان</option>'
    body+='</select></div>'
    body+=f'<div><label>مبلغ دریافت‌شده (تومان)</label><input type="number" name="amount" min="1" required></div>'
    body+=f'<div><label>تاریخ دریافت</label><input name="paid_on" type="date" value="{today()}" required></div>'
    body+='<div><label>شماره پیگیری (اختیاری)</label><input name="reference" maxlength="100"></div>'
    body+='<div><label>توضیحات (اختیاری)</label><input name="note" maxlength="500"></div>'
    body+='<div><button class="m2-btn" type="submit">ثبت دریافت و کاهش طلب</button></div></form></section>'
    body+='<section class="m2-card m2-finance-section"><h3>دریافتی‌های بدون حساب بانکی</h3>'
    if rows:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>پلتفرم</th><th>مبلغ</th><th>پیگیری / شرح</th><th>وضعیت</th></tr></thead><tbody>'
        for r in rows:
            body+='<tr><td>'+e(r["movement_date"])+'</td><td>'+e(r["party_title"])+'</td>'
            body+='<td>'+fmt(r["amount_toman"])+'</td><td>'+e(r["note"] or r["reference"] or "—")+'</td><td>'
            if r["cancelled_at"]:
                body+='ابطال‌شده'
            else:
                body+=f'<form method="post" action="{ROOT}/finance/receipts/cancel">'
                body+=f'<input type="hidden" name="receipt_id" value="{r["id"]}">'
                body+='<button class="m2-finance-cancel" type="submit" onclick="return confirm(\'این دریافتی ابطال و مبلغ به طلب پلتفرم برگردد؟\')">ابطال دریافتی</button></form>'
            body+='</td></tr>'
        body+='</tbody></table></div>'
    else:
        body+='<p class="m2-hint">هنوز دریافتی بدون تعیین بانک ثبت نشده است.</p>'
    body+='</section>'
    # Old bank-linked receipts remain in the ledger and continue to reduce
    # claims, but no longer force the owner to choose a bank for new receipts.
    old=[m for m in movements(conn,"receipt") if not m["cancelled_at"]]
    if old:
        body+='<section class="m2-card m2-finance-section"><h3>دریافتی‌های قبلی ثبت‌شده با حساب بانکی</h3>'
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>طرف حساب</th><th>مبلغ</th><th>حساب قبلی</th></tr></thead><tbody>'
        for r in old:
            body+='<tr><td>'+e(r["movement_date"])+'</td><td>'+e(r["party_title"])+'</td><td>'+fmt(r["amount_toman"])+'</td><td>'+e(r["account_title"])+'</td></tr>'
        body+='</tbody></table></div></section>'
    return page_with_style("دریافتی‌ها",body)


@router.post(ROOT+"/finance/receipts/add")
def post_bankless_receipt(party_id:str=Form(...),amount:str=Form(...),
                           paid_on:str=Form(...),request_key:str=Form(...),
                           reference:str=Form(""),note:str=Form(""),
                           conn=Depends(conn_dep)):
    try:
        record_receipt(conn,party_id,amount,paid_on,request_key,reference,note)
    except (ImportErrorDetail,ValueError,TypeError) as exc:
        return error_page(exc,"finance/movements?section=receipt")
    return RedirectResponse(ROOT+"/finance/movements?section=receipt",status_code=303)


@router.post(ROOT+"/finance/receipts/cancel")
def post_bankless_receipt_cancel(receipt_id:str=Form(...),conn=Depends(conn_dep)):
    try:
        cancel_receipt(conn,receipt_id)
    except (ImportErrorDetail,ValueError,TypeError) as exc:
        return error_page(exc,"finance/movements?section=receipt")
    return RedirectResponse(ROOT+"/finance/movements?section=receipt",status_code=303)

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
    body+=tiles([("سود کل قالب‌ها",report["mold_profit"],"تومان · جمع فروش قالب و فاکتورها"),
                 ("سفارش ثبت‌شده",report["orders"],"ردیف"),
                 ("تعداد بسته",report["packs"],"بسته"),
                 ("فروش ناخالص",report["gross"],"تومان"),
                 ("هزینه پلتفرم",report["fees"],"تومان"),
                 ("خالص قابل دریافت",report["net"],"تومان"),
                 ("بهای تمام‌شده",report["cogs_known"],"تومان · ثبت‌شده"),
                 ("سود",report["profit"],"تومان · پس از کارمزد و بهای کالا")])
    if report["unknown_cost_lines"]:body+=f'<div class="m2-msg">{report["unknown_cost_lines"]} ردیف فاقد بهای تمام‌شده است؛ سود کل نامشخص است.</div>'
    business_rows=business_sales_report(conn,channel or None,from_date or None,to_date or None)
    body+='<section class="m2-card m2-finance-section"><h3>تفکیک فروش کسب‌وکارها</h3>'
    body+='<p class="m2-hint">فروش هر کسب‌وکار از نوع کالای فروخته‌شده تعیین می‌شود؛ واریزی پلتفرم فروش تازه نیست. کالاهای نامشخص یا ترکیبی حدسی تقسیم نمی‌شوند.</p>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>کسب‌وکار</th><th>تعداد بسته</th><th>تعداد کالا</th><th>فروش</th><th>کارمزد</th><th>بهای کالا</th><th>سود</th></tr></thead><tbody>'
    for x in business_rows:
        body+=f'<tr><th>{e(x["business"])}</th><td>{fmt(x["packs"])}</td><td>{fmt(x["units"])}</td><td>{fmt(x["gross"])}</td><td>{fmt(x["fees"])}</td>'
        body+=f'<td>{fmt(x["cogs_known"]) if not x["unknown_cost_lines"] else "ناقص"}</td><td>{fmt(x["profit"])}</td></tr>'
    if not business_rows:
        body+='<tr><td colspan="7">فروشی در این بازه ثبت نشده است.</td></tr>'
    body+='</tbody></table></div></section>'

    body+='<p class="m2-hint">فاکتورهای ارسال‌شده قالب در جمع فروش و سود لحاظ می‌شوند؛ ریز فاکتور و مشتری فقط در صفحه فاکتورهاست. دریافت مشتری فروش تازه نیست.</p>'
    body+='<section class="m2-card m2-finance-section"><h3>ریز فروش‌ها</h3>'
    if report["lines"]:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>پلتفرم</th><th>محصول</th><th>بسته</th><th>عدد کالا</th><th>فروش</th><th>هزینه پلتفرم</th><th>بهای کالا</th><th>طلب ایجادشده</th><th>سود</th></tr></thead><tbody>'
        for r in report["lines"]:
            if r["kind"]=="invoice":
                continue  # Customer/Mehr detail remains on its own invoice pages.
            body+=f'<tr><th>{e(r["sale_date"])}</th><td>{e(PLATFORMS.get(r["source"],r["source"]))}</td><td>{e(r["title"])}</td>'
            body+=f'<td>{fmt(r["packs"])}</td><td>{fmt(r["units"])}</td><td>{fmt(r["gross"])}</td><td>{fmt(r["fees"])}</td><td>{fmt(r["cogs"])}</td><td>{fmt(r["net"])}</td><td>{fmt(r["profit"])}</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">در این بازه فروشی ثبت نشده است.</p>'
    body+='</section>'
    return page_with_style("گزارش جامع فروش",body)

@router.get(ROOT+"/api/sister-finance.json")
def finance_json(conn=Depends(conn_dep)):
    return JSONResponse(overview(conn))
