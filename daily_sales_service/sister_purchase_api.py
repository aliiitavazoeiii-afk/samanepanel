"""Excel-style physical purchasing for mold, Dia, Darma and Bodyguard."""
import uuid
from fastapi import APIRouter,Depends,Form,Request
from fastapi.responses import RedirectResponse
from .app import ROOT,conn_dep,e,fmt
from .calendar_jalali import label as jal_label
from .effective_costs import today
from .engine import ImportErrorDetail
from .master_v2_ui import page_with_style
from .sister_finance_logic import accounts
from .sister_purchase_grid import purchase_grid
from .sister_purchases import (CATEGORIES,register_purchase,register_supplier_payment,
    suppliers,supplier_totals,purchase_history,purchase_detail,supplier_history)

router=APIRouter()

def _token():
    return uuid.uuid4().hex

def _error(exc):
    return page_with_style("خطای خرید",
        '<h2>ثبت انجام نشد</h2><div class="m2-msg">'+e(str(exc))+
        '</div><p><a class="m2-btn" href="'+ROOT+'/purchases">بازگشت به خرید کالا</a></p>')

def _product_select(conn,index):
    html='<select name="master_'+str(index)+'"><option value="">انتخاب کالا</option>'
    for category in CATEGORIES:
        html+='<optgroup label="'+e(category)+'">'
        for r in conn.execute("""SELECT id,title,color,size,subtype,seller_stock
                    FROM master_products WHERE category=? AND active=1
                    ORDER BY title,color,size,id""",(category,)):
            desc=" / ".join(x for x in (r["title"],r["subtype"],r["color"],r["size"]) if x and x!="-")
            html+='<option value="'+str(r["id"])+'">'+e(desc)+' — خانه: '+fmt(r["seller_stock"])+'</option>'
        html+='</optgroup>'
    return html+'</select>'

def _account_options(conn):
    return ''.join('<option value="'+str(r["id"])+'">'+e(r["title"])+'</option>'
                   for r in accounts(conn) if r["active"])

@router.get(ROOT+"/purchases")
def purchase_home(supplier_id:str="",receipt_id:str="",conn=Depends(conn_dep)):
    body='<h1>خرید کالا</h1><p class="m2-hint">ثبت خرید قالب، دیا، دارما، بادیگارد و زیرپوش؛ به سبک جدول خرید تکوین. خرید قطعی به موجودی فیزیکی اضافه می‌شود و بدهی تأمین‌کننده را ثبت می‌کند.</p>'
    body+='<p class="m2-msg">مانده این قسمت از خریدهای جدید محاسبه می‌شود؛ بدهی‌های قدیمی تأمین‌کنندگان هنوز وارد نشده‌اند. خرید یا افزایش موجودی قدیمی را دوباره ثبت نکن.</p>'
    body+='<section class="m2-card"><h3>ثبت خرید جدید</h3><form id="purchase-entry-form" method="post" action="'+ROOT+'/purchases/add"><input type="hidden" name="request_key" value="'+_token()+'">'
    body+='<div class="m2-fields"><div><label>تأمین‌کننده</label><input list="sister-suppliers" name="supplier" maxlength="120" required placeholder="مثلاً دیا یا دارما"></div>'
    body+='<datalist id="sister-suppliers"><option value="مه هر"></option>'+''.join('<option value="'+e(s["name"])+'"></option>' for s in suppliers(conn))+'</datalist>'
    body+='<div><label>تاریخ خرید</label><input type="date" name="purchase_date" value="'+today()+'" required></div>'
    body+='<div><label>موجودی کجا اضافه شود؟</label><select name="warehouse"><option value="home">خانه</option><option value="khorshid">خورشید</option></select></div>'
    body+='<div><label>شماره فاکتور تأمین‌کننده (اختیاری)</label><input name="supplier_invoice" maxlength="100"></div></div>'
    body+='<div class="m2-fields"><div><label>تخفیف کل خرید (%)</label><input id="purchase-discount-percent" name="discount_percent" type="number" step="0.01" min="0" max="99.99" value="0" required></div><div><label>توضیحات خرید (اختیاری)</label><input name="notes" maxlength="500"></div></div>'
    body+=purchase_grid(conn)
    body+='<button type="submit" class="m2-btn">ثبت قطعی خرید و افزایش موجودی</button></form></section>'
    if receipt_id:
        try:p,lines=purchase_detail(conn,int(receipt_id))
        except (ValueError,TypeError,ImportErrorDetail) as exc:return _error(exc)
        body+='<section class="m2-card"><h3>رسید خرید #'+str(p["id"])+' از '+e(p["supplier_name"])+'</h3>'
        body+='<p>تاریخ: '+jal_label(p["purchase_date"])+' — مقصد: '+("خانه" if p["warehouse"]=="home" else "خورشید")+' — قبل تخفیف: '+fmt(p["subtotal_toman"] or p["total_toman"])+' تومان — تخفیف: '+e(p["discount_percent"])+'٪ — جمع نهایی: '+fmt(p["total_toman"])+' تومان</p>'
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>کالا</th><th>تعداد</th><th>بهای هر عدد</th><th>جمع</th></tr></thead><tbody>'
        for l in lines:
            body+='<tr><td>'+e(" / ".join(x for x in (l["category"],l["title"],l["subtype"],l["color"],l["size"]) if x and x!="-"))+'</td><td>'+fmt(l["quantity"])+'</td><td>'+fmt(l["unit_cost_toman"])+'</td><td>'+fmt(l["quantity"]*l["unit_cost_toman"])+'</td></tr>'
        body+='</tbody></table></div></section>'
    body+='<section class="m2-card"><h3>خریدهای اخیر</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>تأمین‌کننده</th><th>مبلغ</th><th>موجودی</th><th>جزئیات</th></tr></thead><tbody>'
    for p in purchase_history(conn):
        body+='<tr><td>'+jal_label(p["purchase_date"])+'</td><td>'+e(p["supplier_name"])+'</td><td>'+fmt(p["total_toman"])+'</td><td>'+("خانه" if p["warehouse"]=="home" else "خورشید")+'</td><td><a href="'+ROOT+'/purchases?receipt_id='+str(p["id"])+'">نمایش</a></td></tr>'
    body+='</tbody></table></div></section>'
    return page_with_style("خرید کالا",body)

@router.post(ROOT+"/purchases/add")
async def add_purchase(request:Request,conn=Depends(conn_dep)):
    form=await request.form()
    items=[]
    for index in range(1,121):
        mid=form.get("master_"+str(index),"")
        if not mid:continue
        items.append((mid,form.get("qty_"+str(index),""),form.get("cost_"+str(index),"")))
    try:
        register_purchase(conn,form.get("supplier"),form.get("purchase_date"),
                          form.get("warehouse"),items,form.get("request_key"),
                          form.get("supplier_invoice"),form.get("notes"),form.get("discount_percent","0"))
    except (ImportErrorDetail,ValueError,TypeError) as ex:return _error(ex)
    return RedirectResponse(ROOT+"/purchases",status_code=303)

@router.post(ROOT+"/purchases/payments/add")
def add_payment(supplier_id:str=Form(...),bank_id:str=Form(...),amount:str=Form(...),
                paid_on:str=Form(...),request_key:str=Form(...),notes:str=Form(""),
                conn=Depends(conn_dep)):
    try:
        register_supplier_payment(conn,supplier_id,bank_id,amount,paid_on,request_key,notes)
    except (ImportErrorDetail,ValueError,TypeError) as ex:return _error(ex)
    return RedirectResponse(ROOT+"/finance/movements?section=payment",status_code=303)
