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
from .sister_invoices import (SIZES,create_invoice,submit_invoice,dispatch_invoice,record_receipt,
    receive_purchase,settlement,mehr_balance,mehr_open_items,invoices,invoice_detail)
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
    body+='<div class="m2-tabs"><a href="'+ROOT+'/invoices/new">+ فاکتور جدید</a><a href="'+ROOT+'/invoices/mehr">حساب مه هر</a><a href="'+ROOT+'/purchases">خرید کالا</a></div>'
    body+='<form method="get" action="'+ROOT+'/invoices" class="m2-filters"><label>جست‌وجوی مشتری با نام</label><input name="q" value="'+e(query)+'" placeholder="نام مشتری"><button class="m2-btn">جست‌وجو</button></form>'
    body+='<section class="m2-card"><h3>فاکتورهای ثبت‌شده</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>شماره</th><th>مشتری</th><th>تاریخ</th><th>مبدأ</th><th>وضعیت فاکتور</th><th>جمع فاکتور</th><th>دریافتی</th><th>مانده</th><th>وضعیت تسویه</th></tr></thead><tbody>'
    for r in rows:
        body+='<tr><td><a href="'+ROOT+'/invoices/'+str(r["id"])+'">#'+str(r["id"])+'</a></td><td>'+e(r["name"])+'</td><td>'+jal_label(r["invoice_date"])+'</td><td>'+("خانه" if r["origin"]=="home" else "کارخانه")+'</td><td>'+("ارسال‌شده" if r["status"]=="dispatched" else "پیش‌نویس")+'</td><td>'+fmt(r["gross"])+'</td><td>'+fmt(r["paid"])+'</td><td>'+fmt(r["gross"]-r["paid"])+'</td><td>'+("تسویه‌شده" if r["paid"]>=r["gross"] else "باز / تسویه‌نشده")+'</td></tr>'
    body+='</tbody></table></div></section>'
    return page_with_style("فاکتور مشتریان",body)

@router.get(ROOT+"/invoices")
def index(q:str="",conn=Depends(conn_dep)):
    return page_invoices(conn,q)

@router.get(ROOT+"/invoices/new")
def new_invoice(conn=Depends(conn_dep)):
    body='<h1>فاکتور جدید</h1><p class="m2-hint">همه اطلاعات، جمع فاکتور و دریافت اولیه را همین‌جا ثبت کن. با ثبت نهایی، فاکتور قطعی و موجودی دقیقاً یک بار اصلاح می‌شود.</p>'
    body+='<form id="sister-one-invoice" action="'+ROOT+'/invoices/create" method="post">'
    body+='<input type="hidden" name="request_key" value="'+token()+'">'
    body+='<section class="m2-card"><h3>مشخصات و محل ارسال</h3><div class="m2-fields">'
    body+='<div><label>نام مشتری</label><input name="customer_name" list="sister-customer-list" required maxlength="120"></div>'
    body+='<datalist id="sister-customer-list">'+''.join('<option value="'+e(x[0])+'"></option>' for x in conn.execute("SELECT name FROM sister_invoice_customers ORDER BY name"))+'</datalist>'
    body+='<div><label>شماره تماس</label><input name="phone" maxlength="40"></div>'
    body+='<div><label>تاریخ فاکتور</label><input type="date" name="invoice_date" value="'+today()+'" required></div>'
    body+='<div><label>محل کسر کالا / ارسال (فقط یک‌بار)</label><select name="origin" id="invoice-origin"><option value="home">خانه (کسر از موجودی خانه)</option><option value="factory">کارخانه (خرید مستقیم از مه هر، بدون کسر از خانه)</option></select></div>'
    body+='</div></section>'
    body+='<section class="m2-card"><h3>اقلام فاکتور</h3>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>سایز</th><th>تعداد</th><th>قیمت خرید هر عدد از مه هر</th><th>قیمت فروش هر عدد</th><th>جمع ردیف</th></tr></thead><tbody>'
    for size,key in (("کوچک","small"),("متوسط","medium"),("بزرگ","large")):
        body+='<tr><th>'+size+'</th><td><input type="number" min="0" max="100000" name="qty_'+key+'" value="0" required data-invoice-qty></td>'
        body+='<td><input type="number" min="0" name="purchase_'+key+'" placeholder="تومان"></td>'
        body+='<td><input type="number" min="0" name="sale_'+key+'" placeholder="تومان" data-invoice-sale></td>'
        body+='<td><strong data-invoice-row>۰</strong> تومان</td></tr>'
    body+='</tbody></table></div>'
    # A physical SKU must be unambiguous; show a selector only for sizes with multiple active SKUs.
    for size,key in (("کوچک","small"),("متوسط","medium"),("بزرگ","large")):
        choices=list(conn.execute("""SELECT id,title,color,seller_stock FROM master_products
            WHERE category='قالب' AND size=? AND active=1 ORDER BY title,color,id""",(size,)))
        if len(choices)>1:
            body+='<div class="m2-fields invoice-sku-ambiguous"><div><label>مدل / رنگ قالب '+size+' (فقط در صورت ارسال از خانه و ثبت تعداد)</label>'
            body+='<select name="master_'+key+'"><option value="">انتخاب مدل دقیق</option>'
            body+=''.join('<option value="'+str(r["id"])+'">'+e(r["title"])+' / '+e(r["color"])+' · موجودی '+fmt(r["seller_stock"])+'</option>' for r in choices)
            body+='</select></div></div>'
        elif len(choices)==1:
            body+='<input type="hidden" name="master_'+key+'" value="'+str(choices[0]["id"])+'">'
    body+='<div class="m2-fields"><div><label>توضیحات فاکتور</label><textarea name="notes" maxlength="350"></textarea></div></div></section>'
    body+='<section class="m2-card"><h3>جمع فاکتور و دریافتی</h3>'
    body+='<div class="m2-finance-cards">'
    body+='<div class="m2-card"><small>جمع کل فاکتور</small><strong id="invoice-grand-total">۰</strong><span class="m2-unit">تومان</span></div>'
    body+='<div class="m2-card"><small>سود ناخالص فاکتور</small><strong id="invoice-gross-profit">۰</strong><span class="m2-unit">تومان · فروش منهای بهای خرید</span></div>'
    body+='<div class="m2-card"><small>دریافت اولیه</small><strong id="invoice-paid-total">۰</strong><span class="m2-unit">تومان</span></div>'
    body+='<div class="m2-card"><small>مانده مشتری</small><strong id="invoice-remaining">۰</strong><span class="m2-unit">تومان</span></div></div>'
    body+='<div class="m2-fields"><div><label>مبلغ دریافتی هنگام ثبت (تومان؛ اختیاری)</label><input type="number" min="0" value="0" name="initial_amount" id="invoice-initial-amount"></div>'
    body+='<div><label>دریافت‌شده توسط</label><select name="destination" id="invoice-destination"><option value="mine">من (بدون انتخاب بانک)</option><option value="mehr">مه هر</option><option value="check_mehr">چک تحویل مه هر</option></select></div>'
    body+='<div><label>تاریخ پرداخت</label><input type="date" name="paid_on" value="'+today()+'"></div>'
    body+='<div id="invoice-check-date-wrap" style="display:none"><label>تاریخ چک</label><input type="date" name="check_date"></div>'
    body+='<div><label>شرح دریافت / شماره پیگیری (اختیاری)</label><input name="receipt_notes" maxlength="350"></div></div>'
    body+='<p class="m2-hint">اگر دریافت به من ثبت شود، ولی بانک مشخص نباشد، دریافت در تاریخچه فاکتور ثبت می‌شود؛ به مانده هیچ حساب بانکی اضافه نمی‌شود تا حساب واقعی تعیین شود.</p>'
    body+='<button class="m2-btn" type="submit" id="invoice-save-button">ثبت نهایی فاکتور و دریافتی</button>'
    body+='</section></form>'
    body+=r'''<script>
(function(){
  var form=document.getElementById("sister-one-invoice");
  if(!form)return;
  var fmt=function(n){return new Intl.NumberFormat("fa-IR").format(n);};
  var number=function(name){var x=form.elements[name];return x?Math.max(0,Number(x.value)||0):0;};
  var qty=form.querySelectorAll("[data-invoice-qty]"),sales=form.querySelectorAll("[data-invoice-sale]");
  var total=document.getElementById("invoice-grand-total"),profit=document.getElementById("invoice-gross-profit"),paid=document.getElementById("invoice-paid-total"),balance=document.getElementById("invoice-remaining");
  function refresh(){
    var sum=0,cost=0;
    for(var i=0;i<qty.length;i++){
      var line=(Number(qty[i].value)||0)*(Number(sales[i].value)||0);
      var purchase=qty[i].closest("tr").querySelector('input[name^="purchase_"]');
      cost+=(Number(qty[i].value)||0)*(Number(purchase.value)||0);
      qty[i].closest("tr").querySelector("[data-invoice-row]").textContent=fmt(line);
      sum+=line;
    }
    var amount=number("initial_amount");
    total.textContent=fmt(sum);profit.textContent=fmt(sum-cost);paid.textContent=fmt(amount);balance.textContent=fmt(sum-amount);
    form.elements["initial_amount"].max=String(sum);
    var home=form.elements["origin"].value==="home";
    form.querySelectorAll(".invoice-sku-ambiguous").forEach(function(x){x.style.display=home?"":"none";});
    document.getElementById("invoice-check-date-wrap").style.display=form.elements["destination"].value==="check_mehr"?"":"none";
  }
  form.addEventListener("input",refresh);form.addEventListener("change",refresh);
  form.addEventListener("submit",function(ev){
    var grand=0;
    for(var i=0;i<qty.length;i++)grand+=(Number(qty[i].value)||0)*(Number(sales[i].value)||0);
    if(grand<=0||number("initial_amount")>grand){ev.preventDefault();alert("جمع فاکتور و مبلغ دریافتی را بررسی کن.");return;}
    document.getElementById("invoice-save-button").disabled=true;
  });
  refresh();
})();
</script>'''
    return page_with_style("فاکتور جدید",body)

@router.post(ROOT+"/invoices/create")
async def create(request:Request,conn=Depends(conn_dep)):
    f=await request.form()
    lines={}
    for size,key in (("کوچک","small"),("متوسط","medium"),("بزرگ","large")):
        lines[size]={"qty":f.get("qty_"+key),"purchase":f.get("purchase_"+key),
                     "sale":f.get("sale_"+key),"master_id":f.get("master_"+key)}
    try:
        iid=submit_invoice(conn,f.get("customer_name"),f.get("phone"),f.get("invoice_date"),
                           f.get("origin"),lines,f.get("notes"),f.get("request_key"),
                           f.get("initial_amount","0"),f.get("destination","mine"),
                           f.get("paid_on",""),f.get("check_date",""),f.get("receipt_notes",""))
    except (ImportErrorDetail,ValueError,TypeError) as ex:return form_error(ex,"invoices/new")
    return RedirectResponse(ROOT+"/invoices/"+str(iid),status_code=303)

@router.get(ROOT+"/invoices/mehr")
def supplier(conn=Depends(conn_dep)):
    b=mehr_balance(conn)
    body='<h1>حساب مه هر</h1><p class="m2-hint">واریزی مشتری به حساب مهر، پولی برای تسویه بدهی خرید از مهر است؛ تا وقتی بدهی بیشتر باشد، تو از مهر طلب خالص نداری. ثبت تهاتر عملیاتی جداگانه است.</p>'
    body+='<div class="m2-msg">مانده قدیمی مه هر هنوز با دفتر جدید تطبیق داده نشده است؛ عدد فعلی، مانده قطعی همه سال‌ها نیست.</div>'
    body+='<div class="m2-finance-cards"><div class="m2-card"><small>بدهی خالص من به مه هر</small><strong>'+fmt(max(0,-b["net"]))+'</strong><span class="m2-unit">تومان</span></div>'
    body+='<div class="m2-card"><small>طلب خالص من از مه هر</small><strong>'+fmt(max(0,b["net"]))+'</strong><span class="m2-unit">تومان</span></div>'
    body+='</div>'
    body+='<p class="m2-hint">ریز محاسبه: بدهی خرید '+fmt(b["debt"])+' تومان، وجوه مشتری نزد مهر '+fmt(b["credit"])+' تومان. مانده‌های بالا خالص این دو مبلغ‌اند.</p>'
    open_items=mehr_open_items(conn)
    body+='<section class="m2-card"><h3>بدهی‌های باز مهر به تفکیک فاکتور و خرید</h3>'
    if open_items:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>سند</th><th>تاریخ</th><th>بهای خرید</th><th>واریزی مشتری نزد مهر</th><th>پرداخت اختصاص‌یافته</th><th>مانده سند</th></tr></thead><tbody>'
        for item in open_items:
            title='<a href="'+ROOT+'/invoices/'+str(item["id"])+'">'+e(item["label"])+'</a>' if item["kind"]=="invoice" else e(item["label"])
            body+='<tr><td>'+title+'</td><td>'+jal_label(item["date"])+'</td><td>'+fmt(item["gross"])+'</td><td>'+fmt(item["credit"])+'</td><td>'+fmt(item["paid"])+'</td><td>'+fmt(item["remaining"])+'</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">فعلاً فاکتور یا خرید باز ثبت نشده است.</p>'
    body+='</section>'
    body+='<div class="m2-tabs"><a href="'+ROOT+'/invoices">فاکتورها</a><a href="'+ROOT+'/purchases">ثبت خرید کالا</a></div>'
    body+='<section class="m2-card"><h3>ثبت تسویه یا تهاتر</h3>'
    body+='<form method="post" action="'+ROOT+'/invoices/mehr/settle"><input type="hidden" name="request_key" value="'+token()+'"><div class="m2-fields">'
    body+='<div><label>نوع عملیات</label><select name="kind" id="mehr-action"><option value="paid_to_mehr">پرداخت من به مه هر</option><option value="offset">تهاتر وجوه مشتری با بدهی خرید</option><option value="received_from_mehr">واریز مه هر به من</option></select></div>'
    body+='<div id="mehr-target-wrap"><label>انتخاب فاکتور یا خرید بابت پرداخت</label><select name="target" id="mehr-target"><option value="">انتخاب سند</option>'
    for item in open_items:
        if item["remaining"]>0:
            body+='<option value="'+e(item["target"])+'">'+e(item["label"])+' · مانده '+fmt(item["remaining"])+' تومان</option>'
    body+='</select></div>'
    body+='<div><label>مبلغ (تومان)</label><input type="text" inputmode="numeric" dir="ltr" name="amount" placeholder="مثلاً 18000000" required></div>'
    body+='<div><label>تاریخ ثبت</label><input type="date" name="day" value="'+today()+'" required></div>'
    body+='<p class="m2-hint">پرداخت واقعی بدهی خالص را کم می‌کند و به فاکتور انتخاب‌شده وصل می‌شود. تهاترِ ۵۸ میلیون واریزی مشتری از قبل در مانده خالص حساب شده؛ تهاترِ جداگانه مانده خالص را دوباره کم نمی‌کند و برای تطبیق دوطرفه دفتر است. هیچ بانکی انتخاب نمی‌شود.</p>'
    body+='<div><label>توضیحات</label><input name="notes" maxlength="350"></div>'
    body+='</div><button class="m2-btn">ثبت تسویه</button></form>'
    body+='<script>(function(){var a=document.getElementById("mehr-action"),w=document.getElementById("mehr-target-wrap"),t=document.getElementById("mehr-target");if(!a)return;function update(){var pay=a.value==="paid_to_mehr";w.style.display=pay?"":"none";t.required=pay;}a.addEventListener("change",update);update();})();</script>'
    body+='</section>'
    body+='<section class="m2-card"><h3>گردش حساب مه هر</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>نوع</th><th>تغییر بدهی خرید</th><th>تغییر وجه مشتری نزد مهر</th><th>توضیحات</th></tr></thead><tbody>'
    labels={"purchase_general":"خرید کالا","purchase":"خرید خانه","factory_invoice":"ارسال کارخانه","customer_to_mehr":"واریز/چک مشتری","offset":"تهاتر","paid_to_mehr":"پرداخت به مه هر","received_from_mehr":"دریافت از مه هر"}
    for r in conn.execute("SELECT * FROM sister_mehr_ledger ORDER BY id DESC LIMIT 200"):
        body+='<tr><td>'+jal_label(r["occurred_on"])+'</td><td>'+e(labels.get(r["kind"],r["kind"]))+'</td><td>'+fmt(r["debt_delta"])+'</td><td>'+fmt(r["credit_delta"])+'</td><td>'+e(r["notes"])+'</td></tr>'
    body+='</tbody></table></div></section>'
    return page_with_style("حساب مه هر",body)

@router.post(ROOT+"/invoices/mehr/settle")
def settle(kind:str=Form(...),amount:str=Form(...),day:str=Form(...),request_key:str=Form(...),
           account_id:str=Form(""),notes:str=Form(""),target:str=Form(""),conn=Depends(conn_dep)):
    try:
        if kind=="paid_to_mehr" and not target:
            raise ImportErrorDetail("فاکتور یا خرید مورد تسویه را انتخاب کن.")
        settlement(conn,kind,amount,day,request_key,account_id,notes,target=target)
    except (ImportErrorDetail,ValueError) as ex:return form_error(ex,"invoices/mehr")
    return RedirectResponse(ROOT+"/invoices/mehr",status_code=303)

@router.get(ROOT+"/invoices/purchases")
def purchases(conn=Depends(conn_dep)):
    # One source of truth for NEW purchases. Old purchasing database rows and
    # legacy POST endpoint remain intact for audit/compatibility.
    return RedirectResponse(ROOT+"/purchases",status_code=303)

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
    body='<h1>فاکتور شماره '+str(invoice_id)+'</h1><div class="m2-tabs"><a href="'+ROOT+'/invoices">فاکتورها</a><a href="'+ROOT+'/invoices/mehr">حساب مه هر</a></div>'
    body+='<section class="m2-card"><h3>'+e(inv["name"])+'</h3><p>'+e(inv["phone"])+' · '+jal_label(inv["invoice_date"])+' · '+("خانه" if inv["origin"]=="home" else "کارخانه")+' · '+("ارسال‌شده" if inv["status"]=="dispatched" else "پیش‌نویس")+'</p>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>سایز</th><th>تعداد</th><th>خرید هر عدد</th><th>فروش هر عدد</th><th>جمع فروش</th></tr></thead><tbody>'
    for r in lines:
        body+='<tr><td>'+e(r["size"])+'</td><td>'+fmt(r["qty"])+'</td><td>'+fmt(r["purchase_unit"])+'</td><td>'+fmt(r["sale_unit"])+'</td><td>'+fmt(r["qty"]*r["sale_unit"])+'</td></tr>'
    body+='</tbody></table></div><div class="m2-finance-cards"><div class="m2-card"><small>کل فاکتور</small><strong>'+fmt(total)+'</strong></div>'
    body+='<div class="m2-card"><small>بهای کالا</small><strong>'+fmt(cost)+'</strong></div>'
    body+='<div class="m2-card"><small>سود ناخالص</small><strong>'+fmt(total-cost)+'</strong></div>'
    body+='<div class="m2-card"><small>دریافتی مشتری</small><strong>'+fmt(paid)+'</strong></div>'
    body+='<div class="m2-card"><small>مانده مشتری</small><strong>'+fmt(total-paid)+'</strong></div></div><p>'+e(inv["notes"])+'</p>'
    if inv["origin"]=="factory" and inv["status"]=="dispatched":
        item=next((r for r in mehr_open_items(conn) if r["kind"]=="invoice" and r["id"]==invoice_id),None)
        if item:
            body+='<p class="m2-hint">حساب تأمین‌کننده این فاکتور: بهای خرید '+fmt(item["gross"])+' تومان، وجوه مشتری نزد مهر '+fmt(item["credit"])+' تومان، پرداخت من به مهر '+fmt(item["paid"])+' تومان، <strong>مانده پرداخت این فاکتور به مهر: '+fmt(item["remaining"])+' تومان</strong>. این مبلغ با مانده مشتری فرق دارد.</p>'
            linked=list(conn.execute("""SELECT l.occurred_on,l.debt_delta,l.notes
                FROM sister_mehr_settlement_links a
                JOIN sister_mehr_ledger l ON l.reference=a.reference
                WHERE a.target_type='invoice' AND a.target_id=? AND l.kind='paid_to_mehr'
                ORDER BY l.id DESC""",(invoice_id,)))
            if linked:
                body+='<h3>تاریخچه تسویه من با مهر برای این فاکتور</h3>'
                for payment in linked:
                    body+='<p>'+jal_label(payment["occurred_on"])+' — '+fmt(-payment["debt_delta"])+' تومان — '+e(payment["notes"])+'</p>'
    if inv["status"]=="draft":
        body+='<form method="post" action="'+ROOT+'/invoices/'+str(invoice_id)+'/dispatch"><button class="m2-btn" onclick="return confirm(\'ارسال قطعی شود؟ این عملیات بر موجودی یا بدهی مه هر اثر می‌گذارد.\')">تأیید ارسال قطعی</button></form>'
    body+='</section>'
    body+='<section class="m2-card"><h3>پرداخت‌های مشتری</h3>'
    for r in receipts:
        label={"mine":"به حساب من","mehr":"به حساب مه هر","check_mehr":"چک تحویل مه هر"}[r["destination"]]
        body+='<p>'+jal_label(r["paid_on"])+' — '+e(label)+(' (بانک نامشخص)' if r["destination"]=="mine" and r["account_id"] is None else '')+' — '+fmt(r["amount"])+' تومان'+(' — تاریخ چک '+jal_label(r["check_date"]) if r["check_date"] else '')+' — '+e(r["notes"])+'</p>'
    if total>paid:
        body+='<form method="post" action="'+ROOT+'/invoices/'+str(invoice_id)+'/receipt"><input type="hidden" name="request_key" value="'+token()+'"><div class="m2-fields">'
        body+='<div><label>مبلغ (تومان)</label><input type="number" min="1" max="'+str(total-paid)+'" name="amount" required></div>'
        body+='<div><label>دریافت‌کننده</label><select name="destination"><option value="mine">حساب من</option><option value="mehr">حساب مه هر</option><option value="check_mehr">چک تحویل مه هر</option></select></div>'
        body+='<input type="hidden" name="account_id" value=""><p class="m2-hint">دریافت به من بدون انتخاب بانک ثبت می‌شود؛ تا زمان تعیین حساب واقعی به موجودی بانک اضافه نمی‌شود.</p>'
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
