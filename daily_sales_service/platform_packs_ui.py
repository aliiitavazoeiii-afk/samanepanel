"""Presentation for platform packs and per-size sales prices.

Three clean steps: define a model, choose 1–6 physical color slots, tick sizes.
All later prices belong only to these registered platform size variants.
"""
import json
from urllib.parse import quote
from .app import ROOT,e,fmt
from .master_engine import CATEGORIES
from .engine import ImportErrorDetail
from .master_v2_ui import page_with_style
from .platform_catalog import PLATFORMS, SALE_CHANNELS, list_listings
from .platform_packs_v4 import available_models,list_bundle_groups,list_bundle_variants

def _json_safe(obj):
    # JSON embedded in <script type=application/json>: do not allow HTML escape.
    return (json.dumps(obj,ensure_ascii=False)
        .replace("<","\\u003c").replace(">","\\u003e")
        .replace("&","\\u0026"))

def definition_page(conn,channel,category,q=""):
    if channel not in SALE_CHANNELS:raise ValueError("پلتفرم نامعتبر")
    if channel=="mold":category="قالب"
    if category not in CATEGORIES:category=CATEGORIES[0]
    models=available_models(conn,category)
    body=(f'<div class="m2-hero"><div><h1>{e(PLATFORMS[channel])}</h1>'
          '<p class="m2-hint">محصولات فروشی این پلتفرم را از تعاریف و رنگ‌های موجودی بساز.</p></div>'
          f'<a href="{ROOT}/platforms">بازگشت به پلتفرم‌ها</a></div>')
    body+='<section class="m2-card m2-bundle-definition"><h3>تعریف محصول</h3>'
    if channel!="mold":
        body+=f'<form method="get" action="{ROOT}/platforms/{channel}" class="m2-inline-filter">'
        body+='<div><label>دسته کالا</label><select name="category" onchange="this.form.submit()">'
        body+=''.join(f'<option value="{e(cat)}"'+(' selected' if cat==category else '')+f'>{e(cat)}</option>' for cat in CATEGORIES)
        body+='</select></div><button class="m2-btn" type="submit">نمایش</button></form>'
    else:
        body+='<p class="m2-hint">دسته کالا: قالب</p>'
    if not models:
        body+=f'<div class="m2-msg">در دسته «{e(category)}» هنوز کالایی تعریف نشده است. ابتدا از تعریف محصولات، مدل و رنگ و سایز را ثبت کن.</div>'
        body+=f'<p><a href="{ROOT}/master?category={quote(category)}">تعریف محصولات</a></p>'
    else:
        first=models[0]
        body+=f'<form id="m2-bundle-form" method="post" action="{ROOT}/platforms/{channel}/add">'
        body+=f'<input type="hidden" name="category" value="{e(category)}">'
        body+='<div class="m2-bundle-primary">'
        body+='<div><label>۱. مدل محصول</label><select name="model_key" id="m2-model" required>'
        body+=''.join(f'<option value="{e(m["key"])}">{e(m["title"])}{(" · "+e(m["subtype"])) if m["subtype"] else ""}</option>' for m in models)
        body+='</select></div>'
        body+='<div><label>۲. تعداد در هر بسته</label><select name="pack_qty" id="m2-pack-qty">'+''.join(
            f'<option value="{n}">{n} عددی</option>' for n in range(1,7))+'</select></div>'
        body+='<div><label>عنوان فروش محصول (اختیاری)</label><input type="text" name="title" maxlength="220" placeholder="مثلاً پک سه‌عددی دارما"></div>'
        body+='</div>'
        body+='<h4 class="m2-bundle-label">۳. رنگ هر عدد در بسته</h4><div class="m2-color-slots" id="m2-color-slots">'
        # Render all six positions, disabling unopened slots as a safe form default.
        # JavaScript populates each position from the selected model. Backend
        # validates all positions; no client fields are trusted.
        for position in range(1,7):
            body+=(f'<div class="m2-color-slot" id="m2-slot-{position}"'
                   +('' if position==1 else ' hidden')+'>'
                   f'<label>عدد {position}، رنگ</label>'
                   f'<select name="color_{position}" id="m2-color-{position}"'
                   +('' if position==1 else ' disabled')+'>'
                   +''.join(f'<option value="{e(color)}">{e(color)}</option>' for color in first["colors"])
                   +'</select></div>')
        body+='</div><h4 class="m2-bundle-label">۴. سایزبندی این محصول</h4>'
        body+='<p class="m2-hint">سایزهای موردنظر را تیک بزن. سایزی که یکی از رنگ‌های بسته برای آن تعریف نشده باشد، غیرفعال می‌شود.</p>'
        body+='<div id="m2-bundle-sizes" class="m2-size-checks">'
        body+=''.join(f'<label class="m2-size-check"><input type="checkbox" name="size" value="{e(sz)}"> {e(sz)}</label>'
                      for sz in first["sizes"])
        body+='</div><div class="m2-form-footer"><button class="m2-btn" type="submit">ثبت محصول و سایزهای انتخابی</button></div></form>'
        payload=_json_safe(models)
        body+='<script type="application/json" id="m2-bundle-data">'+payload+'</script>'
        # Safe progressive enhancement: server-rendered fields work for the
        # first model without JS. Script manages dynamic model choices.
        body+="""<script>
(function(){
 const data=document.getElementById('m2-bundle-data');
 if(!data)return;
 let models;
 try{models=JSON.parse(data.textContent);}catch(e){return;}
 const model=document.getElementById('m2-model');
 const qty=document.getElementById('m2-pack-qty');
 const sizeBox=document.getElementById('m2-bundle-sizes');
 const slots=Array.from({length:6},(_,index)=>({
   wrapper:document.getElementById('m2-slot-'+(index+1)),
   select:document.getElementById('m2-color-'+(index+1))
 }));
 function current(){return models.find(item=>item.key===model.value);}
 function redrawSizes(){
   const selected=current();
   if(!selected){sizeBox.replaceChildren();return;}
   const picked=new Set(Array.from(sizeBox.querySelectorAll('input:checked')).map(n=>n.value));
   const colors=slots.filter(s=>!s.select.disabled).map(s=>s.select.value);
   sizeBox.replaceChildren();
   for(const size of selected.sizes){
     // Exact availability is encoded in the model data, not inferred from the
     // union of colors/sizes. Each selected slot must exist at this size.
     const enabled=colors.every(color=>(selected.pairs||[]).some(x=>x.color===color&&x.size===size));
     const item=document.createElement('label');
     item.className='m2-size-check'+(enabled?'':' m2-size-disabled');
     const check=document.createElement('input');
     check.type='checkbox';check.name='size';check.value=size;check.disabled=!enabled;
     check.checked=enabled&&picked.has(size);
     item.append(check,document.createTextNode(' '+size));
     sizeBox.append(item);
   }
 }
 function redrawColors(){
   const selected=current();if(!selected)return;
   const count=parseInt(qty.value,10)||1;
   for(const [index,slot] of slots.entries()){
     const previous=slot.select.value;
     slot.wrapper.hidden=index>=count;slot.select.disabled=index>=count;
     if(index<count){
       slot.select.replaceChildren(...selected.colors.map(color=>{
         const option=document.createElement('option');option.value=color;option.textContent=color;return option;
       }));
       if(selected.colors.includes(previous))slot.select.value=previous;
     }
   }
   redrawSizes();
 }
 model.addEventListener('change',redrawColors);
 qty.addEventListener('change',redrawColors);
 for(const slot of slots)slot.select.addEventListener('change',redrawSizes);
 redrawColors();
})();
</script>"""
    body+='</section>'
    body+=f'<div class="m2-search-block"><form action="{ROOT}/platforms/{channel}" method="get">'
    body+=f'<input type="hidden" name="category" value="{e(category)}">'
    body+=f'<input name="q" value="{e(q)}" placeholder="جستجو در محصولات ثبت‌شده"><button class="m2-btn">جستجو</button></form></div>'
    items=list_bundle_groups(conn,channel,q)
    body+='<section class="m2-card"><h3>فهرست محصولات ثبت‌شده</h3>'
    if not items:body+='<p class="m2-hint">هنوز محصولی در این پلتفرم با این جستجو ثبت نشده است.</p>'
    else:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>محصول</th><th>دسته</th><th>رنگ‌های بسته</th><th>تعداد در بسته</th><th>سایزها</th><th>قیمت‌گذاری</th></tr></thead><tbody>'
        for item in items:
            body+=f'<tr><th>{e(item["title"])}</th><td>{e(item["category"])}</td>'
            body+=f'<td>{e("، ".join(item["colors"]))}</td><td>{item["pack_qty"]}</td><td>{e(item["sizes"] or "—")}</td>'
            body+=f'<td><a href="{ROOT}/pricing/sales?channel={channel}">{item["priced_count"] or 0} از {item["size_count"]} سایز قیمت‌گذاری شده</a></td></tr>'
        body+='</tbody></table></div>'
    body+='</section>'
    legacy=list_listings(conn,channel,max_rows=200)
    if legacy:
        body+=f'<details class="m2-card" style="margin-top:15px"><summary>محصولات ثبت‌شده با ساختار قدیمی ({len(legacy)})</summary>'
        body+='<p class="m2-hint">این رکوردها و فروش‌های قبلی حفظ شده‌اند. برای مدل‌های چندرنگ از فرم جدید استفاده کن؛ تا زمان تطبیق دستی، رکورد قدیمی خودکار به پک چندرنگ تبدیل نمی‌شود.</p></details>'
    return page_with_style(PLATFORMS[channel],body)

def price_page(conn,channel):
    if channel not in SALE_CHANNELS:channel="site"
    body='<h1>قیمت‌گذاری فروش</h1><p class="m2-hint">این صفحه فقط محصولات ثبت‌شده در پلتفرم‌ها را نشان می‌دهد. قیمت هر سایز، قیمت نهایی یک بسته است؛ نه قیمت یک عدد.</p>'
    body+='<div class="m2-tabs">'
    for key,label in (("site","فروش سایت"),("basalam","فروش باسلام"),("mold","فروش قالب")):
        body+=f'<a class="{("current" if key==channel else "")}" href="{ROOT}/pricing/sales?channel={key}">{label}</a>'
    body+='</div>'
    rows=list_bundle_variants(conn,channel)
    if not rows:
        body+=f'<div class="m2-card"><h3>هنوز محصولی برای {e(PLATFORMS[channel])} تعریف نشده است.</h3>'
        body+=f'<a class="m2-btn" href="{ROOT}/platforms/{channel}">تعریف محصول در {e(PLATFORMS[channel])}</a></div>'
    else:
        grouped={}
        for row in rows:grouped.setdefault(row["bundle_id"],[]).append(row)
        for group in grouped.values():
            item=group[0]
            body+=f'<section class="m2-card m2-bundle-price-card"><h3>{e(item["title"])}</h3>'
            body+=f'<p class="m2-hint">{e(item["category"])} · {item["pack_qty"]} عددی · رنگ‌ها: {e("، ".join(item["colors"]))}</p>'
            body+=f'<form method="post" action="{ROOT}/pricing/sales/variants/save">'
            body+=f'<input type="hidden" name="channel" value="{e(channel)}">'
            body+='<div class="m2-price-variants">'
            for sku in group:
                body+=f'<div class="m2-price-variant"><strong>سایز {e(sku["size"])}</strong>'
                body+=f'<div><label>قیمت فروش کل بسته (تومان)</label><input type="number" min="1" name="price_{sku["variant_id"]}" value="{e(sku["price_toman"] if sku["price_toman"] is not None else "")}" placeholder="قیمت ثبت نشده"></div></div>'
            body+='</div><div class="m2-form-footer"><button class="m2-btn">ذخیره قیمت سایزهای این محصول</button></div></form></section>'
    body+=f'<p><a href="{ROOT}/platforms/{channel}">بازگشت به تعریف محصولات {e(PLATFORMS[channel])}</a></p>'
    return page_with_style("قیمت فروش "+PLATFORMS[channel],body)

def daily_sales_page(conn,channel,day=""):
    from .effective_costs import today,valid_date
    from .sister_finance_logic import sales_report,platform_balances
    if channel not in SALE_CHANNELS:raise ValueError("پلتفرم نامعتبر")
    try:
        selected=valid_date(day) if day else today()
        stats=sales_report(conn,channel,selected,selected,limit=200)
    except (ValueError,ImportErrorDetail) as exc:
        return page_with_style("تاریخ نامعتبر",f'<div class="m2-msg">{e(exc)}</div>')
    rows=[x for x in list_bundle_variants(conn,channel) if x["bundle_active"] and x["variant_active"]]
    claim=platform_balances(conn)[channel]["outstanding"]
    body=f'<h1>فروش روزانه {e(PLATFORMS[channel])}</h1>'
    body+='<p class="m2-hint">ثبت سفارش، کسر موجودی، محاسبه هزینه پلتفرم و بهای تمام‌شده و ایجاد طلب از همان پلتفرم، همگی به یک فروش متصل هستند.</p>'
    body+=f'<div class="m2-finance-actions"><a class="m2-btn" href="{ROOT}/finance/accounts">مانده طلب از {e(PLATFORMS[channel])}: {fmt(claim)} تومان</a>'
    body+=f'<a class="m2-btn" href="{ROOT}/finance/sales?channel={channel}">گزارش کامل این پلتفرم</a></div>'
    body+=f'<form class="m2-filters m2-day-filter" method="get" action="{ROOT}/platforms/{channel}/sales"><label>گزارش فروش کدام روز؟</label>'
    body+=f'<div class="m2-fields"><input type="date" name="day" value="{selected}" required><button class="m2-btn" type="submit">نمایش روز</button></div></form>'
    body+='<div class="m2-finance-cards">'
    overview=[("سفارش",stats["orders"],"ردیف"),("تعداد کالای فیزیکی",stats["units"],"عدد"),
              ("فروش ناخالص",stats["gross"],"تومان"),
              ("کارمزد "+PLATFORMS[channel],stats["fees"],"تومان"),
              ("طلب ایجادشده از فروش",stats["net"],"تومان"),
              ("بهای تمام‌شده",stats["cogs_known"],"تومان · موارد دارای بها"),
              ("سود فروش",stats["profit"],"تومان · پس از کارمزد و بهای کالا")]
    for title,value,foot in overview:
        body+=f'<div class="m2-card m2-finance-tile"><small>{e(title)}</small><strong class="m2-finance-value">{fmt(value)}</strong><span class="m2-unit">{e(foot)}</span></div>'
    body+='</div>'
    if stats["unknown_cost_lines"]:
        body+=f'<div class="m2-msg">{stats["unknown_cost_lines"]} ردیف امروز بهای تمام‌شده ندارد؛ تا تکمیل بها، سود کل نامشخص می‌ماند.</div>'
    if channel=="basalam":
        body+='<p class="m2-hint">کارمزد باسلام برابر ۱۵٪ مبلغ ناخالص هر سفارش است. مبلغ قابل‌دریافت = فروش − کارمزد؛ سود = مبلغ قابل‌دریافت − بهای تمام‌شده.</p>'
    else:
        body+='<p class="m2-hint">برای این کانال هزینه پلتفرم دیگری اعلام نشده است؛ فعلاً هزینه ثبت‌شده آن صفر است و هزینه‌ای به‌صورت حدسی ساخته نمی‌شود.</p>'
    body+=f'<div class="m2-card m2-finance-section"><h3>ثبت فروش {e(PLATFORMS[channel])}</h3><form method="post" action="{ROOT}/platforms/{channel}/sales/add" class="m2-fields">'
    body+=f'<div><label>تاریخ فروش</label><input name="sale_date" type="date" value="{selected}" required></div>'
    body+='<div><label>محصول و سایز</label><select name="variant_id" required>'
    body+=''.join(f'<option value="{v["variant_id"]}">{e(v["title"])} · سایز {e(v["size"])} · {e("، ".join(v["colors"]))} · قیمت پک {fmt(v["price_toman"]) if v["price_toman"] else "ثبت نشده"}</option>' for v in rows)
    body+='</select></div><div><label>تعداد بسته فروخته‌شده</label><input type="number" name="packs" min="1" value="1" required></div>'
    body+='<div><label>انبار مبدأ</label><select name="warehouse"><option value="home">خانه</option><option value="khorshid">خورشید</option></select></div>'
    body+='<div><label>شماره سفارش (برای جلوگیری از ثبت تکراری)</label><input name="order_ref" maxlength="100" placeholder="شناسه سفارش"></div>'
    body+='<div><button class="m2-btn" type="submit"'+("" if rows else " disabled") +'>ثبت فروش و کسر موجودی</button></div></form>'
    if not rows:body+=f'<p class="m2-hint"><a href="{ROOT}/platforms/{channel}">اول کالا را در پلتفرم تعریف کن.</a></p>'
    body+='</div>'
    body+='<div class="m2-card m2-finance-section"><h3>ریز فروش‌های روز انتخابی</h3>'
    if stats["lines"]:
        body+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>محصول</th><th>بسته</th><th>عدد کالا</th><th>فروش</th><th>هزینه پلتفرم</th><th>بهای کالا</th><th>طلب ایجادشده</th><th>سود</th></tr></thead><tbody>'
        for r in stats["lines"]:
            body+=f'<tr><th>{e(r["title"])}</th><td>{fmt(r["packs"])}</td><td>{fmt(r["units"])}</td><td>{fmt(r["gross"])}</td><td>{fmt(r["fees"])}</td><td>{fmt(r["cogs"])}</td><td>{fmt(r["net"])}</td><td>{fmt(r["profit"])}</td></tr>'
        body+='</tbody></table></div>'
    else:body+='<p class="m2-hint">برای این روز هنوز فروش ثبت نشده است.</p>'
    body+='</div>'
    body+=f'<p><a href="{ROOT}/finance/movements?section=receipt">ثبت دریافت از {e(PLATFORMS[channel])} در حسابداری</a></p>'
    return page_with_style("فروش روزانه "+PLATFORMS[channel],body)
