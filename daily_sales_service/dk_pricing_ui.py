"""Compact dated price management for all 538 DigiKala listings.

Category -> Bodyguard subtype -> paginated listing rows -> bulk effective-date save.
No writes to marketplace catalog identities, earlier posted sales or stock.
"""
from urllib.parse import urlencode
from fastapi import APIRouter,Depends,Form,Request
from fastapi.responses import RedirectResponse

from .app import ROOT,conn_dep,e,fmt
from .engine import ImportErrorDetail
from .effective_costs import today,valid_date
from .master_v2_ui import page_with_style
from .master_engine import CATEGORIES,_daily_digikala_price
from .digikala_auto_link import category_for
from .dk_dated_prices import save_dated_prices,effective_price
from .calendar_jalali import picker as date_picker,ASSETS as CALENDAR_ASSETS

router=APIRouter()
SIZES=(("بادیگارد","شورت مردانه بادیگارد"),("شورت زنانه دارما","شورت زنانه دارما"),
       ("شورت زنانه دیا","شورت زنانه دیا"),("زیرپوش دارما","زیرپوش"),
       ("قالب","قالب کفش"),("سایر","سایر کدهای دیجی‌کالا"))
LABELS=dict(SIZES)

def family(row):
    if row["master_category"] in CATEGORIES:
        cat=row["master_category"]
        subtype=row["master_subtype"] or ""
    else:
        cat,subtype=category_for(row["category"],row["title"])
        if not cat:
            title=str(row["title"])
            if "دیا" in title and "زنانه" in title:cat="شورت زنانه دیا"
            elif "دارما" in title and "زنانه" in title:cat="شورت زنانه دارما"
            else:cat="سایر"
    if cat=="بادیگارد" and subtype not in ("اسلیپ","پادار"):
        title=str(row["title"])
        if "اسلیپ" in title and "پادار" not in title:subtype="اسلیپ"
        elif "پادار" in title and "اسلیپ" not in title:subtype="پادار"
        else:subtype="نامشخص"
    return cat,subtype

def records(conn):
    return conn.execute("""SELECT p.*,m.category master_category,m.subtype master_subtype,
        m.sale_price_toman master_sale_price,
        d.archived,d.display_title,d.display_price_toman
        FROM products p
        LEFT JOIN master_products m ON m.id=p.master_id
        LEFT JOIN dk_catalog_preferences d ON d.variant_id=p.variant_id
        WHERE p.active=1 AND COALESCE(d.archived,0)=0
        ORDER BY p.category,p.title,p.variant_id""").fetchall()

def link(category,subtype="",page=1,as_of=""):
    return ROOT+"/pricing/digikala?"+urlencode(
        {"category":category,"subtype":subtype,"page_no":page,"as_of":as_of})

@router.get(ROOT+"/pricing/digikala")
def digikala_pricing(category:str="",subtype:str="",page_no:int=1,as_of:str="",saved:int=0,
                     conn=Depends(conn_dep)):
    day=valid_date(as_of or today())
    classified=[(row,*family(row)) for row in records(conn)]
    counts={key:sum(1 for _,cat,_ in classified if cat==key) for key,_ in SIZES}
    if category not in LABELS:category=""
    body='<h1>قیمت‌گذاری دیجی‌کالا</h1>'
    body+='<p class="m2-hint">قیمت هر کد تنوع، قیمت کل همان بسته در دیجی‌کالاست. نرخ را همراه تاریخ شروع ثبت کن؛ فروش‌های تأییدشده قبلی تغییر نمی‌کنند.</p>'
    body+='<div class="m2-cards" style="margin:18px 0">'
    for key,name in SIZES:
        body+=f'<a class="m2-card" href="{e(link(key,as_of=day))}" style="text-decoration:none;border-color:{"#ed8b44" if category==key else "#355572"}"><h3>{e(name)}</h3><span class="m2-unit">{fmt(counts[key])} کد فعال</span></a>'
    body+='</div>'
    if saved:body+='<div class="m2-dk-success">قیمت‌های تاریخ‌دار ثبت شدند؛ از تاریخ اجرا در فایل فروش روزانه استفاده خواهند شد.</div>'
    if not category:
        body+='<p class="m2-hint">برای دیدن لیست قیمت‌ها، یکی از دسته‌های بالا را انتخاب کن.</p>'
        return page_with_style("قیمت‌گذاری دیجی‌کالا",body)
    if category=="بادیگارد":
        body+='<div class="m2-tabs">'
        for key,name in (("اسلیپ","اسلیپ"),("پادار","پادار"),("نامشخص","نوع نامشخص")):
            target=link(category,key,as_of=day)
            body+=f'<a class="{"current" if subtype==key else ""}" href="{e(target)}">{e(name)}</a>'
        body+='</div>'
        if subtype not in ("اسلیپ","پادار","نامشخص"):
            body+='<p class="m2-hint">ابتدا نوع شورت مردانه را انتخاب کن: اسلیپ یا پادار.</p>'
            return page_with_style("قیمت‌گذاری دیجی‌کالا",body)
    selected=[row for row,cat,kind in classified if cat==category and
              (category!="بادیگارد" or kind==subtype)]
    per_page=40;page=max(1,min(page_no,max(1,(len(selected)+per_page-1)//per_page)))
    current=selected[(page-1)*per_page:page*per_page]
    body+=f'<div class="m2-card"><h3>{e(LABELS[category])}'+(f' / {e(subtype)}' if subtype else '')+'</h3>'
    body+=f'<p class="m2-hint">تعداد {fmt(len(selected))} کد · صفحه {fmt(page)}. فقط ردیف‌هایی که قیمت وارد کرده‌ای ذخیره می‌شوند.</p>'
    body+=f'<form method="get" action="{ROOT}/pricing/digikala" class="m2-fields">'
    body+=f'<input type="hidden" name="category" value="{e(category)}"><input type="hidden" name="subtype" value="{e(subtype)}">'
    body+=f'<div><label>نمایش قیمت در تاریخ</label><input type="date" name="as_of" value="{e(day)}"></div><button class="m2-btn">نمایش</button></form>'
    body+=f'<form method="post" action="{ROOT}/pricing/digikala/save">'
    body+=f'<input type="hidden" name="category" value="{e(category)}"><input type="hidden" name="subtype" value="{e(subtype)}">'
    body+=f'<input type="hidden" name="page_no" value="{page}">'
    body+=f'<div class="m2-fields" style="margin:16px 0"><div><label>شروع اجرای قیمت جدید (شمسی)</label>{date_picker(today(),today())}</div></div>'
    body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>کد تنوع / محصول</th><th>قیمت فعلی (تومان)</th><th>تاریخ آخرین نرخ</th><th>قیمت جدید هر بسته (تومان)</th></tr></thead><tbody>'
    for r in current:
        variant=int(r["variant_id"])
        override=effective_price(conn,variant,day)
        master=(dict(id=r["master_id"],sale_price_toman=r["master_sale_price"])
                if r["master_id"] is not None else None)
        price,source=_daily_digikala_price(conn,r,master,day)
        latest=conn.execute("""SELECT effective_date,price_toman FROM dk_dated_sale_prices
            WHERE variant_id=? ORDER BY effective_date DESC LIMIT 1""",(variant,)).fetchone()
        body+=(f'<tr><th>{variant}<div class="m2-unit" style="white-space:normal;max-width:440px">{e(r["display_title"] or r["title"])}</div></th>'
               f'<td>{fmt(price) if price else "تعریف نشده"}<div class="m2-unit">{e(source)}</div></td>'
               f'<td>{e(latest["effective_date"]) if latest else "نرخ تاریخ‌دار ندارد"}</td>'
               f'<td><input type="number" name="price_{variant}" min="1" step="1" placeholder="قیمت جدید" style="min-width:140px;width:160px"></td></tr>')
    body+='</tbody></table></div><div style="margin-top:17px"><button class="m2-btn" type="submit">ثبت قیمت‌های انتخاب‌شده با تاریخ اجرا</button></div></form>'
    if page>1:body+=f'<a class="m2-btn" href="{e(link(category,subtype,page-1,day))}">صفحه قبل</a> '
    if page*per_page<len(selected):body+=f'<a class="m2-btn" href="{e(link(category,subtype,page+1,day))}">صفحه بعد</a>'
    body+='</div>'
    return page_with_style("قیمت‌گذاری دیجی‌کالا",body+CALENDAR_ASSETS)

@router.post(ROOT+"/pricing/digikala/save")
async def save_prices(request:Request,category:str=Form(""),subtype:str=Form(""),
                      page_no:int=Form(1),conn=Depends(conn_dep)):
    from .app import fail
    try:
        data=await request.form()
        values={}
        for key,value in data.items():
            if key.startswith("price_") and str(value).strip():
                if not key[6:].isdigit():raise ImportErrorDetail("کد تنوع نامعتبر است.")
                values[int(key[6:])]=value
        if not values:raise ImportErrorDetail("حداقل برای یک محصول قیمت وارد کن.")
        # Bound the edit to the current visual category. The client cannot
        # send an arbitrary variant not displayed by this admin view.
        selected={int(row["variant_id"]) for row in records(conn)
                  if (lambda x: x[0]==category and
                      (category!="بادیگارد" or x[1]==subtype))(family(row))}
        if not set(values).issubset(selected):
            raise ImportErrorDetail("کدها با دسته انتخاب‌شده همخوانی ندارند.")
        save_dated_prices(conn,values,str(data.get("sale_date") or ""))
    except (ValueError,ImportErrorDetail) as exc:return fail(exc)
    return RedirectResponse(link(category,subtype,page_no,today())+"&saved=1",status_code=303)
