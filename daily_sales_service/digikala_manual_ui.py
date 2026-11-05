"""Compact inline color-slot selectors for unlinked DigiKala variants."""
from .app import ROOT,e
from .digikala_manual_pack import listing_scope,sku_options

STYLES = """
<style>
.dk-pick-form{margin:0;max-width:350px;min-width:255px;border:1px solid #456481;border-radius:12px;padding:9px;background:#17314b}
.dk-pick-form summary{cursor:pointer;color:#ffcf98;font-weight:800;list-style-position:inside;font-size:12px}
.dk-pick-form[open]{border-color:#e89b5f;background:#1b364f}
.dk-pick-hint{font-size:11px;color:#b7cada;margin:9px 0;line-height:1.7}
.dk-pick-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.dk-pick-slot{min-width:0}
.dk-pick-slot label{color:#e3eff9;display:block;font-size:11px;margin-bottom:4px}
.dk-pick-slot select{width:100%!important;min-width:0;max-width:100%;padding:8px 5px!important;font-size:12px}
.dk-pick-button{margin-top:10px;width:100%}
.dk-pick-unavailable{font-size:11px;color:#ffb8a6;margin:5px 0;max-width:290px}
.dk-pick-form input[type=hidden]{display:none}
@media(max-width:720px){.dk-pick-form{min-width:225px}.dk-pick-grid{grid-template-columns:1fr 1fr}}
</style>
"""

def build_manual_form(conn,variant,cache=None):
    """An ordinary HTML POST form; Django proxy injects its CSRF token."""
    scope=listing_scope(variant)
    if "error" in scope:
        return ('<span style="color:#ffa460;font-size:12px">بدون اتصال</span>'
                '<p class="dk-pick-unavailable">'+e(scope["error"])+'</p>')
    key=(scope["category"],scope["subtype"],scope["size"])
    if cache is None:cache={}
    if key not in cache:cache[key]=sku_options(conn,scope)
    candidates=cache[key]
    if not candidates:
        return ('<span style="color:#ffa460;font-size:12px">بدون اتصال</span>'
                '<p class="dk-pick-unavailable">برای '+e(scope["category"])+'، سایز '+e(scope["size"])+
                ' هنوز محصول رنگ‌بندی‌شده‌ای در «تعریف محصولات» وجود ندارد.</p>')
    quantity=scope["pack_qty"]
    title=(f'انتخاب رنگ‌های پک {quantity} عددی' if quantity>1
           else 'انتخاب رنگ کالا')
    html='<details class="dk-pick-form"><summary>'+e(title)+'</summary>'
    html+=f'<form action="{ROOT}/catalog/parts/save" method="post">'
    html+=f'<input type="hidden" name="variant_id" value="{int(variant["variant_id"])}">'
    html+='<p class="dk-pick-hint">'+e(scope["category"])+' · سایز '+e(scope["size"])
    html+=(' · '+e(scope["subtype"]) if scope["subtype"] else '')
    html+='<br>برای هر عدد داخل بسته یک رنگ از محصولات اصلی انتخاب کن. رنگ تکراری هم مجاز است.</p>'
    html+='<div class="dk-pick-grid">'
    for i in range(1,quantity+1):
        html+=f'<div class="dk-pick-slot"><label for="dk-pick-{int(variant["variant_id"])}-{i}">عدد {i} · رنگ</label>'
        html+=f'<select id="dk-pick-{int(variant["variant_id"])}-{i}" name="part_id" required>'
        html+='<option value="" selected disabled>انتخاب رنگ</option>'
        for m in candidates:
            variant_label=(str(m["color"])+(f' · {m["subtype"]}' if m["subtype"] else '')+
                          (f' · {m["title"]}' if m["title"] else '')+
                          f' (#{m["id"]})')
            html+=f'<option value="{int(m["id"])}">{e(variant_label)}</option>'
        html+='</select></div>'
    html+='</div><button class="dk-pick-button" type="submit">ثبت اتصال به موجودی</button></form></details>'
    return html
