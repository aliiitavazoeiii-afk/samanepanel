"""HTML presentation shared by product master, pricing and Darma-style inventory."""
from collections import defaultdict
from html import escape
from urllib.parse import quote

from .app import ROOT, e, fmt
from .master_engine import CATEGORIES
from .master_v2_logic import BODY_TYPES, SIZES, cost_for, list_models, sku_rows

STYLE="""
<style>
.m2-shell{max-width:1500px;margin:auto}.m2-hero{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.m2-tabs{display:flex;gap:9px;flex-wrap:wrap;margin:18px 0 22px}
.m2-tabs a{border:1px solid #385773;border-radius:11px;padding:9px 15px;text-decoration:none;color:#dbe8f5;background:#112640}
.m2-tabs a.current{background:#df7a2b;color:#091a2b;font-weight:800;border-color:#fdb476}
.m2-filters{padding:18px;margin-bottom:20px;border-radius:16px;border:1px solid #294766;background:#112841}
.m2-filters form{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));align-items:end;gap:12px}
.m2-filters label{display:block;margin:0 0 7px;color:#c5d5e7}
.m2-filters select,.m2-filters input,.m2-field{width:100%;min-width:0;background:#142d49!important;border:1px solid #365874!important;color:#fff!important;border-radius:10px;padding:10px}
.m2-filters button,.m2-btn{border:1px solid #ef914c;background:#e77d2b;color:#0b1c2c!important;border-radius:10px;padding:10px 16px;text-decoration:none;cursor:pointer;font-weight:800}
.m2-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.m2-card{border:1px solid #2c4965;border-radius:16px;background:linear-gradient(135deg,#142e48,#0e2036);padding:19px;min-width:0}
.m2-card h3{font-size:17px;color:#fff;margin:0 0 14px}.m2-card small,.m2-hint{color:#afc1d5}
.m2-shell{direction:rtl;width:100%;min-width:0;padding-bottom:24px}
.m2-shell>h1{font-size:1.6rem;font-weight:850;margin:0 0 8px}
.m2-shell>p.m2-hint{margin-bottom:18px}
.m2-shell .m2-hero{margin:0 0 14px}
.m2-shell .m2-hero h2{font-size:1.15rem;font-weight:800;margin:0}
.m2-filters form>div{min-width:0}
.m2-filters form>div:last-child{display:flex;align-items:flex-end}
.m2-filters form>div:last-child button{width:auto}
.m2-section h3{display:flex;align-items:center;gap:8px}
.m2-family-title{font-size:1.15rem;font-weight:800;margin:22px 0 8px;padding:12px 16px;border-radius:12px;border-right:3px solid #fb6514;background:rgba(24,50,79,.55)}
.m2-hero .m2-btn{white-space:nowrap}
.m2-list .m2-card{display:flex;flex-direction:column;gap:8px}
.m2-list .m2-card .m2-tags{margin:0 0 7px}
@media(min-width:900px){.m2-filters form{grid-template-columns:minmax(220px,1.3fr) repeat(2,minmax(160px,1fr)) auto}.m2-filters form>div:last-child{align-self:end}}
@media(max-width:899px){.m2-filters form{grid-template-columns:repeat(2,minmax(0,1fr))}}

.m2-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;align-items:end}
.m2-fields label{font-size:12px;color:#cbd9e7;display:block}
.m2-fields input,.m2-fields select{width:100%;min-width:0;background:#142d49!important;color:#fff!important;border:1px solid #365874!important;padding:10px;border-radius:9px}
.m2-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.m2-tags{display:flex;flex-wrap:wrap;gap:7px}.m2-tag{background:#21425d;border-radius:7px;padding:4px 9px;font-size:12px;color:#eaf2fa}
.m2-table-scroll{width:100%;overflow:auto;border:1px solid #294867;border-radius:10px}
.m2-table{border-collapse:separate;border-spacing:0;width:100%;min-width:600px;color:#e9f3fd;font-size:13px;text-align:center}
.m2-table th,.m2-table td{border:1px solid #29435b;padding:11px 13px;white-space:nowrap;text-align:center!important;background:#10263c}
.m2-table th{background:#1a3855;color:#fff;font-weight:800}
.m2-table th:first-child{position:sticky;right:0;z-index:2;min-width:140px;text-align:right!important;background:#213b56}
.m2-table .m2-subtotal td,.m2-table .m2-subtotal th{background:#3b2f2e!important;font-weight:800}
.m2-table .m2-capital td,.m2-table .m2-capital th{background:#193e3b!important;font-weight:800}
.m2-table .m2-zero{background:#791622!important;color:#fff;font-weight:900}
.m2-table .m2-low{background:#472633!important;color:#ffd5d8;font-weight:700}
.m2-table .m2-empty{background:#0d2237;color:#627d96}
.m2-section{margin:25px 0}.m2-section h3{font-size:20px;color:#f8fafc;margin-bottom:13px}
.m2-unit{font-size:12px;color:#9cb2c8}
.m2-operation-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.m2-operation-color{background:#15334f;border:1px solid #31516b;border-radius:11px;padding:13px}
.m2-operation-color strong{display:block;margin-bottom:6px}
.m2-operation-color input{width:100%;background:#11273f!important;border:1px solid #345574!important;color:#fff!important}
.m2-history{width:100%;overflow:auto}.m2-history table{width:100%;min-width:700px;border-collapse:collapse}
.m2-history th,.m2-history td{padding:10px;border-bottom:1px solid #2d4860;text-align:right;color:#e4effb;font-size:12px}
.m2-msg{padding:13px 16px;background:#533c23;border:1px solid #916d45;border-radius:9px;margin:15px 0;color:#ffdfac}
.m2-cost-stack{display:flex;flex-direction:column;gap:14px;margin-top:18px;width:100%}
.m2-cost-row{width:100%;max-width:none;display:block}
.m2-cost-line{display:grid;grid-template-columns:minmax(180px,1.4fr) minmax(160px,1fr) minmax(155px,1fr) auto;align-items:end;gap:14px;padding:15px 0;border-top:1px solid #314962}
.m2-cost-caption{display:flex;flex-direction:column;gap:5px;min-width:0}
.m2-cost-caption strong{font-size:15px;color:#fff}.m2-cost-caption span{font-size:12px;color:#a7bed1}
.m2-cost-line input{width:100%;max-width:none;border:1px solid #35536d!important;background:#142e4a!important;color:#fff!important;border-radius:9px;padding:10px}
.m2-cost-line label{display:block;margin-bottom:6px;color:#c5d5e7;font-size:12px}
.m2-platform-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:20px 0}
.m2-platform-card{background:linear-gradient(145deg,#1c3852,#11283f);border:1px solid #3d5369;border-radius:17px;padding:24px 15px;display:flex;flex-direction:column;gap:20px;align-items:start;min-height:145px}
.m2-platform-card:hover{border-color:#e77d2b;transform:translateY(-2px)}
.m2-platform-card h3{color:#f6f9fe;font-size:20px;margin:0}.m2-platform-dot{width:46px;height:46px;border:1px solid #52708b;background:#264760;color:#ffbe82;display:grid;place-items:center;border-radius:13px;font-weight:900;font-size:23px}
.m2-platform-form{margin-top:16px}.m2-search-block{margin:16px 0;padding:12px;background:#11273e;border-radius:12px}
.m2-search-block form{display:flex;gap:10px;flex-wrap:wrap}.m2-search-block input{flex:1 1 240px;padding:10px;border:1px solid #375775;background:#142f49;color:#fff}
.m2-inline-filter{display:flex;gap:12px;align-items:center;margin-bottom:15px;flex-wrap:wrap}.m2-inline-filter select{background:#17324a;color:white;padding:9px;border:1px solid #41627b}

.m2-bundle-definition{padding:24px!important}
.m2-bundle-definition>h3{font-size:20px;margin-bottom:18px}
.m2-bundle-primary{display:grid;grid-template-columns:minmax(220px,1.4fr) minmax(155px,.7fr) minmax(240px,1fr);gap:15px;margin:12px 0 22px;align-items:end}
.m2-bundle-primary label,.m2-color-slot label{display:block;margin:0 0 8px;color:#c4d7e7;font-size:12px;font-weight:700}
.m2-bundle-primary input,.m2-bundle-primary select,.m2-color-slot select{
 width:100%;min-width:0;max-width:none;color:#f7fbff!important;
 background:#122c45!important;border:1px solid #3d607c!important;
 border-radius:11px;padding:11px 13px}
.m2-bundle-label{font-size:15px;font-weight:800;color:#f6f9ff;letter-spacing:0;margin:22px 0 13px}
.m2-color-slots{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.m2-color-slot{min-width:0;border:1px solid #345570;border-radius:12px;padding:12px;background:#18354f}
.m2-color-slot[hidden],.m2-picker-extra[hidden]{display:none!important}
.m2-size-checks{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
.m2-size-check{display:flex!important;align-items:center;gap:7px;border:1px solid #375a76;border-radius:12px;
 background:#14324f;padding:11px 16px;color:#fff!important;cursor:pointer;font-weight:700}
.m2-size-check input{width:16px;height:16px;accent-color:#f59b5a;margin:0;max-width:none}
.m2-size-check:has(input:checked){border-color:#f59b5a;background:#483b35}
.m2-size-disabled{opacity:.4;cursor:not-allowed}
.m2-form-footer{display:flex;justify-content:flex-end;margin-top:18px}
.m2-bundle-price-card{margin:15px 0;width:100%}
.m2-bundle-price-card>h3{font-size:18px}
.m2-price-variants{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:15px}
.m2-price-variant{min-width:0;display:flex;flex-direction:column;gap:10px;padding:15px;border-radius:13px;background:#193550;border:1px solid #355572}
.m2-price-variant strong{font-size:16px;color:#fff}
.m2-price-variant label{font-size:12px;color:#a9c1d5;display:block;margin-bottom:6px}
.m2-price-variant input{width:100%;min-width:0;max-width:none;color:#fff!important;
background:#112a44!important;border:1px solid #365671!important;padding:10px;border-radius:10px}
@media(max-width:880px){.m2-bundle-primary{grid-template-columns:repeat(2,minmax(0,1fr))}.m2-color-slots{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:540px){.m2-bundle-primary{grid-template-columns:1fr}.m2-color-slots{grid-template-columns:1fr 1fr}.m2-bundle-definition{padding:15px!important}.m2-price-variants{grid-template-columns:1fr 1fr}.m2-size-check{padding:10px 13px}}


.m2-finance-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0 21px}
.m2-finance-tile{min-height:130px;display:flex;flex-direction:column;justify-content:space-between;gap:12px;border-color:#385470}
.m2-finance-tile small{font-size:12px;color:#abc0d4;font-weight:700}
.m2-finance-value{font-size:clamp(18px,2.25vw,28px);line-height:1.2;direction:ltr;text-align:right;color:#fefefe;font-weight:900;font-variant-numeric:tabular-nums}
.m2-finance-tile .m2-unit{color:#9fb8ce}
.m2-finance-section{margin:16px 0 20px}
.m2-finance-section h3{margin-bottom:16px}
.m2-finance-section .m2-fields{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.m2-finance-section .m2-fields>div{min-width:0}
.m2-finance-form{margin-top:15px;padding-top:15px;border-top:1px solid #36516b}
.m2-finance-actions{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}
.m2-finance-actions .m2-btn{display:inline-flex;align-items:center}
.m2-finance-cancel{border:1px solid #c26767!important;background:#512c37!important;color:#ffd7d7!important;border-radius:7px;padding:5px 10px;cursor:pointer}
.m2-day-filter{display:block;margin-top:15px}
.m2-day-filter>.m2-fields{display:flex;align-items:end;gap:10px;flex-wrap:wrap;margin-top:10px}
.m2-day-filter>.m2-fields input{max-width:240px}
.m2-day-filter>.m2-fields button{min-width:130px}
@media(max-width:1150px){.m2-finance-cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:780px){.m2-finance-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:480px){.m2-finance-cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.m2-finance-tile{padding:13px;min-height:112px}.m2-finance-value{font-size:19px}.m2-finance-actions .m2-btn{font-size:12px;padding:8px 10px}}

@media(max-width:950px){.m2-platform-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.m2-cost-line{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.m2-cost-line{grid-template-columns:1fr}.m2-platform-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.m2-platform-card{padding:14px;min-height:115px}.m2-platform-card h3{font-size:16px}}

@media(max-width:700px){.m2-filters form{grid-template-columns:1fr}.m2-tabs{flex-wrap:nowrap;overflow:auto}.m2-tabs a{white-space:nowrap}.m2-card{padding:15px}.m2-table th,.m2-table td{padding:10px}.m2-hero h1{font-size:20px}}

/* Darma-inspired single-day DigiKala order-import and reporting */
.m2-dk-head{margin-bottom:18px}.m2-dk-head h1{font-size:1.65rem}
.m2-dk-upload{margin-bottom:20px!important;border-color:#a66b3c!important;background:linear-gradient(125deg,#223348,#172839)!important}
.m2-dk-upload h3{font-size:19px!important;margin:7px 0 10px!important}
.m2-dk-upload-head{margin-bottom:14px}.m2-dk-upload .m2-hint{max-width:950px;line-height:1.9;margin:0}
.m2-dk-upload-form{display:grid;grid-template-columns:minmax(165px,.75fr) minmax(180px,1fr) minmax(260px,2fr) auto;gap:12px;align-items:end;margin:13px 0 15px}
.m2-dk-upload-form label{display:block;margin-bottom:7px;color:#cbdcec;font-size:12px;font-weight:700}
.m2-dk-upload-form input,.m2-dk-upload-form select{background:#122b44!important;color:#fff!important;border:1px solid #45647e!important;border-radius:10px;padding:10px;max-width:100%;width:100%}
.m2-dk-upload-form input[type=file]{min-height:44px;font-size:13px}
.m2-dk-upload-form .m2-btn{white-space:nowrap;min-height:44px}
.m2-dk-daybar{display:flex;align-items:end;justify-content:space-between;gap:20px;margin:20px 0 15px}
.m2-dk-daybar h3{font-size:19px;font-weight:900;color:#fff;margin:0}
.m2-dk-daybar form{display:flex;gap:9px;align-items:end}
.m2-dk-daybar .m2-fields input{min-width:150px}
.m2-dk-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:20px}
.m2-dk-kpi{min-height:125px;display:flex;flex-direction:column;justify-content:space-between;gap:11px}
.m2-dk-kpi small{font-size:12px;color:#acc1d5;font-weight:800}
.m2-dk-kpi strong{font-size:clamp(20px,2vw,29px);color:#fff;direction:ltr;text-align:right;font-variant-numeric:tabular-nums}
.m2-dk-section{margin:18px 0}.m2-dk-section h3{font-size:19px!important;font-weight:850}
.m2-dk-brand-filter,.m2-dk-size-filter{display:flex;flex-wrap:wrap;gap:9px;margin:12px 0 16px}
.m2-dk-brand-filter a,.m2-dk-size-filter a{border:1px solid #3d5670;background:#172f45;border-radius:11px;padding:9px 15px;color:#d7e8f5;text-decoration:none;font-size:13px;font-weight:750}
.m2-dk-brand-filter a.active,.m2-dk-size-filter a.active{background:#e77d2b;color:#101e2b;border-color:#e77d2b}
.m2-dk-color{font-size:12px;color:#bccee1;margin-top:8px;white-space:normal}
.m2-dk-code{font-size:11px;color:#809eb7;margin-top:6px;white-space:normal}
.m2-dk-success{border:1px solid #32866b;background:#153b35;color:#c7f8df;border-radius:11px;padding:13px 17px;margin:15px 0}
.m2-dk-confirm{margin:20px 0}.m2-dk-confirm .m2-btn{padding:14px 20px}
.m2-dk-back{display:inline-block;color:#c6deed;padding:8px 0}
@media(max-width:1050px){.m2-dk-upload-form{grid-template-columns:repeat(2,minmax(0,1fr))}.m2-dk-upload-input{grid-column:span 2}.m2-dk-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.m2-dk-upload-form{grid-template-columns:1fr}.m2-dk-upload-input{grid-column:auto}.m2-dk-summary{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.m2-dk-kpi{padding:12px;min-height:110px}.m2-dk-kpi strong{font-size:19px}.m2-dk-daybar{align-items:stretch;flex-direction:column}.m2-dk-daybar form{width:100%}.m2-dk-daybar .m2-fields{flex:1}}
</style>
"""

def with_style(page_response):
    from fastapi.responses import HTMLResponse
    html=page_response.body.decode("utf-8").replace("</style>","</style>"+STYLE,1)
    return HTMLResponse(html)

def category_tabs(endpoint,category):
    return '<div class="m2-tabs">'+''.join(
        f'<a class="{("current" if cat==category else "")}" href="{ROOT}{endpoint}?category={quote(cat)}">{e(cat)}</a>'
        for cat in CATEGORIES)+'</div>'

def category_option(category):
    return ''.join(f'<option value="{e(c)}"'+(' selected' if category==c else '')+'>'+e(c)+'</option>'
                   for c in CATEGORIES)

def group_options(models,model_id=None):
    return '<option value="">تمام مدل‌ها</option>'+''.join(
      f'<option value="{m["representative"]}"'+(' selected' if str(model_id or '')==str(m["representative"]) else '')+'>'
      +e(m["title"]+(" · "+m["subtype"] if m["subtype"] else ""))+'</option>'
      for m in models)

def family_title(sku):
    """Only a display grouping: never merge or change underlying SKU identities."""
    title=str(sku["title"])
    color=str(sku["color"])
    suffix=" - "+color
    return title[:-len(suffix)] if color not in ("","-") and title.endswith(suffix) else title

def inventory_grid(conn,skus,location,label):
    colors=sorted({s["color"] for s in skus})
    sizes=sorted({s["size"] for s in skus},key=lambda x:(["XS","S","M","L","XL","XXL","2XL","3XL","4XL","کوچک","متوسط","بزرگ"].index(x)
       if x in ["XS","S","M","L","XL","XXL","2XL","3XL","4XL","کوچک","متوسط","بزرگ"] else 999,x))
    keyed={(s["color"],s["size"]):s for s in skus}
    sums=[0]*len(sizes)
    worth=[0]*len(sizes)
    grand=0;capital=0;unknown=set()
    col={"total":None,"home":"seller_stock","khorshid":"khorshid_stock"}[location]
    rows=[]
    for color in colors:
        cells=[];row_total=0
        for idx,size in enumerate(sizes):
            x=keyed.get((color,size))
            if not x:
                cells.append('<td class="m2-empty">—</td>');continue
            qty=int(x["seller_stock"])+int(x["khorshid_stock"]) if col is None else int(x[col])
            cs=cost_for(conn,x)
            value=(cs or 0)*qty
            if cs is None and qty>0:unknown.add(idx)
            row_total+=qty;sums[idx]+=qty;worth[idx]+=value;capital+=value
            css="m2-zero" if qty==0 else ("m2-low" if qty<10 else "")
            cells.append(f'<td class="{css}" title="بهای تمام‌شده هر عدد: {fmt(cs) if cs is not None else "نامشخص"}">{fmt(qty)}</td>')
        grand+=row_total
        rows.append(f'<tr><th>{e(color)}</th>'+''.join(cells)+f'<td><b>{fmt(row_total)}</b></td></tr>')
    foot='<tr class="m2-subtotal"><th>مجموع</th>'+''.join(f'<td>{fmt(n)}</td>' for n in sums)+f'<td>{fmt(grand)}</td></tr>'
    if location=="total":
        capital_label='نامشخص' if unknown else fmt(capital)+' <small>تومان</small>'
        foot+='<tr class="m2-capital"><th>ارزش سرمایه</th>'+''.join(f'<td>{fmt(n) if idx not in unknown else "نامشخص"}</td>' for idx,n in enumerate(worth))+f'<td>{capital_label}</td></tr>'
    html=f'<div class="m2-section"><h3>{e(label)}</h3><div class="m2-unit">جدول را به چپ و راست بکش</div>'
    html+='<div class="m2-table-scroll"><table class="m2-table"><thead><tr><th>رنگ / مدل</th>'+''.join(f'<th>{e(s)}</th>' for s in sizes)+'<th>کل</th></tr></thead><tbody>'+''.join(rows)+'</tbody><tfoot>'+foot+'</tfoot></table></div></div>'
    return html

def page_with_style(title,content,description=""):
    from .app import page
    return with_style(page(title,'<div class="m2-shell">'+content+'</div>',description))
