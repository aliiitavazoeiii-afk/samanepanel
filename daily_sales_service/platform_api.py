"""Minimal 4-card platform navigation and SKU-linked selling item catalogue."""
from urllib.parse import quote
import json
from .master_v2_ui import family_title
from fastapi import APIRouter,Depends,Form,Request
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
    from .platform_packs_ui import definition_page
    return definition_page(conn,channel,category,q)

@router.post(ROOT+"/platforms/{channel}/add")
async def add_platform(channel:str,request:Request,conn=Depends(conn_dep)):
    try:
        form=await request.form()
        if form.get("model_key"):
            from .platform_packs_v4 import define_bundle
            count=int(form.get("pack_qty") or 0)
            colors=[str(form.get(f"color_{i}","")) for i in range(1,count+1)]
            define_bundle(conn,channel,str(form.get("category") or ""),
                          str(form.get("model_key") or ""),count,colors,
                          form.getlist("size"),str(form.get("title") or ""))
        elif form.get("master_id"):
            # Old single-SKU form compatibility, not advertised in new UI.
            create_listing(conn,channel,form.get("master_id"),form.get("title"),form.get("pack_qty"))
        else:
            raise ImportErrorDetail("مدل، رنگ‌های بسته و سایزهای آن را انتخاب کن.")
    except (ImportErrorDetail,ValueError,TypeError) as exc:return error_page(exc,channel)
    return RedirectResponse(ROOT+"/platforms/"+channel,status_code=303)

@router.get(ROOT+"/platforms/{channel}/sales")
def sales_page(channel:str,conn=Depends(conn_dep)):
    if channel not in SALE_CHANNELS:return error_page("این پلتفرم برای ثبت فروش آماده نیست.")
    from .platform_packs_ui import daily_sales_page
    return daily_sales_page(conn,channel)

@router.post(ROOT+"/platforms/{channel}/sales/add")
async def post_sale(channel:str,request:Request,conn=Depends(conn_dep)):
    try:
        form=await request.form()
        values={"packs":form.get("packs"),"warehouse":form.get("warehouse"),
                "sale_date":form.get("sale_date"),"order_ref":form.get("order_ref") or ""}
        if form.get("variant_id"):
            from .platform_packs_v4 import book_bundle_sale
            book_bundle_sale(conn,channel,form["variant_id"],**values)
        elif form.get("listing_id"):
            # Existing v3 sales remain available to integrations, but the new
            # user interface only shows size/pack variants created by V4.
            book_sale(conn,channel,form["listing_id"],**values)
        else:
            raise ImportErrorDetail("محصول پلتفرم را انتخاب کن.")
    except (ImportErrorDetail,ValueError,TypeError) as exc:return error_page(exc,channel)
    return RedirectResponse(ROOT+"/platforms/"+channel+"/sales",status_code=303)
