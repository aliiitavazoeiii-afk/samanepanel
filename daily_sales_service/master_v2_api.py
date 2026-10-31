"""Route family for sister catalogue, centralized pricing, and dual-warehouse stock."""
from collections import defaultdict
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .app import ROOT, conn_dep, e, fmt
from .engine import ImportErrorDetail
from .master_engine import CATEGORIES
from .master_v2_logic import (
    BODY_TYPES, CHANNELS, SIZES, WAREHOUSES, add_model, rename_model,
    list_models, sku_rows, batch_adjust, batch_transfer,
    set_cost_rule, set_channel_prices, cost_for,
)
from .master_v2_ui import (
    page_with_style, category_tabs, category_option, group_options, inventory_grid, family_title,
)
from .master_api import catalog as digikala_catalog, catalog_map as digikala_map
from .master_v2_corrections import undo_adjustment, revise_transfer

router=APIRouter()

def alert_error(exc):
    return page_with_style("خطا در ثبت",f'<div class="m2-msg">{e(str(exc))}</div>'
       +f'<p><a class="m2-btn" href="{ROOT}/master">بازگشت به تعاریف</a> · '
       +f'<a href="{ROOT}/master/stock">موجودی کالا</a> · '
       +f'<a href="{ROOT}/pricing">قیمت‌گذاری</a></p>')

def tabs(category):
    return category_tabs("/master",category)

def _subtypes(category):
    if category=="بادیگارد":
        return '<option value="">همه</option>'+''.join(f'<option value="{e(t)}">{e(t)}</option>' for t in BODY_TYPES)
    return '<option value="">بدون زیرگروه</option>'

def _filter_form(endpoint,category,subtype,q,models,model_id="",with_model=False):
    model_input=('''<div><label>مدل محصول</label><select name="model_id">'''
                 +group_options(models,model_id)+'</select></div>') if with_model else ''
    opt='<option value="">همه زیرگروه‌ها</option>'
    if category=="بادیگارد":
        opt+=''.join(f'<option value="{e(t)}"'+(' selected' if t==subtype else '')+'>'+e(t)+'</option>' for t in BODY_TYPES)
    return (f'<div class="m2-filters"><form action="{ROOT}{endpoint}" method="get">'
        f'<input type="hidden" name="category" value="{e(category)}">'
        f'<div><label>جست‌وجوی نام مدل یا رنگ</label><input name="q" value="{e(q)}" placeholder="نام محصول یا رنگ"></div>'
        f'<div><label>نوع محصول</label><select name="subtype">{opt}</select></div>'
        +model_input+
        '<div><button type="submit">اعمال فیلتر</button></div></form></div>')

@router.get(ROOT+"/master")
def master(category:str="",subtype:str="",q:str="",conn=Depends(conn_dep)):
    category=category if category in CATEGORIES else CATEGORIES[0]
    subtype=subtype if category=="بادیگارد" and subtype in BODY_TYPES else ""
    models=list_models(conn,category,subtype,q)
    intro=(f'<div class="m2-hero"><div><h1>تعریف محصولات</h1>'
      '<p class="m2-hint">فقط هویت کالا: دسته، نام، نوع، رنگ و سایزبندی. قیمت و موجودی در بخش‌های جداگانه‌اند.</p></div>'
      f'<a class="m2-btn" href="{ROOT}/pricing">قیمت‌گذاری</a></div>')
    intro+=tabs(category)
    intro+=_filter_form("/master",category,subtype,q,models)
    subtype_select=(f'<div><label>نوع بادیگارد</label><select name="subtype">'
          +''.join(f'<option value="{e(t)}">{e(t)}</option>' for t in BODY_TYPES)
          +'</select></div>') if category=="بادیگارد" else '<input type="hidden" name="subtype" value="">'
    intro+=f'''<div class="m2-card" style="margin-bottom:22px"><h3>افزودن محصول / مدل</h3>
<form method="post" action="{ROOT}/master/add" class="m2-fields">
<input type="hidden" name="category" value="{e(category)}">
<div><label>عنوان محصول</label><input name="title" placeholder="نام مدل" required maxlength="220"></div>
{subtype_select}
<div><label>رنگ‌بندی (با ویرگول جدا کن)</label><input name="colors" placeholder="مشکی، سفید، سرمه‌ای"></div>
<div><label>سایزبندی (با ویرگول جدا کن)</label><input name="sizes" placeholder="{e('، '.join(SIZES[category]))}"></div>
<div><button type="submit" class="m2-btn">ثبت محصول</button></div>
</form><p class="m2-hint" style="margin-top:12px">اگر همین مدل قبلاً ثبت شده باشد، فقط ترکیب رنگ/سایزهای جدید اضافه می‌شوند و موجودی‌های قبلی حفظ می‌شوند. شناسه داخلی به‌صورت خودکار ساخته می‌شود.</p></div>'''
    if not models:
        intro+='<div class="m2-card"><h3>هنوز محصولی در این فیلتر تعریف نشده است.</h3></div>'
    else:
        # Imported catalog codes are per color, NOT per product model.
        # Present them as ONE family card with all colors and sizes; keep
        # every physical SKU ID/stock/DigiKala mapping unchanged.
        families={}
        for m in models:
            product_skus=sku_rows(conn,category,m["representative"],active_only=False)
            if not product_skus:continue
            key=(family_title(product_skus[0]),m["subtype"])
            family=families.setdefault(key,{"models":[],"skus":[]})
            family["models"].append(m)
            family["skus"].extend(product_skus)
        intro+='<h3>مدل‌های تعریف‌شده</h3><div class="m2-list">'
        for (family_name,group_type),family in families.items():
            skus=family["skus"]
            colors=sorted({s["color"] for s in skus})
            sizes=sorted({s["size"] for s in skus})
            intro+=f'<div class="m2-card"><h3>{e(family_name)}</h3>'
            if group_type:intro+=f'<p class="m2-hint">نوع: {e(group_type)}</p>'
            intro+=f'<p class="m2-hint">{len(colors)} رنگ · {len(sizes)} سایز · {len(skus)} تنوع فیزیکی</p>'
            intro+='<div class="m2-tags">'+''.join(f'<span class="m2-tag">{e(col)}</span>' for col in colors)+'</div>'
            intro+='<p class="m2-hint">سایزها: '+e(" · ".join(sizes))+'</p>'
            if len(family["models"])==1:
                m=family["models"][0]
                intro+=f'''<form method="post" action="{ROOT}/master/rename" class="m2-fields">
<input type="hidden" name="master_id" value="{m["representative"]}">
<div><label>ویرایش عنوان</label><input name="title" value="{e(m["title"])}" required></div>
<div><label><input type="checkbox" name="active" value="1" {"checked" if m["active"] else ""}> فعال</label><button class="m2-btn" type="submit">ذخیره</button></div>
</form>'''
            else:
                intro+='<p class="m2-hint">رنگ‌ها به‌صورت یک مدل نمایش داده می‌شوند و شناسه‌های قبلیِ کالا بدون تغییر باقی مانده‌اند.</p>'
            intro+=f'<p><a class="m2-btn" href="{ROOT}/master/stock?category={quote(category)}'+(f'&subtype={quote(group_type)}' if group_type else '')+'">مشاهده موجودی</a></p></div>'
        intro+='</div>'
    intro+=f'<p style="margin-top:24px"><a href="{ROOT}/catalog">محصولات دیجی‌کالا</a> · <a href="{ROOT}/master/stock">موجودی کالا</a></p>'
    return page_with_style("تعریف محصولات",intro)

@router.post(ROOT+"/master/add")
def add(category:str=Form(...),title:str=Form(...),subtype:str=Form(""),colors:str=Form(""),sizes:str=Form(""),conn=Depends(conn_dep)):
    try:add_model(conn,category,title,subtype,colors,sizes)
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/master?category="+quote(category),status_code=303)

@router.post(ROOT+"/master/rename")
def rename(master_id:int=Form(...),title:str=Form(...),active:str=Form(""),conn=Depends(conn_dep)):
    try:rename_model(conn,master_id,title,bool(active))
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/master",status_code=303)

def _model_scope(conn,category,subtype="",q="",model_id=None):
    models=list_models(conn,category,subtype,q)
    if model_id and not any(m["representative"]==model_id for m in models):model_id=None
    if not model_id and models:model_id=models[0]["representative"]
    return models,model_id

@router.get(ROOT+"/master/stock")
def stock(category:str="",subtype:str="",q:str="",model_id:int|None=None,conn=Depends(conn_dep)):
    category=category if category in CATEGORIES else CATEGORIES[0]
    subtype=subtype if category=="بادیگارد" and subtype in BODY_TYPES else ""
    models=list_models(conn,category,subtype,q)
    # All models/colors are shown by default, like Darma's stock board.
    # Optional model selection narrows to a specific SKU group.
    if model_id and not any(m["representative"]==model_id for m in models):
        model_id=None
    body='<h1>موجودی کالا</h1><p class="m2-hint">ابتدا دسته و نوع را انتخاب کن؛ رنگ‌ها در سطر و سایزها در ستون نمایش داده می‌شوند.</p>'
    legacy=conn.execute("SELECT COALESCE(SUM(digikala_stock),0) FROM master_products").fetchone()[0]
    if legacy:
        body+=f'<div class="m2-msg">{fmt(legacy)} عدد موجودی قدیمیِ «نزد دیجی‌کالا» جداگانه محفوظ است؛ بدون تأیید تو به خورشید منتقل نمی‌شود.</div>'
    body+=category_tabs("/master/stock",category)
    body+=_filter_form("/master/stock",category,subtype,q,models,model_id,with_model=False)
    body+=f'<div class="m2-hero"><h2>{e(category)}'+(f' — {e(subtype)}' if subtype else '')+'</h2>'
    ops_link=f'{ROOT}/master/stock/operations?category={quote(category)}'
    if subtype:ops_link+='&subtype='+quote(subtype)
    if model_id:ops_link+='&model_id='+str(model_id)
    body+=f'<a class="m2-btn" href="{ops_link}">انتقال / اصلاح موجودی</a></div>'
    skus=sku_rows(conn,category,model_id,subtype=subtype)
    if q:
        skus=[s for s in skus if q in s["title"] or q in s["color"] or q in s["size"]]
    if not skus:
        body+='<div class="m2-card"><p>برای فیلتر انتخاب‌شده کالایی تعریف نشده است.</p></div>'
    else:
        families={}
        for sku in skus:
            families.setdefault(family_title(sku),[]).append(sku)
        for family_name,rows in sorted(families.items(),key=lambda item:(0 if "اسلیپ" in item[0] else 1,item[0])):
            if len(families)>1:
                body+=f'<h3 class="m2-family-title">{e(family_name)}</h3>'
            for location,label in (("total","موجودی کل"),("home","موجودی خانه"),("khorshid","موجودی انبار خورشید")):
                body+=inventory_grid(conn,rows,location,label)
        body+='<p class="m2-hint">قرمز پررنگ: صفر؛ قرمز ملایم: کمتر از ۱۰ عدد. ارزش سرمایه از بهای تمام‌شده محاسبه می‌شود.</p>'
    body+=f'<p><a href="{ROOT}/master?category={quote(category)}">بازگشت به تعریف محصولات</a></p>'
    return page_with_style("موجودی کالا",body)

def _operations_filter(conn,category,model_id,subtype,size,location):
    models=list_models(conn,category,subtype)
    if model_id and not any(m["representative"]==model_id for m in models):
        model_id=None
    # Preserve "all colors" as the default, rather than silently narrowing
    # the correction screen to one color-coded imported model.
    skus=sku_rows(conn,category,model_id,subtype=subtype)
    order=("XS","S","M","L","XL","2XL","XXL","3XL","4XL","کوچک","متوسط","بزرگ")
    sizes=sorted({s["size"] for s in skus},key=lambda x:(order.index(x) if x in order else 999,x))
    if size not in sizes:size=sizes[0] if sizes else ""
    selected=[s for s in skus if s["size"]==size]
    current_model=next((m for m in models if m["representative"]==model_id),None)
    return models,model_id,skus,sizes,size,selected,current_model

@router.get(ROOT+"/master/stock/operations")
def operations(category:str="",model_id:int|None=None,subtype:str="",size:str="",location:str="home",conn=Depends(conn_dep)):
    category=category if category in CATEGORIES else CATEGORIES[0]
    if location not in WAREHOUSES:location="home"
    subtype=subtype if category=="بادیگارد" and subtype in BODY_TYPES else ""
    models,model_id,skus,sizes,size,selected,model=_operations_filter(conn,category,model_id,subtype,size,location)
    body='<h1>انتقال / اصلاح موجودی</h1><p class="m2-hint">اصلاح تعداد نهایی و انتقال بین خانه و خورشید، با ثبت سند گردش برای هر رنگ و سایز.</p>'
    body+=category_tabs("/master/stock/operations",category)
    body+=f'<div class="m2-filters"><form action="{ROOT}/master/stock/operations" method="get">'
    body+=f'<input type="hidden" name="category" value="{e(category)}">'
    if category=="بادیگارد":
        opts='<option value="">همه نوع‌ها</option>'+''.join(
            f'<option value="{e(x)}"'+(' selected' if subtype==x else '')+f'>{e(x)}</option>' for x in BODY_TYPES)
        body+='<div><label>نوع بادیگارد</label><select name="subtype">'+opts+'</select></div>'
    # The imported catalog uses a separate internal code for every color.
    # Avoid exposing that technical choice as dozens of confusing model filters.
    if model_id:
        body+=f'<input type="hidden" name="model_id" value="{model_id}">'
    body+='<div><label>سایز</label><select name="size">'+''.join(f'<option value="{e(s)}"'+(' selected' if s==size else '')+'>'+e(s)+'</option>' for s in sizes)+'</select></div>'
    body+='<div><label>محل اصلاح</label><select name="location"><option value="home"'+(' selected' if location=="home" else '')+'>خانه</option><option value="khorshid"'+(' selected' if location=="khorshid" else '')+'>خورشید</option></select></div>'
    body+='<div><button type="submit">نمایش موجودی</button></div></form></div>'
    if not selected:
        body+='<div class="m2-card">برای این فیلتر کالایی پیدا نشد.</div>'
    else:
        body+=f'<div class="m2-card"><h3>اصلاح موجودی {e(model["title"] if model else category)} — سایز {e(size)}</h3>'
        body+='<p class="m2-hint">فقط رنگ‌هایی که باید اصلاح شوند را پر کن؛ عدد واردشده جایگزین موجودی فعلی همان انبار می‌شود.</p>'
        body+=f'<form method="post" action="{ROOT}/master/stock/bulk-adjust"><input type="hidden" name="category" value="{e(category)}"><input type="hidden" name="model_id" value="{model_id or ''}"><input type="hidden" name="subtype" value="{e(subtype)}"><input type="hidden" name="size" value="{e(size)}"><input type="hidden" name="location" value="{e(location)}">'
        body+='<div class="m2-operation-grid">'
        for s in selected:
            body+=f'<div class="m2-operation-color"><strong>{e(s["color"])}'+(f' · {e(family_title(s))}' if not subtype and category=="بادیگارد" else '')+'</strong>'
            body+=f'<div class="m2-hint">خانه: {fmt(s["seller_stock"])} · خورشید: {fmt(s["khorshid_stock"])} · کل: {fmt(s["seller_stock"]+s["khorshid_stock"])}</div>'
            body+=f'<label>موجودی جدید {("خانه" if location=="home" else "خورشید")}</label><input type="number" min="0" name="target_{s["id"]}" placeholder="بدون تغییر" /></div>'
        body+='</div><div class="m2-fields" style="margin-top:16px"><div><label>دلیل اصلاح</label><input name="reason" required placeholder="شمارش موجودی / مغایرت"></div><div><button type="submit" class="m2-btn">ثبت اصلاح موجودی</button></div></div></form></div>'
        body+=f'<div class="m2-card" style="margin-top:20px"><h3>انتقال بین انبار خورشید و خانه</h3>'
        body+=f'<form method="post" action="{ROOT}/master/stock/transfer"><input type="hidden" name="category" value="{e(category)}"><input type="hidden" name="model_id" value="{model_id or ''}"><input type="hidden" name="subtype" value="{e(subtype)}"><input type="hidden" name="size" value="{e(size)}">'
        body+='<div class="m2-fields"><div><label>جهت انتقال</label><select name="location">'
        body+='<option value="khorshid">خورشید ← خانه</option><option value="home">خانه ← خورشید</option></select></div></div>'
        body+='<div class="m2-operation-grid" style="margin-top:14px">'
        for s in selected:
            body+=f'<div class="m2-operation-color"><strong>{e(s["color"])}'+(f' · {e(family_title(s))}' if not subtype and category=="بادیگارد" else '')+f'</strong><div class="m2-hint">خانه: {fmt(s["seller_stock"])} · خورشید: {fmt(s["khorshid_stock"])}</div><input type="number" name="qty_{s["id"]}" min="0" placeholder="تعداد انتقال"></div>'
        body+='</div><div class="m2-fields" style="margin-top:15px"><div><label>شرح انتقال</label><input name="reason" value="انتقال بین دو انبار" required></div><div><button type="submit" class="m2-btn">ثبت انتقال</button></div></div></form></div>'
    recent=conn.execute("""SELECT ev.id,ev.master_id,ev.occurred_at,ev.source,ev.delta,ev.balance_after,ev.reference,
       m.title,m.color,m.size FROM master_stock_events ev
       JOIN master_products m ON m.id=ev.master_id
       WHERE m.category=? ORDER BY ev.id DESC LIMIT 40""",(category,)).fetchall()
    body+='<div class="m2-section"><h3>آخرین گردش‌ها و اصلاحات</h3><div class="m2-history"><table>'
    body+='<thead><tr><th>زمان</th><th>مدل</th><th>رنگ / سایز</th><th>انبار</th><th>تغییر</th><th>موجودی پس از ثبت</th><th>شرح</th><th>اصلاح سند</th></tr></thead><tbody>'
    seen_latest=set()
    for ev in recent:
        loc={"home":"خانه","seller":"خانه","khorshid":"خورشید","digikala":"دیجی‌کالا (سابق)"}.get(ev["source"],ev["source"])
        key=(ev["master_id"],ev["source"])
        eligible=key not in seen_latest and str(ev["reference"]).startswith("adjust:") and ev["source"] in ("home","khorshid")
        seen_latest.add(key)
        undo_button=(f'<form method="post" action="{ROOT}/master/stock/undo" onsubmit="return confirm(\'این اصلاح برگردانده شود؟\')"><input type="hidden" name="event_id" value="{ev["id"]}"><input type="hidden" name="category" value="{e(category)}"><button type="submit">برگرداندن اصلاح</button></form>') if eligible else "—"
        body+=f'<tr><td>{e(ev["occurred_at"][:19])}</td><td>{e(ev["title"])}</td><td>{e(ev["color"])} / {e(ev["size"])}</td><td>{e(loc)}</td><td>{fmt(ev["delta"])}</td><td>{fmt(ev["balance_after"])}</td><td>{e(ev["reference"])}</td><td>{undo_button}</td></tr>'
    body+='</tbody></table></div></div>'
    transfers=conn.execute("""SELECT t.*,m.title,m.size,m.color FROM master_transfers t
        JOIN master_products m ON m.id=t.master_id
        WHERE m.category=? ORDER BY t.id DESC LIMIT 30""",(category,)).fetchall()
    if transfers:
        body+='<div class="m2-section"><h3>سوابق انتقال و ویرایش تعداد</h3><div class="m2-history"><table><thead><tr><th>زمان</th><th>محصول</th><th>مسیر</th><th>تعداد قبلی</th><th>ویرایش تعداد</th></tr></thead><tbody>'
        for t in transfers:
            src="خانه" if t["from_location"]=="home" else "خورشید"
            dst="خانه" if t["to_location"]=="home" else "خورشید"
            edit=(f'<form action="{ROOT}/master/stock/transfer/revise" method="post" class="m2-fields"><input type="hidden" name="transfer_id" value="{t["id"]}"><input type="hidden" name="category" value="{e(category)}"><input type="number" name="target_qty" value="{t["quantity"]}" min="0" style="width:100px"><button type="submit">اصلاح</button></form>')
            body+=f'<tr><td>{e(t["occurred_at"][:19])}</td><td>{e(t["title"])} / {e(t["color"])} / {e(t["size"])}</td><td>{e(src)} ← {e(dst)}</td><td>{fmt(t["quantity"])}</td><td>{edit}</td></tr>'
        body+='</tbody></table></div><p class="m2-hint">ویرایش انتقال فقط وقتی مجاز است که بعد از آن هیچ گردش دیگری روی همان کالا و دو انبار ثبت نشده باشد؛ برای جلوگیری از برهم‌خوردن موجودی.</p></div>'
    body+=f'<a class="m2-btn" href="{ROOT}/master/stock?category={quote(category)}'+(f'&model_id={model_id}' if model_id else '')+'">بازگشت به موجودی کالا</a>'
    return page_with_style("انتقال / اصلاح موجودی",body)

def _posted_targets(conn,category,model_id,size,post,prefix,subtype=""):
    valid=sku_rows(conn,category,model_id,subtype=subtype)
    return {s["id"]:post.get(f"{prefix}{s['id']}") for s in valid if s["size"]==size and post.get(f"{prefix}{s['id']}") not in (None,"")}

@router.post(ROOT+"/master/stock/bulk-adjust")
async def post_adjust(request:Request,category:str=Form(...),model_id:str=Form(""),subtype:str=Form(""),size:str=Form(...),location:str=Form(...),reason:str=Form(...),conn=Depends(conn_dep)):
    try:
        post=await request.form()
        mid=int(model_id) if model_id else None
        values=_posted_targets(conn,category,mid,size,post,"target_",subtype)
        count=batch_adjust(conn,category,mid,size,location,values,reason)
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/master/stock/operations?category="+quote(category)+(f"&model_id={model_id}" if model_id else "")+f"&size={quote(size)}&subtype={quote(subtype)}&location={location}",status_code=303)

@router.post(ROOT+"/master/stock/transfer")
async def post_transfer(request:Request,category:str=Form(...),model_id:str=Form(""),subtype:str=Form(""),size:str=Form(...),location:str=Form(...),reason:str=Form(...),conn=Depends(conn_dep)):
    try:
        post=await request.form()
        mid=int(model_id) if model_id else None
        values=_posted_targets(conn,category,mid,size,post,"qty_",subtype)
        batch_transfer(conn,category,mid,size,location,values,reason)
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/master/stock/operations?category="+quote(category)+(f"&model_id={model_id}" if model_id else "")+f"&size={quote(size)}&subtype={quote(subtype)}",status_code=303)

@router.post(ROOT+"/master/stock/undo")
def undo_stock(event_id:int=Form(...),category:str=Form(""),conn=Depends(conn_dep)):
    try:undo_adjustment(conn,event_id)
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/master/stock/operations?category="+quote(category),status_code=303)

@router.post(ROOT+"/master/stock/transfer/revise")
def revise_stock_transfer(transfer_id:int=Form(...),target_qty:str=Form(...),category:str=Form(""),conn=Depends(conn_dep)):
    try:revise_transfer(conn,transfer_id,target_qty)
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/master/stock/operations?category="+quote(category),status_code=303)

def _price_tiles():
    return (f'<div class="m2-cards">'
      f'<a class="m2-card" href="{ROOT}/pricing/cost" style="text-decoration:none"><h3>بهای تمام‌شده</h3><p class="m2-hint">تعریف هزینه تولید بر اساس نوع کالا؛ بادیگارد اسلیپ/پادار و قالب کوچک/متوسط/بزرگ.</p></a>'
      f'<a class="m2-card" href="{ROOT}/pricing/sales" style="text-decoration:none"><h3>قیمت فروش</h3><p class="m2-hint">قیمت‌گذاری گروهی فروش سایت، باسلام و قالب؛ مستقل از دیجی‌کالا.</p></a></div>')

@router.get(ROOT+"/pricing")
def pricing(conn=Depends(conn_dep)):
    return page_with_style("قیمت‌گذاری",'<h1>قیمت‌گذاری</h1><p class="m2-hint">قیمت از تعریف محصول جدا شده است.</p>'+_price_tiles())

@router.get(ROOT+"/pricing/cost")
def cost_prices(as_of:str="",conn=Depends(conn_dep)):
    from datetime import date,timedelta
    from .effective_costs import today,dated_cost,valid_date
    today_key=today()
    proposed=(date.fromisoformat(today_key)+timedelta(days=1)).isoformat()
    shown=valid_date(as_of) if as_of else today_key
    rules={(r["category"],r["subtype"],r["size"]):r["cost_toman"]
           for r in conn.execute("""SELECT h.category,h.subtype,h.size,h.cost_toman
              FROM master_cost_history h WHERE h.effective_date=(
                SELECT MAX(y.effective_date) FROM master_cost_history y
                WHERE y.category=h.category AND y.subtype=h.subtype AND y.size=h.size AND y.effective_date<=?)""",(shown,))}
    body='<h1>بهای تمام‌شده</h1><p class="m2-hint">برای هر دسته، بهای تمام‌شده جدید و تاریخ اجرای آن را مشخص کن. از همان تاریخ، ارزش موجودی و بهای فروش‌های جدید با نرخ تازه محاسبه می‌شود. فروش‌های ثبت‌شده قبلی تغییر نمی‌کنند.</p>'
    body+=_price_tiles()
    body+=f'<form action="{ROOT}/pricing/cost" method="get" class="m2-filters" style="margin-top:18px"><label>مشاهده نرخ‌های مؤثر در تاریخ</label><div class="m2-fields"><input name="as_of" type="date" value="{e(shown)}"><button type="submit" class="m2-btn">نمایش</button></div></form>'
    body+='<div class="m2-cost-stack">'
    for category in CATEGORIES:
        variants=[("اسلیپ","*"),("پادار","*")] if category=="بادیگارد" else ([("",s) for s in SIZES["قالب"]] if category=="قالب" else [("","*")])
        body+=f'<section class="m2-card m2-cost-row"><h3>{e(category)}</h3>'
        for subtype,size in variants:
            current=rules.get((category,subtype,size))
            name=subtype or (size if size!="*" else "همه محصولات این دسته")
            latest=conn.execute("""SELECT effective_date,cost_toman FROM master_cost_history
                WHERE category=? AND subtype=? AND size=? AND effective_date>? ORDER BY effective_date ASC LIMIT 3""",
                (category,subtype,size,today_key)).fetchall()
            body+=f'<form method="post" action="{ROOT}/pricing/cost/save" class="m2-cost-line">'
            body+=f'<input type="hidden" name="category" value="{e(category)}"><input type="hidden" name="subtype" value="{e(subtype)}"><input type="hidden" name="size" value="{e(size)}">'
            body+=f'<div class="m2-cost-caption"><strong>{e(name)}</strong><span>قیمت مؤثر در {e(shown)}: {fmt(current) if current is not None else "تعریف‌نشده"} تومان</span></div>'
            body+=f'<div><label>بهای تمام‌شده جدید (تومان)</label><input type="number" name="cost" min="0" required placeholder="مبلغ جدید"></div>'
            body+=f'<div><label>تاریخ شروع اجرا</label><input type="date" name="effective_date" min="{today_key}" value="{proposed}" required></div>'
            body+='<div><button type="submit" class="m2-btn">ثبت نرخ جدید</button></div></form>'
            if latest:
                body+='<div class="m2-hint">نرخ‌های برنامه‌ریزی‌شده: '+ ' · '.join(f'{e(v["effective_date"])}: {fmt(v["cost_toman"])} تومان' for v in latest)+'</div>'
        body+='</section>'
    body+='</div>'
    body+=f'<p style="margin-top:20px"><a href="{ROOT}/capital-report">مشاهده گزارش جامع سرمایه بر اساس نرخ امروز</a></p>'
    return page_with_style("بهای تمام‌شده",body)

@router.post(ROOT+"/pricing/cost/save")
def save_cost(category:str=Form(...),subtype:str=Form(""),size:str=Form("*"),
              cost:str=Form(...),effective_date:str=Form(...),conn=Depends(conn_dep)):
    from .effective_costs import schedule_cost
    try:schedule_cost(conn,category,subtype,size,cost,effective_date)
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/pricing/cost",status_code=303)

@router.get(ROOT+"/pricing/sales")
def sales_prices(channel:str="site",category:str="",conn=Depends(conn_dep)):
    if channel not in CHANNELS:channel="site"
    category=category if category in CATEGORIES else ("قالب" if channel=="mold" else CATEGORIES[0])
    if channel=="mold":category="قالب"
    models=list_models(conn,category)
    body='<h1>قیمت فروش</h1><p class="m2-hint">قیمت مستقل برای هر درگاه، قابل اعمال گروهی به مدل یا دسته و سایز. دیجی‌کالا فقط در «محصولات دیجی‌کالا» مدیریت می‌شود.</p>'
    body+=_price_tiles()
    body+='<div class="m2-tabs">'+''.join(f'<a href="{ROOT}/pricing/sales?channel={name}" class="{("current" if name==channel else "")}">{e(title)}</a>' for name,title in CHANNELS.items())+'</div>'
    body+=f'<div class="m2-card"><h3>ثبت گروهی قیمت — {e(CHANNELS[channel])}</h3><form method="post" action="{ROOT}/pricing/sales/save" class="m2-fields">'
    body+=f'<input type="hidden" name="channel" value="{e(channel)}">'
    if channel=="mold":
        body+='<input type="hidden" name="category" value="قالب"><div><label>دسته</label><strong>قالب</strong></div>'
    else:
        body+='<div><label>دسته</label><select name="category" id="m2-cat" onchange="window.location.href=\''+ROOT+'/pricing/sales?channel='+quote(channel)+'&category=\'+encodeURIComponent(this.value)">'
        body+=category_option(category)+'</select></div>'
    if category=="بادیگارد":
        body+='<div><label>نوع بادیگارد</label><select name="subtype">'+''.join(f'<option value="{e(t)}">{e(t)}</option>' for t in BODY_TYPES)+'</select></div>'
    else:body+='<input type="hidden" name="subtype" value="">'
    body+='<div><label>مدل موردنظر</label><select name="model_id">'+group_options(models)+'</select></div>'
    body+='<div><label>سایز</label><select name="size"><option value="*">همه سایزها</option>'+''.join(f'<option value="{e(s)}">{e(s)}</option>' for s in SIZES[category])+'</select></div>'
    body+='<div><label>قیمت فروش واحد (تومان)</label><input type="number" min="0" name="price" required></div>'
    body+='<div><button class="m2-btn" type="submit">ثبت قیمت گروهی</button></div></form></div>'
    rows=conn.execute("""SELECT m.title,m.size,m.color,m.subtype,cp.price_toman FROM master_channel_prices cp
        JOIN master_products m ON m.id=cp.master_id
        WHERE cp.channel=? AND m.category=?
        ORDER BY m.title,m.size,m.color LIMIT 150""",(channel,category)).fetchall()
    body+=f'<div class="m2-section"><h3>قیمت‌های ثبت‌شده — {e(category)}</h3><div class="m2-history"><table><thead><tr><th>محصول</th><th>نوع</th><th>رنگ</th><th>سایز</th><th>قیمت (تومان)</th></tr></thead><tbody>'
    for row in rows:
        body+=f'<tr><td>{e(row["title"])}</td><td>{e(row["subtype"] or "—")}</td><td>{e(row["color"])}</td><td>{e(row["size"])}</td><td>{fmt(row["price_toman"])}</td></tr>'
    body+='</tbody></table></div></div>'
    return page_with_style("قیمت فروش",body)

@router.post(ROOT+"/pricing/sales/save")
def save_sale_price(channel:str=Form(...),category:str=Form(...),subtype:str=Form(""),size:str=Form("*"),model_id:str=Form(""),price:str=Form(...),conn=Depends(conn_dep)):
    try:
        group_id=int(model_id) if model_id else None
        set_channel_prices(conn,channel,category,subtype,size,price,group_id)
    except (ImportErrorDetail,ValueError) as exc:return alert_error(exc)
    return RedirectResponse(ROOT+"/pricing/sales?channel="+quote(channel)+"&category="+quote(category),status_code=303)

# The existing 538 DigiKala external variants and their mapping remain intact.
router.add_api_route(ROOT+"/catalog",digikala_catalog,methods=["GET"])
router.add_api_route(ROOT+"/catalog/map",digikala_map,methods=["POST"])

from .platform_api import router as platform_router
from .capital_api import router as capital_router
router.include_router(platform_router)
router.include_router(capital_router)
