"""Simple customer invoices and Mehr account screens."""
import uuid
from urllib.parse import quote
from fastapi import APIRouter,Depends,Form,Request
from fastapi.responses import RedirectResponse
from .app import ROOT,conn_dep,e,fmt
from .effective_costs import today
from .engine import ImportErrorDetail
from .master_v2_ui import page_with_style
from .calendar_jalali import label as jal_label
from .sister_invoices import (SIZES,create_invoice,dispatch_invoice,record_receipt,
    receive_purchase,settlement,mehr_balance,invoices,invoice_detail)
from .sister_finance_logic import accounts

router=APIRouter()

def form_error(exc,back="invoices"):
    return page_with_style("خطای ثبت",'<h2>عملیات انجام نشد</h2><div class="m2-msg">'+e(exc)+'</div>'+
      '<p><a class="m2-btn" href="'+ROOT+'/'+back+'">بازگشت</a></p>')

def token():
    return uuid.uuid4().hex

def receipt_bank_options(conn):
    return ''.join('<option value="'+str(a["id"])+'">'+e(a["title"])+'</option>' for a in accounts(conn) if a["active"])

def sku_options(conn,size):
    rows=conn.execute("""SELECT id,title,color,seller_stock FROM master_products
     WHERE category='قالب' AND size=? AND active=1 ORDER BY title,color,id""",(size,))
    return '<option value="">انتخاب قالب واقعی</option>'+''.join(
      '<option value="'+str(r["id"])+'">'+e(r["title"])+' / '+e(r["color"])+' — خانه: '+fmt(r["seller_stock"])+'</option>'
      for r in rows)

def page_invoices(conn,query=""):
    rows=invoices(conn,query)
    body='<h1>فاکتور مشتریان</h1><p class="m2-hint">فاکتور ابتدا پیش‌نویس است؛ فقط هنگام تأیید ارسال، موجودی و حساب مه هر تغییر می‌کند.</p>'
    body+='<div class="m2-tabs"><a href="'+ROOT+'/invoices/new">+ فاکتور جدید</a><a href="'+ROOT+'/invoices/mehr">حساب مه هر</a><a href="'+ROOT+'/invoices/purchases">خرید از مه هر</a></div>'
    body+='<form method="get" action="'+ROOT+'/invoices" class="m2-filters"><label>جست‌وجوی مشتری با نام</label><input name="q" value="'+e(query)+'" placeholder="نام مشتری"><button class="m2-btn">جست‌وجو</button></form>'
    body+='<section class="m2-card"><h3>فاکتورهای ثبت‌شده</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>شماره</th><th>مشتری</th><th>تاریخ</th><th>مبدأ</th><th>وضعیت</th><th>فروش</th><th>مانده مشتری</th></tr></thead><tbody>'
    for r in rows:
        body+='<tr><td><a href="'+ROOT+'/invoices/'+str(r["id"])+'">#'+str(r["id"])+'</a></td><td>'+e(r["name"])+'</td><td>'+jal_label(r["invoice_date"])+'</td><td>'+("خانه" if r["origin"]=="home" else "کارخانه")+'</td><td>'+("ارسال‌شده" if r["status"]=="dispatched" else "پیش‌نویس")+'</td><td>'+fmt(r["gross"])+'</td><td>'+fmt(r["gross"]-r["paid"])+'</td></tr>'
    body+='</tbody></table></div></section>'
    return page_with_style("فاکتور مشتریان",body)

@router.get(ROOT+"/invoices")
def index(q:str="",conn=Depends(conn_dep)):
    return page_invoices(conn,q)

@router.get(ROOT+"/invoices/new")
def new_invoice(conn=Depends(conn_dep)):
    body='<h1>فاکتور جدید</h1><p class="m2-hint">مبالغ به تومان هستند؛ مبلغ خرید از مه هر و قیمت فروش به مشتری را جدا ثبت کن.</p>'
    body+='<form action="'+ROOT+'/invoices/create" method="post"><section class="m2-card"><div class="m2-fields">'
    body+='<div><label>نام مشتری</label><input name="customer_name" list="sister-customer-list" required maxlength="120"></div>'
    body+='<datalist id="sister-customer-list">'+''.join('<option value="'+e(x[0])+'"></option>' for x in conn.execute("SELECT name FROM sister_invoice_customers ORDER BY name"))+'</datalist>'
    body+='<div><label>شماره تماس</label><input name="phone" maxlength="40"></div>'
    body+='<div><label>تاریخ فاکتور</label><input type="date" name="invoice_date" value="'+today()+'" required></div>'
    body+='<div><label>محل ارسال</label><select name="origin" id="invoice-origin"><option value="home">خانه (کسر از موجودی)</option><option value="factory">کارخانه (بدون کسر از خانه)</option></select></div></div></section>'
    body+='<section class="m2-card"><h3>سه سایز قالب</h3><p class="m2-hint">در ارسال از خانه، برای هر سایز کالای واقعی موجودی را انتخاب کن. برای کارخانه انتخاب کالا لازم نیست.</p>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>سایز</th><th>قالب موجودی خانه</th><th>تعداد</th><th>قیمت خرید هر عدد از مه هر</th><th>قیمت فروش هر عدد</th></tr></thead><tbody>'
    for size in SIZES:
        key={"کوچک":"small","متوسط":"medium","بزرگ":"large"}[size]
        body+='<tr><th>'+size+'</th><td><select name="master_'+key+'">'+sku_options(conn,size)+'</select></td>'
        body+='<td><input type="number" min="0" max="100000" name="qty_'+key+'" value="0" required></td>'
        body+='<td><input type="number" min="0" name="purchase_'+key+'" placeholder="تومان"></td>'
        body+='<td><input type="number" min="0" name="sale_'+key+'" placeholder="تومان"></td></tr>'
    body+='</tbody></table></div><div class="m2-fields"><div><label>توضیحات فاکتور</label><textarea name="notes" maxlength="350"></textarea></div></div>'
    body+='<button class="m2-btn" type="submit">ذخیره پیش‌نویس فاکتور</button></section></form>'
    return page_with_style("فاکتور جدید",body)

@router.post(ROOT+"/invoices/create")
async def create(request:Request,conn=Depends(conn_dep)):
    f=await request.form()
    lines={}
    for size,key in (("کوچک","small"),("متوسط","medium"),("بزرگ","large")):
        lines[size]={"qty":f.get("qty_"+key),"purchase":f.get("purchase_"+key),
                     "sale":f.get("sale_"+key),"master_id":f.get("master_"+key)}
    try:
        iid=create_invoice(conn,f.get("customer_name"),f.get("phone"),f.get("invoice_date"),
                           f.get("origin"),lines,f.get("notes"))
    except (ImportErrorDetail,ValueError,TypeError) as ex:return form_error(ex,"invoices/new")
    return RedirectResponse(ROOT+"/invoices/"+str(iid),status_code=303)

@router.get(ROOT+"/invoices/mehr")
def supplier(conn=Depends(conn_dep)):
    b=mehr_balance(conn)
    body='<h1>حساب مه هر</h1><p class="m2-hint">بدهی خرید و طلب واریز مشتری جدا هستند. تهاتر فقط با ثبت تو انجام می‌شود.</p>'
    body+='<div class="m2-finance-cards"><div class="m2-card"><small>بدهی من به مه هر</small><strong>'+fmt(b["debt"])+'</strong></div>'
    body+='<div class="m2-card"><small>طلب من از مه هر</small><strong>'+fmt(b["credit"])+'</strong></div>'
    body+='<div class="m2-card"><small>خالص (مثبت: طلبکار)</small><strong>'+fmt(b["net"])+'</strong></div></div>'
    body+='<div class="m2-tabs"><a href="'+ROOT+'/invoices">فاکتورها</a><a href="'+ROOT+'/invoices/purchases">ثبت خرید از مه هر</a></div>'
    body+='<section class="m2-card"><h3>ثبت تسویه یا تهاتر</h3>'
    body+='<form method="post" action="'+ROOT+'/invoices/mehr/settle"><input type="hidden" name="request_key" value="'+token()+'"><div class="m2-fields">'
    body+='<div><label>نوع عملیات</label><select name="kind"><option value="offset">تهاتر از طلب من</option><option value="paid_to_mehr">پرداخت من به مه هر</option><option value="received_from_mehr">واریز مه هر به من</option></select></div>'
    body+='<div><label>مبلغ (تومان)</label><input type="number" name="amount" min="1" required></div>'
    body+='<div><label>تاریخ ثبت</label><input type="date" name="day" value="'+today()+'" required></div>'
    body+='<div><label>حساب بانکی (فقط برای واریز واقعی)</label><select name="account_id"><option value="">انتخاب حساب</option>'+receipt_bank_options(conn)+'</select></div>'
    body+='<div><label>توضیحات</label><input name="notes" maxlength="350"></div>'
    body+='</div><button class="m2-btn">ثبت تسویه</button></form></section>'
    body+='<section class="m2-card"><h3>گردش حساب مه هر</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>نوع</th><th>تغییر بدهی</th><th>تغییر طلب</th><th>توضیحات</th></tr></thead><tbody>'
    labels={"purchase":"خرید خانه","factory_invoice":"ارسال کارخانه","customer_to_mehr":"واریز/چک مشتری","offset":"تهاتر","paid_to_mehr":"پرداخت به مه هر","received_from_mehr":"دریافت از مه هر"}
    for r in conn.execute("SELECT * FROM sister_mehr_ledger ORDER BY id DESC LIMIT 200"):
        body+='<tr><td>'+jal_label(r["occurred_on"])+'</td><td>'+e(labels.get(r["kind"],r["kind"]))+'</td><td>'+fmt(r["debt_delta"])+'</td><td>'+fmt(r["credit_delta"])+'</td><td>'+e(r["notes"])+'</td></tr>'
    body+='</tbody></table></div></section>'
    return page_with_style("حساب مه هر",body)

@router.post(ROOT+"/invoices/mehr/settle")
def settle(kind:str=Form(...),amount:str=Form(...),day:str=Form(...),request_key:str=Form(...),
           account_id:str=Form(""),notes:str=Form(""),conn=Depends(conn_dep)):
    try:settlement(conn,kind,amount,day,request_key,account_id,notes)
    except (ImportErrorDetail,ValueError) as ex:return form_error(ex,"invoices/mehr")
    return RedirectResponse(ROOT+"/invoices/mehr",status_code=303)

@router.get(ROOT+"/invoices/purchases")
def purchases(conn=Depends(conn_dep)):
    body='<h1>خرید قالب از مه هر</h1><p class="m2-hint">فقط خرید واقعی را اینجا ثبت کن؛ اصلاح شمارش موجودی، بدهی جدید نمی‌سازد.</p>'
    body+='<form action="'+ROOT+'/invoices/purchases/add" method="post"><input type="hidden" name="request_key" value="'+token()+'"><section class="m2-card"><div class="m2-fields">'
    body+='<div><label>قالب و سایز</label><select name="master_id" required><option value="">انتخاب</option>'
    for size in SIZES:
        body+='<optgroup label="'+size+'">'+''.join('<option value="'+str(r["id"])+'">'+e(r["title"])+' / '+e(r["color"])+' / '+size+'</option>' for r in conn.execute("SELECT id,title,color FROM master_products WHERE category='قالب' AND size=? AND active=1",(size,)))+'</optgroup>'
    body+='</select></div>'
    body+='<div><label>تعداد تحویل خانه</label><input name="qty" type="number" min="1" required></div>'
    body+='<div><label>قیمت خرید هر عدد از مه هر</label><input name="cost" type="number" min="1" required></div>'
    body+='<div><label>تاریخ خرید</label><input name="day" type="date" value="'+today()+'" required></div>'
    body+='<div><label>توضیحات</label><input name="notes" maxlength="350"></div></div>'
    body+='<button class="m2-btn">ثبت خرید و افزایش موجودی خانه</button></section></form>'
    body+='<p><a href="'+ROOT+'/invoices/mehr">مشاهده مانده مه هر</a></p>'
    return page_with_style("خرید از مه هر",body)

@router.post(ROOT+"/invoices/purchases/add")
def purchase_add(master_id:int=Form(...),qty:str=Form(...),cost:str=Form(...),day:str=Form(...),
                 request_key:str=Form(...),notes:str=Form(""),conn=Depends(conn_dep)):
    try:receive_purchase(conn,master_id,qty,cost,day,request_key,notes)
    except (ImportErrorDetail,ValueError) as ex:return form_error(ex,"invoices/purchases")
    return RedirectResponse(ROOT+"/invoices/mehr",status_code=303)

@router.get(ROOT+"/invoices/{invoice_id}")
def detail(invoice_id:int,conn=Depends(conn_dep)):
    try:inv,lines,receipts=invoice_detail(conn,invoice_id)
    except ImportErrorDetail as ex:return form_error(ex)
    total=sum(r["qty"]*r["sale_unit"] for r in lines)
    cost=sum(r["qty"]*r["purchase_unit"] for r in lines)
    paid=sum(r["amount"] for r in receipts)
    body='<h1>فاکتور شماره '+str(invoice_id)+'</h1><div class="m2-tabs"><button type="button" class="m2-btn" onclick="window.print()">چاپ فاکتور</button><a href="'+ROOT+'/invoices">فاکتورها</a><a href="'+ROOT+'/invoices/mehr">حساب مه هر</a></div>'
    body+='<section class="m2-card"><h3>'+e(inv["name"])+'</h3><p>'+e(inv["phone"])+' · '+jal_label(inv["invoice_date"])+' · '+("خانه" if inv["origin"]=="home" else "کارخانه")+' · '+("ارسال‌شده" if inv["status"]=="dispatched" else "پیش‌نویس")+'</p>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>سایز</th><th>تعداد</th><th>خرید هر عدد</th><th>فروش هر عدد</th><th>جمع فروش</th></tr></thead><tbody>'
    for r in lines:
        body+='<tr><td>'+e(r["size"])+'</td><td>'+fmt(r["qty"])+'</td><td>'+fmt(r["purchase_unit"])+'</td><td>'+fmt(r["sale_unit"])+'</td><td>'+fmt(r["qty"]*r["sale_unit"])+'</td></tr>'
    body+='</tbody></table></div><div class="m2-finance-cards"><div class="m2-card"><small>کل فاکتور</small><strong>'+fmt(total)+'</strong></div>'
    body+='<div class="m2-card"><small>بهای کالا</small><strong>'+fmt(cost)+'</strong></div>'
    body+='<div class="m2-card"><small>سود ناخالص</small><strong>'+fmt(total-cost)+'</strong></div>'
    body+='<div class="m2-card"><small>مانده مشتری</small><strong>'+fmt(total-paid)+'</strong></div></div><p>'+e(inv["notes"])+'</p>'
    if inv["status"]=="draft":
        body+='<form method="post" action="'+ROOT+'/invoices/'+str(invoice_id)+'/dispatch"><button class="m2-btn" onclick="return confirm(\'ارسال قطعی شود؟ این عملیات بر موجودی یا بدهی مه هر اثر می‌گذارد.\')">تأیید ارسال قطعی</button></form>'
    body+='</section>'
    body+='<section class="m2-card"><h3>پرداخت‌های مشتری</h3>'
    for r in receipts:
        label={"mine":"به حساب من","mehr":"به حساب مه هر","check_mehr":"چک تحویل مه هر"}[r["destination"]]
        body+='<p>'+jal_label(r["paid_on"])+' — '+e(label)+' — '+fmt(r["amount"])+' تومان'+(' — تاریخ چک '+jal_label(r["check_date"]) if r["check_date"] else '')+' — '+e(r["notes"])+'</p>'
    if total>paid:
        body+='<form method="post" action="'+ROOT+'/invoices/'+str(invoice_id)+'/receipt"><input type="hidden" name="request_key" value="'+token()+'"><div class="m2-fields">'
        body+='<div><label>مبلغ (تومان)</label><input type="number" min="1" max="'+str(total-paid)+'" name="amount" required></div>'
        body+='<div><label>دریافت‌کننده</label><select name="destination"><option value="mine">حساب من</option><option value="mehr">حساب مه هر</option><option value="check_mehr">چک تحویل مه هر</option></select></div>'
        body+='<div><label>حساب من (در صورت واریز به من)</label><select name="account_id"><option value="">انتخاب حساب</option>'+receipt_bank_options(conn)+'</select></div>'
        body+='<div><label>تاریخ پرداخت</label><input type="date" name="paid_on" value="'+today()+'" required></div>'
        body+='<div><label>تاریخ چک (در صورت چک)</label><input type="date" name="check_date"></div>'
        body+='<div><label>توضیحات</label><input name="notes" maxlength="350"></div>'
        body+='</div><button class="m2-btn">ثبت پرداخت مشتری</button></form>'
    body+='</section>'
    return page_with_style("جزئیات فاکتور",body)

@router.post(ROOT+"/invoices/{invoice_id}/dispatch")
def dispatch(invoice_id:int,conn=Depends(conn_dep)):
    try:dispatch_invoice(conn,invoice_id)
    except (ImportErrorDetail,ValueError) as ex:return form_error(ex,"invoices/"+str(invoice_id))
    return RedirectResponse(ROOT+"/invoices/"+str(invoice_id),status_code=303)

@router.post(ROOT+"/invoices/{invoice_id}/receipt")
def receipt(invoice_id:int,amount:str=Form(...),destination:str=Form(...),paid_on:str=Form(...),
            request_key:str=Form(...),account_id:str=Form(""),check_date:str=Form(""),
            notes:str=Form(""),conn=Depends(conn_dep)):
    try:record_receipt(conn,invoice_id,amount,destination,paid_on,request_key,account_id,check_date,notes)
    except (ImportErrorDetail,ValueError) as ex:return form_error(ex,"invoices/"+str(invoice_id))
    return RedirectResponse(ROOT+"/invoices/"+str(invoice_id),status_code=303)
