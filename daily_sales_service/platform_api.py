"""Minimal 4-card platform navigation and SKU-linked selling item catalogue."""
from urllib.parse import quote
from fastapi import APIRouter,Depends,Form
from fastapi.responses import RedirectResponse
from .app import ROOT,conn_dep,e,fmt
from .master_engine import CATEGORIES
from .master_v2_logic import SIZES
from .master_v2_ui import page_with_style
from .platform_catalog import PLATFORMS,SALE_CHANNELS,create_listing,list_listings,book_sale,sale_summary
from .engine import ImportErrorDetail
from .effective_costs import today

router=APIRouter()

def error_page(exc,channel=""):
    return page_with_style("ثبت ناموفق",f'<div class="m2-msg">{e(exc)}</div><a class="m2-btn" href="{ROOT}/platforms/{e(channel)}">بازگشت به پلتفرم</a>' if channel else f'<div class="m2-msg">{e(exc)}</div>')

def cards(selected=""):
    content='<div class="m2-platform-grid">'
    for key,name in PLATFORMS.items():
        content+=f'<a class="m2-platform-card" href="{ROOT}/platforms/{key}" style="text-decoration:none"><span class="m2-platform-dot">{e(name[0])}</span><h3>{e(name)}</h3></a>'
    return content+'</div>'

@router.get(ROOT+"/platforms")
def platforms(conn=Depends(conn_dep)):
    return page_with_style("پلتفرم‌ها",'<h1>پلتفرم‌ها</h1><p class="m2-hint">برای تعریف کالای فروشی، یکی از چهار پلتفرم را انتخاب کن.</p>'+cards())

@router.get(ROOT+"/platforms/{channel}")
def channel_page(channel:str,category:str="",q:str="",conn=Depends(conn_dep)):
    if channel not in PLATFORMS:return error_page("پلتفرم ناشناخته است.")
    if channel=="digikala":
        return RedirectResponse(ROOT+"/catalog",status_code=303)
    if channel=="mold":category="قالب"
    elif category not in CATEGORIES:category=CATEGORIES[0]
    sku_sql="""SELECT id,category,title,subtype,color,size FROM master_products WHERE active=1 AND category=? ORDER BY title,color,size,id"""
    master_skus=[dict(r) for r in conn.execute(sku_sql,(category,))]
    body=f'<div class="m2-hero"><div><h1>{e(PLATFORMS[channel])}</h1><p class="m2-hint">تعریف کالای قابل‌فروش بر مبنای تعریف محصولات و موجودی مشترک</p></div><a href="{ROOT}/platforms">همه پلتفرم‌ها</a></div>'
    body+='<div class="m2-card m2-platform-form"><h3>تعریف محصول</h3>'
    if channel!="mold":
        body+=f'<form action="{ROOT}/platforms/{channel}" method="get" class="m2-inline-filter"><label>دسته‌بندی محصول</label><select name="category" onchange="this.form.submit()">'
        body+=''.join(f'<option value="{e(c)}"'+(' selected' if c==category else '')+'>'+e(c)+'</option>' for c in CATEGORIES)
        body+='</select><button class="m2-btn" type="submit">انتخاب دسته</button></form>'
    body+=f'<form method="post" action="{ROOT}/platforms/{channel}/add" class="m2-fields">'
    body+=f'<input type="hidden" name="category" value="{e(category)}">'
    body+='<div><label>محصول پایه، رنگ و سایز</label><select name="master_id" required>'
    if master_skus:
        body+=''.join(f'<option value="{s["id"]}">{e(s["title"])} · {e(s["subtype"] or s["category"])} · {e(s["color"])} · {e(s["size"])}</option>' for s in master_skus)
    else:body+='<option value="">برای این دسته هنوز کالایی تعریف نشده</option>'
    body+='</select></div>'
    body+='<div><label>تعداد در هر بسته</label><select name="pack_qty">'+''.join(f'<option value="{n}">{n} عددی</option>' for n in range(1,13))+'</select></div>'
    body+='<div><label>عنوان فروش در پلتفرم (اختیاری)</label><input name="title" placeholder="مثلاً پک سه‌عددی شورت زنانه"></div>'
    body+='<div><button class="m2-btn" type="submit"'+(' disabled' if not master_skus else '')+'>ثبت محصول</button></div></form>'
    body+=f'<p class="m2-hint" style="margin-top:12px">قیمت این بسته از قیمت واحد همان محصول در <a href="{ROOT}/pricing/sales?channel={channel}&category={quote(category)}">قیمت‌گذاری {e(PLATFORMS[channel])}</a> × تعداد بسته محاسبه می‌شود؛ موجودی تکراری ایجاد نمی‌شود.</p></div>'
    body+=f'<div class="m2-search-block"><form action="{ROOT}/platforms/{channel}" method="get">'
    body+=f'<input type="hidden" name="category" value="{e(category)}"><input name="q" placeholder="جست‌وجوی نام یا شناسه محصول" value="{e(q)}"><button class="m2-btn">جستجو</button></form></div>'
    rows=list_listings(conn,channel,q,category)
    body+='<div class="m2-card"><h3>فهرست محصولات ثبت‌شده</h3>'
    if rows:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>عنوان محصول</th><th>شناسه پلتفرم</th><th>رنگ / سایز</th><th>بسته</th><th>قیمت</th><th>موجودی کل (عدد)</th><th>وضعیت</th></tr></thead><tbody>'
        for row in rows:
            price=(row["unit_price"]*row["pack_qty"] if row["unit_price"] is not None else None)
            stock=row["seller_stock"]+row["khorshid_stock"]
            body+=f'<tr><th>{e(row["title"])}</th><td>{e(row["listing_code"])}</td><td>{e(row["color"])} / {e(row["size"])}</td><td>{row["pack_qty"]}</td><td>{fmt(price) if price is not None else "قیمت‌گذاری نشده"}</td><td>{fmt(stock)}</td><td>{"فعال" if row["active"] else "غیرفعال"}</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">هنوز محصولی با این فیلتر در این پلتفرم ثبت نشده است.</p>'
    body+='</div>'
    body+=f'<p style="margin-top:20px"><a href="{ROOT}/platforms/{channel}/sales">ورود فروش روزانه {e(PLATFORMS[channel])}</a></p>'
    return page_with_style(PLATFORMS[channel],body)

@router.post(ROOT+"/platforms/{channel}/add")
def add_platform(channel:str,master_id:str=Form(...),title:str=Form(""),pack_qty:int=Form(...),category:str=Form(""),conn=Depends(conn_dep)):
    try:
        # category is UI filter only; SKU itself is authoritative.
        create_listing(conn,channel,master_id,title,pack_qty)
    except (ImportErrorDetail,ValueError) as exc:return error_page(exc,channel)
    return RedirectResponse(ROOT+"/platforms/"+channel+"?category="+quote(category),status_code=303)

@router.get(ROOT+"/platforms/{channel}/sales")
def sales_page(channel:str,conn=Depends(conn_dep)):
    if channel not in SALE_CHANNELS:return error_page("این فروشگاه هنوز برای ثبت دستی آماده نیست.")
    listings=list_listings(conn,channel,max_rows=1000)
    body=f'<h1>فروش روزانه {e(PLATFORMS[channel])}</h1><p class="m2-hint">فروش به محصول ثبت‌شده در پلتفرم متصل است و تعداد بسته × تعداد در هر بسته از انبار فیزیکی کم می‌شود.</p>'
    body+=f'<div class="m2-card"><h3>ثبت فروش</h3><form method="post" action="{ROOT}/platforms/{channel}/sales/add" class="m2-fields">'
    body+='<div><label>تاریخ فروش</label><input type="date" name="sale_date" value="'+today()+'" required></div>'
    body+='<div><label>محصول پلتفرم</label><select name="listing_id">'
    body+=''.join(f'<option value="{x["id"]}">{e(x["title"])} - {x["pack_qty"]} عددی · {e(x["color"])} · {e(x["size"])}</option>' for x in listings if x["active"] and x["master_active"])
    body+='</select></div><div><label>تعداد بسته فروخته‌شده</label><input type="number" min="1" name="packs" value="1" required></div>'
    body+='<div><label>کسر از انبار</label><select name="warehouse"><option value="home">خانه</option><option value="khorshid">خورشید</option></select></div>'
    body+='<div><label>شناسه سفارش (برای جلوگیری از ثبت تکراری)</label><input name="order_ref" placeholder="اختیاری، اما توصیه می‌شود"></div>'
    body+='<div><button class="m2-btn" type="submit">ثبت فروش و کسر موجودی</button></div></form></div>'
    recent=conn.execute("""SELECT s.*,l.title,l.pack_qty FROM platform_sales s JOIN platform_listings l ON l.id=s.listing_id
          WHERE s.channel=? ORDER BY s.id DESC LIMIT 70""",(channel,)).fetchall()
    body+='<div class="m2-card" style="margin-top:18px"><h3>فروش‌های اخیر</h3><div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>تاریخ</th><th>محصول</th><th>بسته</th><th>تعداد فیزیکی</th><th>مبلغ ناخالص</th><th>انبار</th><th>شناسه</th></tr></thead><tbody>'
    for s in recent:
        body+=f'<tr><th>{e(s["sale_date"])}</th><td>{e(s["title"])}</td><td>{fmt(s["packs"])}</td><td>{fmt(s["units"])}</td><td>{fmt(s["gross_toman"])}</td><td>{e("خانه" if s["warehouse"]=="home" else "خورشید")}</td><td>{e(s["external_ref"] or "—")}</td></tr>'
    body+='</tbody></table></div></div>'
    body+='<p class="m2-hint">کارمزد پلتفرم فعلاً تعریف نشده است. سود خالص قطعی تا دریافت ضوابط کمیسیون محاسبه نمی‌شود.</p>'
    return page_with_style("فروش روزانه "+PLATFORMS[channel],body)

@router.post(ROOT+"/platforms/{channel}/sales/add")
def post_sale(channel:str,listing_id:int=Form(...),packs:int=Form(...),warehouse:str=Form(...),sale_date:str=Form(...),order_ref:str=Form(""),conn=Depends(conn_dep)):
    try:book_sale(conn,channel,listing_id,packs,warehouse,sale_date,order_ref)
    except (ImportErrorDetail,ValueError) as exc:return error_page(exc,channel)
    return RedirectResponse(ROOT+"/platforms/"+channel+"/sales",status_code=303)
