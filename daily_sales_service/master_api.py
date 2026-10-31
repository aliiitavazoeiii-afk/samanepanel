"""User-facing pages for the sister's canonical SKU master and DigiKala mappings."""
from html import escape
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from .app import ROOT, conn_dep, e, fail, fmt, notice, page, table, tr
from .engine import ImportErrorDetail
from .master_engine import CATEGORIES, add_master, update_master, adjust_master_stock, map_variant

router=APIRouter()

def options(selected=""):
    return "".join('<option value="'+e(cat)+'"'+(" selected" if cat==selected else "")+'>'+e(cat)+'</option>' for cat in CATEGORIES)

def filter_links(endpoint,category):
    result='<div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0">'
    for cat in ("همه",)+CATEGORIES:
        href=ROOT+endpoint+("?category="+quote(cat) if cat!="همه" else "")
        result+=f'<a class="button" style="padding:6px 10px;background:'+("#d36617" if cat==category else "#19334e")+'" href="'+e(href)+'">'+e(cat)+'</a>'
    return result+'</div>'

def listing_filter(endpoint,q,category):
    return (f'<form method="get" action="{ROOT}{endpoint}" class="forms">'
            f'<div><label>جست‌وجو کد، عنوان، رنگ یا سایز</label><input name="q" value="{e(q)}"></div>'
            f'<div><label>دسته‌بندی</label><select name="category"><option value="">همه دسته‌ها</option>{options(category)}</select></div>'
            '<button type="submit">جست‌وجو</button></form>')

def query_master(conn,category,q,limit=100,offset=0):
    sql="FROM master_products WHERE 1=1"; args=[]
    if category in CATEGORIES:sql+=" AND category=?";args.append(category)
    if q:
        sql+=" AND (code LIKE ? OR title LIKE ? OR size LIKE ? OR color LIKE ?)"
        args.extend(["%"+q+"%"]*4)
    count=conn.execute("SELECT COUNT(*) "+sql,args).fetchone()[0]
    rows=conn.execute("SELECT * "+sql+" ORDER BY category,code,color,size LIMIT ? OFFSET ?",args+[limit,offset]).fetchall()
    return count,rows

@router.get(ROOT+"/master")
def master(category:str="",q:str="",page_no:int=1,conn=Depends(conn_dep)):
    if category not in CATEGORIES:category=""
    page_no=max(1,min(page_no,10000))
    total,rows=query_master(conn,category,q,75,(page_no-1)*75)
    top=(f'<div class="panel"><h3>تعریف کالای جدید</h3>'
         f'<form class="forms" action="{ROOT}/master/add" method="post">'
         f'<div><label>دسته‌بندی</label><select name="category" required>{options(category)}</select></div>'
         '<div><label>کد کالا</label><input name="code" required maxlength="90"></div>'
         '<div><label>عنوان</label><input name="title" required maxlength="220"></div>'
         '<div><label>رنگ</label><input name="color" placeholder="مثلاً مشکی"></div>'
         '<div><label>سایز</label><input name="size" placeholder="مثلاً XL"></div>'
         '<div><label>قیمت فروش (تومان)</label><input type="number" min="0" name="sale_price" value="0"></div>'
         '<div><label>بهای تمام‌شده (تومان)</label><input type="number" min="0" name="cost" placeholder="در صورت نامشخص بودن خالی"></div>'
         '<button type="submit">ثبت محصول</button></form></div>')
    top+=notice('کد + دسته‌بندی + رنگ + سایز، یک کالای فیزیکی مشخص است. موجودی از بخش «موجودی کالا» وارد می‌شود و تعریف محصول به‌خودی‌خود موجودی ایجاد نمی‌کند.')
    top+='<div class="panel"><h3>فیلتر پنج دسته</h3>'+filter_links("/master",category)+listing_filter("/master",q,category)+'</div>'
    rows_html=''
    for r in rows:
        mid=r["id"]
        rows_html+=tr([(e(mid),"num"),(e(r["category"]),""),
          (e(r["code"]),"num"),(e(r["color"]),""),
          (e(r["size"]),""),
          (f'<form class="forms" style="align-items:center" action="{ROOT}/master/edit" method="post">'
           f'<input type="hidden" name="master_id" value="{mid}">'
           f'<input name="title" value="{e(r["title"])}" required style="width:210px">'
           f'<input type="number" min="0" name="price" value="{r["sale_price_toman"]}" style="width:125px" title="قیمت فروش">'
           f'<input type="number" min="0" name="cost" value="{e(r["cost_toman"] if r["cost_toman"] is not None else "")}" placeholder="بهای تمام‌شده" style="width:125px">'
           f'<label><input type="checkbox" name="active" value="1"'+(' checked' if r["active"] else '')+'> فعال</label>'
           '<button>ذخیره</button></form>',''),
          (f'<a href="{ROOT}/master/stock?q={quote(r["code"])}">موجودی</a>',"")])
    top+='<div class="panel"><h3>محصولات اصلی · '+fmt(total)+' قلم</h3>'+table(
        ["شناسه","دسته","کد","رنگ","سایز","عنوان / قیمت فروش / بهای تمام‌شده","موجودی"],rows_html)+'</div>'
    if total>page_no*75:top+=f'<a class="button" href="{ROOT}/master?page_no={page_no+1}&category={quote(category)}&q={quote(q)}">صفحه بعد</a>'
    if page_no>1:top+=f' <a class="button" href="{ROOT}/master?page_no={page_no-1}&category={quote(category)}&q={quote(q)}">صفحه قبل</a>'
    top+=f'<p><a href="{ROOT}/catalog">تعریف محصولات دیجی‌کالا و اتصال تنوع‌ها</a> · <a href="{ROOT}/master/stock">موجودی کالا</a></p>'
    return page('تعریف محصولات اصلی',top,'پنج دسته اصلی • مرجع واحد برای تمام کانال‌های فروش')

@router.post(ROOT+"/master/add")
def master_add(category:str=Form(...),code:str=Form(...),title:str=Form(...),size:str=Form("-"),color:str=Form("-"),sale_price:str=Form("0"),cost:str=Form(""),conn=Depends(conn_dep)):
    try:add_master(conn,category,code,title,size,color,sale_price,cost)
    except (ImportErrorDetail,ValueError) as ex:return fail(ex)
    return RedirectResponse(ROOT+"/master?category="+quote(category),status_code=303)

@router.post(ROOT+"/master/edit")
def master_edit(master_id:int=Form(...),title:str=Form(...),price:str=Form(...),cost:str=Form(""),active:str=Form(""),conn=Depends(conn_dep)):
    try:update_master(conn,master_id,title,price,cost,bool(active))
    except (ImportErrorDetail,ValueError) as ex:return fail(ex)
    return RedirectResponse(ROOT+"/master?q="+str(master_id),status_code=303)

@router.get(ROOT+"/master/stock")
def stock(category:str="",q:str="",page_no:int=1,conn=Depends(conn_dep)):
    if category not in CATEGORIES:category=""
    page_no=max(1,min(page_no,10000))
    total,rows=query_master(conn,category,q,75,(page_no-1)*75)
    body=notice('هر تغییر موجودی سند دارد. تعداد ثبت‌شده موجودی واقعی همان کالا در آن محل است؛ فروش تأییدشده از همان محل کسر می‌شود.')
    body+='<div class="panel"><h3>فیلتر موجودی کالا</h3>'+filter_links("/master/stock",category)+listing_filter("/master/stock",q,category)+'</div>'
    body_rows=""
    total_seller=total_digikala=0
    for r in rows:
        mid=r["id"];total_seller+=r["seller_stock"];total_digikala+=r["digikala_stock"]
        def stock_form(src,value):
            return (f'<form action="{ROOT}/master/stock/adjust" method="post" class="forms" style="align-items:center">'
                    f'<input type="hidden" name="master_id" value="{mid}"><input type="hidden" name="source" value="{src}">'
                    f'<input type="number" name="stock" min="0" value="{value}" required style="width:105px">'
                    '<input name="reason" required placeholder="علت شمارش یا اصلاح" style="width:165px">'
                    '<button type="submit">ثبت</button></form>')
        body_rows+=tr([(e(r["category"]),""),
                       (e(r["code"]),"num"),
                       (e(r["title"])+' / '+e(r["color"])+' / '+e(r["size"]),"title"),
                       (stock_form("seller",r["seller_stock"]),""),
                       (stock_form("digikala",r["digikala_stock"]),""),
                       (fmt(r["seller_stock"]+r["digikala_stock"]),"num")])
    body+='<div class="panel"><h3>موجودی کالا · '+fmt(total)+' محصول</h3>'+table(
        ["دسته","کد","کالا / رنگ / سایز","موجودی فروشنده","موجودی نزد دیجی‌کالا","کل"],body_rows)+'</div>'
    if total>page_no*75:body+=f'<a class="button" href="{ROOT}/master/stock?page_no={page_no+1}&category={quote(category)}&q={quote(q)}">صفحه بعد</a>'
    if page_no>1:body+=f' <a class="button" href="{ROOT}/master/stock?page_no={page_no-1}&category={quote(category)}&q={quote(q)}">صفحه قبل</a>'
    body+=f'<p><a href="{ROOT}/master">تعریف یا ویرایش محصول</a></p>'
    return page('موجودی کالای اصلی',body,'فقط کالاهای تعریف‌شده در پنج دسته، با سند اصلاح موجودی')

@router.post(ROOT+"/master/stock/adjust")
def stock_adjust(master_id:int=Form(...),source:str=Form(...),stock:str=Form(...),reason:str=Form(...),conn=Depends(conn_dep)):
    try:adjust_master_stock(conn,master_id,source,stock,reason)
    except (ImportErrorDetail,ValueError) as ex:return fail(ex)
    return RedirectResponse(ROOT+"/master/stock",status_code=303)

@router.get(ROOT+"/catalog")
def catalog(q:str="",unmapped:int=0,page_no:int=1,conn=Depends(conn_dep)):
    page_no=max(1,min(page_no,10000))
    where="WHERE 1=1";args=[]
    if unmapped: where+=" AND p.master_id IS NULL"
    if q:
        where+=" AND (p.title LIKE ? OR CAST(p.variant_id AS TEXT) LIKE ? OR p.category LIKE ?)"
        args+=['%'+q+'%']*3
    total=conn.execute("SELECT COUNT(*) FROM products p "+where,args).fetchone()[0]
    mapped=conn.execute("SELECT COUNT(*) FROM products WHERE master_id IS NOT NULL").fetchone()[0]
    rows=conn.execute("""SELECT p.*,m.code master_code,m.category master_category,
       m.color master_color,m.size master_size,m.title master_title
       FROM products p LEFT JOIN master_products m ON m.id=p.master_id """+where+
       " ORDER BY p.master_id IS NULL DESC,p.category,p.title LIMIT 50 OFFSET ?",
       args+[(page_no-1)*50]).fetchall()
    all_masters=conn.execute("SELECT id,category,code,size,color FROM master_products WHERE active=1 ORDER BY category,code,size,color LIMIT 10000").fetchall()
    list_options='<option value="">انتخاب محصول اصلی</option>'+''.join(
        f'<option value="{m["id"]}">{e(m["category"])} · {e(m["code"])} · {e(m["color"])} · {e(m["size"])} (#{m["id"]})</option>'
        for m in all_masters)
    body=notice(f'{mapped} کد از ۵۳۸ کد تنوع به محصولات اصلی متصل شده است. تا پیش از اتصال، فروش آن کد ثبت نمی‌شود. موجودی را فقط در «موجودی کالا» اصلاح کن.')
    body+=f'<div class="panel"><h3>اتصال کد تنوع به کالای اصلی و قیمت فروش آن در دیجی‌کالا</h3><form class="forms" action="{ROOT}/catalog/map" method="post">'
    body+='<div><label>کد تنوع دیجی‌کالا</label><input type="number" min="1" name="variant_id" required placeholder="کد تنوع"></div>'
    body+='<div><label>محصول اصلی (شامل دسته و رنگ و سایز)</label><select name="master_id" required>'+list_options+'</select></div>'
    body+='<div><label>قیمت فروش دیجی‌کالا (تومان)</label><input type="number" min="0" name="sale_price" placeholder="خالی = قیمت فروش محصول اصلی"></div>'
    body+='<button type="submit">ذخیره اتصال</button></form></div>'
    body+='<div class="panel"><h3>جست‌وجوی ۵۳۸ تنوع دیجی‌کالا</h3>'
    body+=f'<form method="get" action="{ROOT}/catalog" class="forms"><div><label>عنوان یا کد تنوع</label><input name="q" value="{e(q)}"></div>'
    body+=f'<div><label>فقط بدون اتصال</label><input type="checkbox" name="unmapped" value="1"'+(' checked' if unmapped else '')+'></div><button>جست‌وجو</button></form></div>'
    catalog_rows=""
    for r in rows:
        mapped_to=(e(r["master_category"])+" / "+e(r["master_code"])+" / "+e(r["master_color"])+" / "+e(r["master_size"])) if r["master_id"] else '<span style="color:#ffa460">بدون اتصال</span>'
        catalog_rows+=tr([(f'<a href="{ROOT}/catalog?q={r["variant_id"]}">{r["variant_id"]}</a>',"num"),
                         (e(r["title"]),"title"),(e(r["category"]),""),
                         (mapped_to,""),(fmt(r["sale_price_toman"] if r["sale_price_toman"] is not None else r["list_price_rial"]//10),"num"),
                         (f'<a href="{ROOT}/master/stock?q={quote(r["master_code"] or "")}">موجودی</a>' if r["master_id"] else '—',"")])
    body+='<div class="panel"><h3>فهرست کدهای دیجی‌کالا · '+fmt(total)+' ردیف</h3>'+table(
        ["کد تنوع","عنوان دیجی‌کالا","گروه ارسالی","اتصال به کالای اصلی","قیمت فعلی/پیش‌فرض (تومان)","موجودی"],catalog_rows)+'</div>'
    if total>page_no*50:body+=f'<a class="button" href="{ROOT}/catalog?page_no={page_no+1}&q={quote(q)}&unmapped={unmapped}">صفحه بعد</a>'
    if page_no>1:body+=f' <a class="button" href="{ROOT}/catalog?page_no={page_no-1}&q={quote(q)}&unmapped={unmapped}">صفحه قبل</a>'
    body+=f'<p><a href="{ROOT}/master">تعریف محصولات اصلی</a> · <a href="{ROOT}/master/stock">موجودی کالا</a></p>'
    return page('محصولات دیجی‌کالا',body,'۵۳۸ کد تنوع مرجع • نگاشت به محصول، رنگ، سایز و قیمت فروش')

@router.post(ROOT+"/catalog/map")
def catalog_map(variant_id:int=Form(...),master_id:int=Form(...),sale_price:str=Form(""),conn=Depends(conn_dep)):
    try:map_variant(conn,variant_id,master_id,sale_price)
    except (ImportErrorDetail,ValueError) as ex:return fail(ex)
    return RedirectResponse(ROOT+"/catalog?q="+str(variant_id),status_code=303)
