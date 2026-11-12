"""Darma-style DigiKala daily worksheet.

The landing page deliberately contains *only* same-day sales workflow:
multi-XLSX upload, day metrics, brand/size/model sold and exact marketplace
fee/COGS/claim/profit. Cross-platform analytics live in Finance, never here.
"""
from collections import Counter,defaultdict
from urllib.parse import quote
from .app import ROOT,e,fmt
from .effective_costs import today,valid_date
from .master_v2_ui import page_with_style

SIZE_ORDER={"M":0,"L":1,"XL":2,"XXL":3,"2XL":3,"3XL":4,"XXXL":4,
            "36-38":0,"38-40":1,"40-42":2,"42-44":3,"44-46":4}

def _sold_rows(conn,day):
    """Historically posted cost/fee; live category/size and physical components."""
    sql="""SELECT s.*,p.title,p.category AS market_category,p.master_id,
                  m.category AS brand,m.size AS master_size,m.color AS master_color
             FROM sales s JOIN products p ON p.variant_id=s.variant_id
             LEFT JOIN master_products m ON m.id=p.master_id
             WHERE s.sale_date=? ORDER BY p.category,p.title,s.source"""
    from .digikala_auto_link import parts_for
    rows=[]
    for item in conn.execute(sql,(day,)):
        r=dict(item)
        qty=int(r["qty"])
        component_ids=parts_for(conn,r["variant_id"],r["master_id"]) if r["master_id"] is not None else []
        color_counts=Counter()
        size_counts=Counter()
        brand_counts=Counter()
        each_units=0
        for mid,n in component_ids:
            sku=conn.execute("SELECT category,size,color FROM master_products WHERE id=?",(mid,)).fetchone()
            if not sku:continue
            amount=int(n);each_units+=amount
            color_counts[sku["color"]]+=amount
            size_counts[sku["size"]]+=amount
            brand_counts[sku["category"]]+=amount
        brand=(brand_counts.most_common(1)[0][0] if brand_counts else r["brand"] or r["market_category"])
        size=(size_counts.most_common(1)[0][0] if size_counts else r["master_size"] or "—")
        colors="، ".join(f"{name} × {n}" for name,n in color_counts.items())
        if not colors:colors=r["master_color"] or "ترکیب رنگ تعریف نشده"
        gross=qty*int(r["price_toman"])
        fee=qty*int(r["fee_toman"])
        cogs=qty*int(r["cost_toman"]) if r["cost_toman"] is not None else None
        rows.append({"brand":brand,"size":size,"colors":colors,
                     "title":r["title"],"code":r["variant_id"],
                     "source":r["source"],"qty":qty,"units":qty*(each_units or 1),
                     "unit_price":r["price_toman"],"gross":gross,"fee":fee,
                     "cogs":cogs,"net":gross-fee,
                     "profit":gross-fee-cogs if cogs is not None else None})
    return rows

def _summary(rows):
    result={"packs":0,"units":0,"gross":0,"fee":0,"net":0,
            "cogs_known":0,"unknown":0,"profit":None}
    for r in rows:
        result["packs"]+=r["qty"];result["units"]+=r["units"]
        result["gross"]+=r["gross"];result["fee"]+=r["fee"]
        result["net"]+=r["net"]
        if r["cogs"] is None:result["unknown"]+=1
        else:result["cogs_known"]+=r["cogs"]
    if not result["unknown"]:result["profit"]=result["net"]-result["cogs_known"]
    return result

def _money(value):
    return "نامشخص" if value is None else fmt(value)

def _source_label(source):
    return {"seller":"خانه","khorshid":"خورشید","digikala":"انبار دیجی‌کالا"}.get(source,source)

def _file_form(day,source="seller"):
    body='<section class="m2-card m2-dk-upload">'
    body+='<div class="m2-dk-upload-head"><div><span class="m2-unit">ورود خودکار سفارش روزانه</span><h3>بارگذاری اکسل دیجی‌کالا</h3>'
    body+='<p class="m2-hint">اگر یک روز دو یا چند محموله داری، همه فایل‌های XLSX آن روز را هم‌زمان انتخاب کن. فایل‌ها تجمیع می‌شوند و یک صورت کامل می‌سازند.</p></div></div>'
    body+=f'<form action="{ROOT}/preview" enctype="multipart/form-data" method="post" class="m2-dk-upload-form">'
    body+=f'<div><label>تاریخ فروش</label><input type="date" name="sale_date" value="{e(day)}" required></div>'
    body+='<div><label>موجودی از کدام انبار کم شود؟</label><select name="source">'
    for code,label in (("seller","خانه"),("khorshid","خورشید")):
        body+=f'<option value="{code}"'+(" selected" if code==source else "")+f'>{label}</option>'
    body+='</select></div>'
    body+='<div class="m2-dk-upload-input"><label>فایل‌های اکسل (امکان انتخاب چند فایل)</label><input type="file" name="files" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" multiple required></div>'
    body+='<div><button type="submit" class="m2-btn">بررسی فایل‌ها و نمایش صورت</button></div></form>'
    body+='<small class="m2-hint">بارگذاری ابتدا پیش‌نمایش می‌دهد و هیچ موجودی را تغییر نمی‌دهد. پس از تأیید، صورت این تاریخ و انبار جایگزین صورت قبلی همان روز می‌شود؛ نه اینکه دوباره به آن اضافه شود.</small>'
    body+='</section>'
    return body

def _cards(stats):
    cards=(("فروش کل",_money(stats["gross"]),"تومان"),
           ("سود فروش",_money(stats["profit"]),"تومان"),
           ("هزینه دیجی‌کالا",_money(stats["fee"]),"تومان"),
           ("طلب ایجادشده از دیجی‌کالا",_money(stats["net"]),"تومان · قبل از واریزی‌ها"),
           ("بهای تمام‌شده کالا",_money(stats["cogs_known"]),"تومان · بهای مشخص"),
           ("تعداد فروخته‌شده",fmt(stats["packs"]),f'{fmt(stats["units"])} عدد کالای فیزیکی'))
    body='<div class="m2-dk-summary">'
    for title,value,subtitle in cards:
        body+=f'<div class="m2-card m2-dk-kpi"><small>{e(title)}</small><strong>{e(value)}</strong><span class="m2-unit">{e(subtitle)}</span></div>'
    return body+'</div>'

def _brand_rows(rows):
    groups=defaultdict(list)
    for r in rows:groups[r["brand"]].append(r)
    return groups

def _selected_link(day,brand="",size=""):
    q=f"sale_date={quote(day)}"
    if brand:q+="&brand="+quote(brand)
    if size:q+="&size="+quote(size)
    return ROOT+"/?"+q

def daily_page(conn,sale_date="",brand="",size="",saved=""):
    day=valid_date(sale_date or today())
    sold=_sold_rows(conn,day)
    stats=_summary(sold)
    body='<div class="m2-dk-head"><h1>صورت فروش روزانه دیجی‌کالا</h1>'
    body+='<p class="m2-hint">همان گردش فروش دارما: فایل روز، صورت برندها و سایزها، هزینه کالا، هزینه دیجی‌کالا، سود و طلب ایجادشده.</p></div>'
    body+=_file_form(day)
    if saved=="1":
        body+='<div class="m2-dk-success">صورت روزانه تأیید شد؛ موجودی فیزیکی اصلاح شد و مبلغ خالص فروش به طلب دیجی‌کالا در حسابداری منتقل شد.</div>'
    body+=f'<div class="m2-dk-daybar"><h3>صورت فروش {e(day)}</h3><form method="get" action="{ROOT}/" class="m2-fields">'
    body+=f'<div><label>انتخاب روز</label><input name="sale_date" type="date" value="{e(day)}"></div><div><button type="submit" class="m2-btn">نمایش روز</button></div></form></div>'
    if not sold:
        last=conn.execute("SELECT MAX(sale_date) FROM sales WHERE sale_date<?",(day,)).fetchone()[0]
        body+='<div class="m2-card"><h3>هنوز فروشی برای این روز ثبت نشده است.</h3><p class="m2-hint">برای مشاهده گزارش روز، فایل‌های اکسل را از کادر بالای صفحه بارگذاری و تأیید کن.</p>'
        if last:body+=f'<a href="{_selected_link(last)}">آخرین روز ثبت‌شده: {e(last)}</a>'
        body+='</div>'
        return page_with_style("فروش روزانه دیجی‌کالا",body)
    body+=_cards(stats)
    if stats["unknown"]:
        body+=f'<div class="m2-msg">بهای تمام‌شده {stats["unknown"]} ردیف فروش مشخص نیست؛ سود روز تا تکمیل قیمت تمام‌شده قطعی نیست. مبلغ طلب مستقل از بهای کالا محاسبه شده است.</div>'
    by_brand=_brand_rows(sold)
    body+='<section class="m2-card m2-dk-section"><h3>خلاصه برندهای فروخته‌شده</h3>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>برند</th><th>تعداد بسته</th><th>عدد کالا</th><th>فروش</th><th>هزینه دیجی‌کالا</th><th>بهای کالا</th><th>طلب ایجادشده</th><th>سود</th></tr></thead><tbody>'
    for name,items in sorted(by_brand.items()):
        values=_summary(items)
        body+=f'<tr><th><a href="{_selected_link(day,name)}">{e(name)}</a></th><td>{fmt(values["packs"])}</td><td>{fmt(values["units"])}</td><td>{fmt(values["gross"])}</td><td>{fmt(values["fee"])}</td><td>{_money(values["cogs_known"]) if not values["unknown"] else "نامشخص"}</td><td>{fmt(values["net"])}</td><td>{_money(values["profit"])}</td></tr>'
    body+='</tbody></table></div></section>'
    if brand not in by_brand:brand=""
    current=by_brand[brand] if brand else sold
    sizes=sorted({r["size"] for r in current},key=lambda x:(SIZE_ORDER.get(x,99),x))
    if size not in sizes:size=""
    visible=[r for r in current if not size or r["size"]==size]
    body+='<section class="m2-card m2-dk-section"><h3>مدل‌ها و سایزهای فروخته‌شده</h3><p class="m2-hint">ابتدا برند و سپس سایز را انتخاب کن.</p>'
    body+='<div class="m2-dk-brand-filter">'
    body+=f'<a class="{"active" if not brand else ""}" href="{_selected_link(day)}">همه برندها · {fmt(stats["packs"])}</a>'
    for name,items in sorted(by_brand.items()):
        body+=f'<a class="{"active" if name==brand else ""}" href="{_selected_link(day,name)}">{e(name)} · {fmt(sum(i["qty"] for i in items))}</a>'
    body+='</div>'
    body+='<div class="m2-dk-size-filter">'
    body+=f'<a class="{"active" if not size else ""}" href="{_selected_link(day,brand)}">همه سایزها</a>'
    for s in sizes:
        body+=f'<a class="{"active" if s==size else ""}" href="{_selected_link(day,brand,s)}">{e(s)}</a>'
    body+='</div>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>مدل / رنگ</th><th>برند / سایز</th><th>تعداد بسته / عدد</th><th>قیمت واحد</th><th>فروش</th><th>دیجی‌کالا</th><th>بهای کالا</th><th>طلب ایجادشده</th><th>سود</th></tr></thead><tbody>'
    for r in visible:
        body+=(f'<tr><th><strong>{e(r["title"])}</strong>'
               f'<div class="m2-dk-color">{e(r["colors"])}</div>'
               f'<div class="m2-dk-code">کد تنوع: {r["code"]} · انبار {_source_label(r["source"])}</div></th>'
               f'<td>{e(r["brand"])} / {e(r["size"])}</td>'
               f'<td>{fmt(r["qty"])} بسته · {fmt(r["units"])} عدد</td>'
               f'<td>{fmt(r["unit_price"])}</td><td>{fmt(r["gross"])}</td>'
               f'<td>{fmt(r["fee"])}</td><td>{_money(r["cogs"])}</td>'
               f'<td>{fmt(r["net"])}</td><td>{_money(r["profit"])}</td></tr>')
    body+='</tbody></table></div></section>'
    body+='<p class="m2-hint">طلب روز حاصل فروش منهای کارمزد دیجی‌کالا است. این طلب در بخش حسابداری با واریزی‌ها تسویه می‌شود. سود برابر طلب ایجادشده منهای بهای تمام‌شده است.</p>'
    return page_with_style("فروش روزانه دیجی‌کالا",body)

def preview_page(data):
    rows=data["rows"]
    gross=sum(int(r["qty"])*int(r["price"]) for r in rows)
    fees=sum(int(r["qty"])*int(r["fee"]) for r in rows)
    known=sum(int(r["qty"])*int(r["cost"]) for r in rows if r["cost"] is not None)
    unknown=sum(1 for r in rows if r["cost"] is None)
    profit=None if unknown else gross-fees-known
    body='<h1>پیش‌نمایش صورت دیجی‌کالا</h1><p class="m2-hint">هنوز هیچ فروشی ثبت و هیچ موجودی کم نشده است. قبل از تأیید، سطرهای تجمیع‌شده را کنترل کن.</p>'
    body+=f'<p class="m2-hint">{e(data["sale_date"])} · {data["files_count"]} فایل اکسل · انبار {_source_label(data["source"])} · {data["ignored"]} ردیف کنار گذاشته‌شده</p>'
    body+=_cards({"gross":gross,"fee":fees,"net":gross-fees,"profit":profit,"cogs_known":known,
                 "packs":sum(int(x["qty"]) for x in rows),
                 "units":sum(int(x["qty"]) * max(1,len(x.get("parts_signature",[]))) for x in rows)})
    if data["fallback_prices"]:
        body+=f'<div class="m2-msg">قیمت فروش {data["fallback_prices"]} ردیف از قیمت کاتالوگ خوانده شده است؛ با قیمت واقعی فایل مقایسه کن.</div>'
    if unknown:
        body+=f'<div class="m2-msg">{unknown} ردیف بهای تمام‌شده ندارد و سود قطعی آن‌ها هنوز نامشخص است.</div>'
    body+='<section class="m2-card m2-dk-section"><h3>ردیف‌های تجمیع‌شده از اکسل‌ها</h3>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>کد تنوع</th><th>مدل</th><th>برند</th><th>بسته</th><th>قیمت واحد</th><th>فروش</th><th>دیجی‌کالا</th><th>بهای کالا</th><th>طلب</th><th>سود</th></tr></thead><tbody>'
    for r in rows:
        qty=int(r["qty"]);gross_row=qty*int(r["price"]);fee_row=qty*int(r["fee"])
        cogs_row=qty*int(r["cost"]) if r["cost"] is not None else None
        body+=f'<tr><th>{e(r["variant_id"])}</th><td>{e(r["title"])}</td><td>{e(r["category"])}</td><td>{fmt(qty)}</td><td>{fmt(r["price"])}</td><td>{fmt(gross_row)}</td><td>{fmt(fee_row)}</td><td>{_money(cogs_row)}</td><td>{fmt(gross_row-fee_row)}</td><td>{_money(gross_row-fee_row-cogs_row if cogs_row is not None else None)}</td></tr>'
    body+='</tbody></table></div></section>'
    if rows:
        body+=f'<form action="{ROOT}/commit" method="post" class="m2-dk-confirm"><input name="token" type="hidden" value="{e(data["token"])}"><button class="m2-btn" type="submit">تأیید نهایی صورت، کسر موجودی و ثبت طلب دیجی‌کالا</button></form>'
    body+=f'<a class="m2-dk-back" href="{ROOT}/?sale_date={quote(data["sale_date"])}">بازگشت به فروش روزانه</a>'
    return page_with_style("پیش‌نمایش فروش دیجی‌کالا",body)
