import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import jdatetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .finance import digikala_fee_for_unit, sale_line_metrics
from .final_services import (
    account_balance, close_batch, finished_inventory_value, inventory_unit_cost,
    prepare_batch, production_batch_metrics, raw_material_value, resolve_shortage,
    setting_decimal, supplier_balance, sync_bank_transfer, sync_digikala_settlement,
    sync_elastic_movement, sync_expense, sync_fabric_roll, sync_inventory_adjustment,
    sync_pedram_payment, sync_production_receipt, sync_return, sync_sale,
    sync_stock_transfer, sync_takvin_payment, sync_takvin_purchase,
)
from .models import (
    Account, AccountEntry, BankTransfer, Brand, Color, DigikalaSettlement,
    ElasticBalance, ElasticMovement, Expense, ExpenseCategory, FabricRoll,
    InventoryAdjustment, InventoryMovement, PedramPayment, ProductSize,
    ProductionBatch, ProductionReceipt, ReturnRecord, SaleDay, SaleLine,
    SaleShortage, SaleSnapshot, SideAsset, Size, StockBalance, StockLocation,
    StockThreshold, StockTransfer, SupplierAccount, SupplierEntry, TakvinPayment,
    TakvinPurchase,
)


def _int(value, default=0):
    try:
        if value in (None, ""): return default
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", ""))
    except Exception: return default


def _dec(value, default="0"):
    try:
        if value in (None, ""): return Decimal(default)
        return Decimal(str(value).replace(",", ".").strip())
    except Exception: return Decimal(default)


def _date(value=None): return parse_jalali_date(value) if value else date.today()
def _today_j(): return format_jalali(date.today())


def _brand_sizes(brand):
    qs=Size.objects.all().order_by("sort_order","id")
    if brand and brand.name=="تکوین": qs=qs.exclude(name__in=["3XL","4XL"])
    return list(qs)


def _day_metrics(day):
    total={"gross":0,"digikala_fee":0,"cogs":0,"profit":0,"shorts":0,"packs":0}
    for line in day.lines.filter(quantity__gt=0).select_related("product_size__product","product_size__size"):
        m=sale_line_metrics(line)
        for k in total: total[k]+=m[k]
    total["margin"]=(total["profit"]/total["gross"]*100) if total["gross"] else 0
    return total


@login_required
def dashboard(request):
    today=SaleDay.objects.filter(date=date.today()).first(); today_metrics=_day_metrics(today) if today else {"gross":0,"profit":0,"shorts":0,"packs":0,"digikala_fee":0,"cogs":0,"margin":0}
    accounts={a.key:{"title":a.title,"balance":account_balance(a)} for a in Account.objects.all()}; alerts=[]
    for t in StockThreshold.objects.select_related("brand","size","color"):
        if t.brand.name=="تکوین" and t.size.name in ("3XL","4XL"): continue
        qs=StockBalance.objects.filter(brand=t.brand,size=t.size,color=t.color); home=qs.filter(location__key=StockLocation.HOME).aggregate(v=Sum("qty"))["v"] or 0; total=qs.aggregate(v=Sum("qty"))["v"] or 0; kh=qs.filter(location__key=StockLocation.KHORSHID).aggregate(v=Sum("qty"))["v"] or 0
        if total<=t.total_min: alerts.append({"kind":"production","title":f"{t.color.name} / {t.size.name}","brand":t.brand.name,"value":total,"target":t.total_min})
        elif home<=t.home_min and t.brand.name=="دارما": alerts.append({"kind":"transfer","title":f"{t.color.name} / {t.size.name}","brand":t.brand.name,"value":home,"target":kh})
    shortages=SaleShortage.objects.filter(resolved=False).select_related("sale_line__product_size__product","source_color")[:8]
    return render(request,"core/dashboard_final.html",{"today_metrics":today_metrics,"accounts":accounts,"alerts":alerts[:12],"shortages":shortages,"finished_value":finished_inventory_value(),"raw_value":raw_material_value(),"today_j":_today_j()})


@login_required
def sale_brand(request,day_id):
    day=get_object_or_404(SaleDay,id=day_id); cards=[]
    for brand in Brand.objects.filter(active=True):
        sizes=_brand_sizes(brand); cards.append({"brand":brand,"first":sizes[0] if sizes else None})
    return render(request,"core/sale_brand_final.html",{"day":day,"cards":cards})


@login_required
@require_POST
@transaction.atomic
def sale_line_save(request):
    day=get_object_or_404(SaleDay,id=request.POST.get("day_id")); ps=get_object_or_404(ProductSize.objects.select_related("product__brand","size"),id=request.POST.get("product_size_id"))
    if ps.product.brand.name=="تکوین" and ps.size.name in ("3XL","4XL"): return HttpResponse("این سایز برای تکوین فعال نیست.",status=400)
    qty=max(0,_int(request.POST.get("quantity"))); price=max(0,_int(request.POST.get("sale_price"),ps.default_sale_price))
    line,_=SaleLine.objects.select_for_update().get_or_create(day=day,product_size=ps,defaults={"quantity":0,"sale_price":price}); line.quantity=qty; line.sale_price=price; line.save(update_fields=["quantity","sale_price"])
    snap,_=SaleSnapshot.objects.get_or_create(sale_line=line); snap.pack_qty=int(ps.product.pack_qty or 0)
    snap.unit_cost=int(ps.unit_cost or (setting_decimal("darma_accounting_unit_cost",61000) if ps.product.brand.name=="دارما" else inventory_unit_cost(ps.product.brand,ps.size))); snap.digikala_fee_unit=digikala_fee_for_unit(price); snap.save()
    result=sync_sale(line); pending=list(line.shortages.filter(resolved=False).select_related("source_color"))
    return render(request,"core/_sale_saved_final.html",{"line":line,"pending":pending,"colors":Color.objects.filter(active=True),"result":result})


@login_required
@require_POST
def shortage_resolve(request,shortage_id):
    shortage=get_object_or_404(SaleShortage.objects.select_related("sale_line"),id=shortage_id); choice=request.POST.get("target_color"); keep_negative=choice=="none"; target=None
    if choice and choice!="none": target=get_object_or_404(Color,id=choice)
    line=shortage.sale_line; resolve_shortage(shortage,target_color=target,keep_negative=keep_negative); pending=list(line.shortages.filter(resolved=False).select_related("source_color"))
    return render(request,"core/_sale_saved_final.html",{"line":line,"pending":pending,"colors":Color.objects.filter(active=True),"result":{"transferred":0}})


@login_required
def inventory(request):
    brands=Brand.objects.filter(active=True); brand=brands.filter(id=request.GET.get("brand")).first() if request.GET.get("brand") else brands.filter(name="دارما").first() or brands.first(); sizes=_brand_sizes(brand); rows=[]
    if brand:
        for color in Color.objects.filter(active=True):
            cells=[]
            for size in sizes:
                qs=StockBalance.objects.filter(brand=brand,size=size,color=color); home=qs.filter(location__key=StockLocation.HOME).aggregate(v=Sum("qty"))["v"] or 0; kh=qs.filter(location__key=StockLocation.KHORSHID).aggregate(v=Sum("qty"))["v"] or 0; cells.append({"size":size,"home":home,"kh":kh,"total":home+kh})
            rows.append({"color":color,"cells":cells})
    return render(request,"core/inventory_final.html",{"brands":brands,"brand":brand,"sizes":sizes,"rows":rows})


@login_required
def inventory_operations(request):
    brands=Brand.objects.filter(active=True); sizes=Size.objects.all(); colors=Color.objects.filter(active=True); locations=StockLocation.objects.all()
    if request.method=="POST":
        try:
            if request.POST.get("action")=="transfer":
                obj=StockTransfer.objects.create(date=_date(request.POST.get("date")),brand_id=request.POST.get("brand"),size_id=request.POST.get("size"),color_id=request.POST.get("color"),qty=max(1,_int(request.POST.get("qty"),1)),from_location_id=request.POST.get("from_location"),to_location_id=request.POST.get("to_location"),note=request.POST.get("note",""))
                if obj.from_location_id==obj.to_location_id: obj.delete(); raise ValueError("مبدا و مقصد نمی‌تواند یکی باشد.")
                sync_stock_transfer(obj); messages.success(request,"انتقال موجودی ثبت شد.")
            else:
                obj=InventoryAdjustment.objects.create(date=_date(request.POST.get("date")),brand_id=request.POST.get("brand"),size_id=request.POST.get("size"),color_id=request.POST.get("color"),location_id=request.POST.get("location"),delta=_int(request.POST.get("delta")),note=request.POST.get("note",""))
                if obj.delta==0: obj.delete(); raise ValueError("مقدار اصلاح نمی‌تواند صفر باشد.")
                sync_inventory_adjustment(obj); messages.success(request,"اصلاح موجودی ثبت شد.")
        except Exception as exc: messages.error(request,str(exc))
        return redirect("inventory_operations")
    recent=InventoryMovement.objects.select_related("brand","size","color","location").order_by("-id")[:50]
    return render(request,"core/inventory_operations.html",{"brands":brands,"sizes":sizes,"colors":colors,"locations":locations,"recent":recent,"today_j":_today_j()})


@login_required
def takvin(request):
    sizes=Size.objects.exclude(name__in=["3XL","4XL"]); colors=Color.objects.filter(active=True)
    if request.method=="POST":
        try:
            if request.POST.get("action")=="purchase_batch":
                d=_date(request.POST.get("date")); size_id=request.POST.get("size"); list_price=max(0,_int(request.POST.get("list_unit_price"))); discount=_dec(request.POST.get("discount_percent"),"10"); note=request.POST.get("note",""); created=0
                for color in colors:
                    qty=max(0,_int(request.POST.get(f"qty_{color.id}")))
                    if qty:
                        obj=TakvinPurchase.objects.create(date=d,size_id=size_id,color=color,qty=qty,list_unit_price=list_price,discount_percent=discount,note=note); sync_takvin_purchase(obj); created+=1
                if not created: raise ValueError("حداقل برای یک رنگ تعداد وارد کن.")
                messages.success(request,f"خرید تکوین برای {created} رنگ ثبت شد.")
            else:
                obj=TakvinPayment.objects.create(date=_date(request.POST.get("date")),amount=max(1,_int(request.POST.get("amount"),1)),note=request.POST.get("note","")); sync_takvin_payment(obj); messages.success(request,"پرداخت تکوین ثبت شد.")
        except Exception as exc: messages.error(request,str(exc))
        return redirect("takvin")
    return render(request,"core/takvin.html",{"sizes":sizes,"colors":colors,"purchases":TakvinPurchase.objects.select_related("size","color")[:40],"takvin_balance":account_balance(Account.TAKVIN),"today_j":_today_j(),"default_discount":setting_decimal("takvin_discount_percent",10)})


@login_required
def materials(request):
    colors=Color.objects.filter(active=True); elastics=ElasticBalance.objects.all()
    if request.method=="POST":
        try:
            action=request.POST.get("action")
            if action=="fabric_add":
                roll=FabricRoll.objects.create(code=(request.POST.get("code") or "").strip(),color_id=request.POST.get("color"),purchase_date=_date(request.POST.get("date")),weight_kg=_dec(request.POST.get("weight_kg")),price_per_kg=max(0,_int(request.POST.get("price_per_kg"))),supplier_name=(request.POST.get("supplier_name") or "").strip(),paid_from_mellat=bool(request.POST.get("paid_from_mellat")),note=request.POST.get("note","")); sync_fabric_roll(roll); messages.success(request,"طاقه پارچه ثبت شد.")
            elif action=="fabric_move":
                roll=get_object_or_404(FabricRoll,id=request.POST.get("roll")); roll.location=request.POST.get("location"); roll.save(update_fields=["location"]); messages.success(request,"محل پارچه تغییر کرد.")
            else:
                elastic=get_object_or_404(ElasticBalance,id=request.POST.get("elastic")); movement=ElasticMovement.objects.create(date=_date(request.POST.get("date")),elastic=elastic,kind=request.POST.get("kind"),qty_kg=_dec(request.POST.get("qty_kg")),unit_cost=max(0,_int(request.POST.get("unit_cost"))),note=request.POST.get("note","")); sync_elastic_movement(movement); messages.success(request,"گردش کش ثبت شد.")
        except Exception as exc: messages.error(request,str(exc))
        return redirect("materials")
    return render(request,"core/materials.html",{"colors":colors,"rolls":FabricRoll.objects.select_related("color").all(),"elastics":elastics,"today_j":_today_j(),"raw_value":raw_material_value()})


@login_required
def production(request):
    batches=list(ProductionBatch.objects.select_related("fabric_roll").prefetch_related("receipts__size","receipts__color","receipts__destination")[:60]); sizes=Size.objects.all(); colors=Color.objects.filter(active=True); locations=StockLocation.objects.all(); available_rolls=FabricRoll.objects.exclude(location=FabricRoll.CONSUMED)
    if request.method=="POST":
        try:
            action=request.POST.get("action")
            if action=="batch":
                batch=ProductionBatch.objects.create(code=(request.POST.get("code") or "").strip(),fabric_roll_id=request.POST.get("fabric_roll") or None,cut_date=_date(request.POST.get("date")),expected_qty=max(0,_int(request.POST.get("expected_qty"))),elastic16_used_kg=_dec(request.POST.get("elastic16_used_kg")),elastic25_used_kg=_dec(request.POST.get("elastic25_used_kg")),elastic16_unit_cost=max(0,_int(request.POST.get("elastic16_unit_cost"))),elastic25_unit_cost=max(0,_int(request.POST.get("elastic25_unit_cost"))),note=request.POST.get("note","")); prepare_batch(batch); messages.success(request,"صورت برش/بچ تولید ثبت شد.")
            elif action=="receipt":
                receipt=ProductionReceipt.objects.create(batch_id=request.POST.get("batch"),date=_date(request.POST.get("date")),size_id=request.POST.get("size"),color_id=request.POST.get("color"),qty=max(1,_int(request.POST.get("qty"),1)),destination_id=request.POST.get("destination"),note=request.POST.get("note","")); sync_production_receipt(receipt); messages.success(request,"تحویل محصول از پدرام ثبت و به موجودی اضافه شد.")
            else:
                batch=get_object_or_404(ProductionBatch,id=request.POST.get("batch")); close_batch(batch); messages.success(request,"بچ بسته شد و پارچه مصرف‌شده ثبت شد.")
        except Exception as exc: messages.error(request,str(exc))
        return redirect("production")
    batch_rows=[{"obj":b,"metrics":production_batch_metrics(b)} for b in batches]
    return render(request,"core/production.html",{"batches":batch_rows,"sizes":sizes,"colors":colors,"locations":locations,"available_rolls":available_rolls,"today_j":_today_j(),"pedram_balance":account_balance(Account.PEDRAM),"e16":ElasticBalance.objects.filter(name="16cm").first(),"e25":ElasticBalance.objects.filter(name="25cm").first()})


@login_required
def finance(request):
    accounts={a.key:a for a in Account.objects.all()}
    if request.method=="POST":
        try:
            action=request.POST.get("action")
            if action=="settlement":
                obj=DigikalaSettlement.objects.create(date=_date(request.POST.get("date")),amount=max(1,_int(request.POST.get("amount"),1)),note=request.POST.get("note","")); sync_digikala_settlement(obj); messages.success(request,"واریزی دیجی‌کالا ثبت شد.")
            elif action=="transfer":
                src=get_object_or_404(Account,id=request.POST.get("from_account")); dst=get_object_or_404(Account,id=request.POST.get("to_account"))
                if {src.key,dst.key}!={Account.MELAT,Account.MOFID}: raise ValueError("مفید فقط برای انتقال سرمایه با ملت استفاده می‌شود.")
                obj=BankTransfer.objects.create(date=_date(request.POST.get("date")),amount=max(1,_int(request.POST.get("amount"),1)),from_account=src,to_account=dst,note=request.POST.get("note","")); sync_bank_transfer(obj); messages.success(request,"انتقال ملت/مفید ثبت شد.")
            elif action=="pedram":
                obj=PedramPayment.objects.create(date=_date(request.POST.get("date")),amount=max(1,_int(request.POST.get("amount"),1)),note=request.POST.get("note","")); sync_pedram_payment(obj); messages.success(request,"پرداخت به پدرام ثبت شد.")
            elif action=="supplier_payment":
                supplier=get_object_or_404(SupplierAccount,id=request.POST.get("supplier")); amount=max(1,_int(request.POST.get("amount"),1)); d=_date(request.POST.get("date")); AccountEntry.objects.create(account=accounts[Account.MELAT],date=d,delta=-amount,title=f"پرداخت به {supplier.name}",entry_type="supplier_payment"); SupplierEntry.objects.create(date=d,supplier=supplier,delta=-amount,title="پرداخت به تامین‌کننده"); messages.success(request,"پرداخت تامین‌کننده ثبت شد.")
        except Exception as exc: messages.error(request,str(exc))
        return redirect("finance")
    balances={key:account_balance(acc) for key,acc in accounts.items()}; supplier_rows=[{"obj":s,"balance":supplier_balance(s)} for s in SupplierAccount.objects.filter(active=True)]
    return render(request,"core/finance.html",{"accounts":accounts,"balances":balances,"recent":AccountEntry.objects.select_related("account")[:80],"supplier_rows":supplier_rows,"today_j":_today_j()})


@login_required
def expenses(request):
    if request.method=="POST":
        try:
            if request.POST.get("action")=="category": ExpenseCategory.objects.get_or_create(name=(request.POST.get("name") or "").strip()); messages.success(request,"دسته هزینه اضافه شد.")
            else:
                obj=Expense.objects.create(date=_date(request.POST.get("date")),category_id=request.POST.get("category"),amount=max(1,_int(request.POST.get("amount"),1)),title=(request.POST.get("title") or "").strip(),note=request.POST.get("note","")); sync_expense(obj); messages.success(request,"خرج از حساب ملت ثبت شد.")
        except Exception as exc: messages.error(request,str(exc))
        return redirect("expenses")
    tj=jdatetime.date.fromgregorian(date=date.today()); start=jdatetime.date(tj.year,tj.month,1).togregorian(); total_month=Expense.objects.filter(date__gte=start,date__lte=date.today()).aggregate(v=Sum("amount"))["v"] or 0
    return render(request,"core/expenses.html",{"categories":ExpenseCategory.objects.filter(active=True),"rows":Expense.objects.select_related("category")[:100],"total_month":total_month,"today_j":_today_j()})


@login_required
def assets(request):
    if request.method=="POST":
        obj_id=request.POST.get("id"); name=(request.POST.get("name") or "").strip(); value=max(0,_int(request.POST.get("value")))
        if obj_id:
            obj=get_object_or_404(SideAsset,id=obj_id); obj.name=name; obj.value=value; obj.note=request.POST.get("note",""); obj.active=True; obj.save()
        else: SideAsset.objects.create(name=name,value=value,note=request.POST.get("note",""))
        messages.success(request,"دارایی حاشیه‌ای ذخیره شد."); return redirect("assets")
    rows=SideAsset.objects.all(); total=rows.filter(active=True).aggregate(v=Sum("value"))["v"] or 0; return render(request,"core/assets.html",{"rows":rows,"total":total})


@login_required
def returns(request):
    product_sizes=ProductSize.objects.filter(active=True,product__active=True).select_related("product__brand","product","size")
    if request.method=="POST":
        try:
            obj=ReturnRecord.objects.create(date=_date(request.POST.get("date")),product_size_id=request.POST.get("product_size"),qty=max(1,_int(request.POST.get("qty"),1)),refund_amount=max(0,_int(request.POST.get("refund_amount"))),add_back_inventory=bool(request.POST.get("add_back_inventory")),note=request.POST.get("note","")); sync_return(obj); messages.success(request,"صورت مرجوعی ثبت شد.")
        except Exception as exc: messages.error(request,str(exc))
        return redirect("returns")
    return render(request,"core/returns.html",{"product_sizes":product_sizes,"rows":ReturnRecord.objects.select_related("product_size__product__brand","product_size__product","product_size__size")[:60],"today_j":_today_j()})


def _report_range(request):
    period=request.GET.get("period","month"); tj=jdatetime.date.fromgregorian(date=date.today())
    if period=="today": start=end=date.today()
    elif period=="week": start=date.today()-timedelta(days=(date.today().weekday()+2)%7); end=date.today()
    elif period=="last_month":
        y,m=(tj.year-1,12) if tj.month==1 else (tj.year,tj.month-1); start=jdatetime.date(y,m,1).togregorian(); end=jdatetime.date(tj.year,tj.month,1).togregorian()-timedelta(days=1)
    elif period=="3m": start=date.today()-timedelta(days=90); end=date.today()
    elif period=="year": start=jdatetime.date(tj.year,1,1).togregorian(); end=date.today()
    elif period=="custom": start=_date(request.GET.get("start")); end=_date(request.GET.get("end"))
    else: start=jdatetime.date(tj.year,tj.month,1).togregorian(); end=date.today()
    return (period,start,end) if start<=end else (period,end,start)


@login_required
def report(request):
    period,start,end=_report_range(request); lines=list(SaleLine.objects.filter(day__date__gte=start,day__date__lte=end,quantity__gt=0).select_related("day","product_size__product__brand","product_size__product","product_size__size")); total={"gross":0,"digikala_fee":0,"cogs":0,"profit":0,"shorts":0,"packs":0}; brands=defaultdict(lambda:{"gross":0,"digikala_fee":0,"cogs":0,"profit":0,"shorts":0,"packs":0}); products=defaultdict(lambda:{"gross":0,"profit":0,"packs":0,"shorts":0}); sizes=defaultdict(lambda:{"gross":0,"packs":0,"shorts":0}); colors=defaultdict(int); daily=defaultdict(lambda:{"gross":0,"profit":0})
    for line in lines:
        m=sale_line_metrics(line); b=line.product_size.product.brand.name; p=f"{b} / {line.product_size.product.code}"; s=line.product_size.size.name
        for k in total: total[k]+=m[k]
        for k in brands[b]: brands[b][k]+=m[k]
        for k in products[p]: products[p][k]+=m[k]
        sizes[s]["gross"]+=m["gross"]; sizes[s]["packs"]+=m["packs"]; sizes[s]["shorts"]+=m["shorts"]; daily[line.day.date]["gross"]+=m["gross"]; daily[line.day.date]["profit"]+=m["profit"]
        for comp in line.product_size.product.composition.select_related("color").all(): colors[comp.color.name]+=int(comp.qty)*int(line.quantity)
    total["margin"]=total["profit"]/total["gross"]*100 if total["gross"] else 0
    for v in brands.values(): v["margin"]=v["profit"]/v["gross"]*100 if v["gross"] else 0
    expenses_total=Expense.objects.filter(date__gte=start,date__lte=end).aggregate(v=Sum("amount"))["v"] or 0; after_expenses=total["profit"]-expenses_total
    span=(end-start).days+1; prev_end=start-timedelta(days=1); prev_start=prev_end-timedelta(days=span-1); prev_profit=0; prev_gross=0
    for line in SaleLine.objects.filter(day__date__gte=prev_start,day__date__lte=prev_end,quantity__gt=0).select_related("product_size__product","product_size__size"):
        m=sale_line_metrics(line); prev_profit+=m["profit"]; prev_gross+=m["gross"]
    sales_change=((total["gross"]-prev_gross)/prev_gross*100) if prev_gross else None; profit_change=((total["profit"]-prev_profit)/prev_profit*100) if prev_profit else None
    account_balances={a.key:account_balance(a) for a in Account.objects.all()}; finished=finished_inventory_value(); raw=raw_material_value(); pedram=account_balances.get(Account.PEDRAM,0); takvin_debt=max(0,account_balances.get(Account.TAKVIN,0)); supplier_debt=sum(max(0,supplier_balance(s)) for s in SupplierAccount.objects.filter(active=True)); operational_capital=account_balances.get(Account.MELAT,0)+account_balances.get(Account.MOFID,0)+account_balances.get(Account.DIGIKALA,0)+max(0,pedram)+finished+raw-takvin_debt-max(0,-pedram)-supplier_debt; side_assets=SideAsset.objects.filter(active=True).aggregate(v=Sum("value"))["v"] or 0
    daily_points=sorted(daily.items())
    return render(request,"core/report_final.html",{"period":period,"start":format_jalali(start),"end":format_jalali(end),"total":total,"brands":sorted(brands.items()),"expenses_total":expenses_total,"after_expenses":after_expenses,"sales_change":sales_change,"profit_change":profit_change,"account_balances":account_balances,"finished_value":finished,"raw_value":raw,"operational_capital":operational_capital,"side_assets":side_assets,"total_wealth":operational_capital+side_assets,"supplier_debt":supplier_debt,"top_products":sorted(products.items(),key=lambda x:x[1]["gross"],reverse=True)[:12],"top_profit":sorted(products.items(),key=lambda x:x[1]["profit"],reverse=True)[:12],"size_rows":sorted(sizes.items(),key=lambda x:x[1]["gross"],reverse=True),"color_rows":sorted(colors.items(),key=lambda x:x[1],reverse=True),"chart_labels":json.dumps([format_jalali(d) for d,_ in daily_points],ensure_ascii=False),"chart_sales":json.dumps([v["gross"] for _,v in daily_points]),"chart_profit":json.dumps([v["profit"] for _,v in daily_points])})
