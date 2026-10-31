"""Standalone UI/API for second Digikala seller panel; mount behind TLS reverse proxy."""
from __future__ import annotations
import csv, hmac, io, os
from datetime import date,datetime,timezone
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from .engine import (BASE, DEFAULT_SETTINGS, ImportErrorDetail, dbconnect, init_db, create_preview,
                     commit_preview, report, set_cost, set_setting, settings_for, xlsx_rows, money, normalize)

ROOT='/daily-sales'; DB=os.environ.get('SALES_DB_PATH','/data/sales.sqlite3')
security=HTTPBasic(auto_error=False)
app=FastAPI(title='سامانه فروش و انبار پنل خواهر',docs_url=None,redoc_url=None,openapi_url=None)

@app.on_event('startup')
def startup():
 password=os.getenv('SALES_ADMIN_PASSWORD','')
 if len(password)<16 or password=='REPLACE_WITH_LONG_RANDOM_SECRET':
  raise RuntimeError('Set a unique SALES_ADMIN_PASSWORD (at least 16 characters) before starting')
 Path(DB).parent.mkdir(parents=True,exist_ok=True)
 init_db(DB).close()

@app.middleware('http')
async def csrf_origin_guard(request:Request,call_next):
 if request.method in ('POST','PUT','PATCH','DELETE'):
  origin=request.headers.get('origin') or request.headers.get('referer')
  if origin:
   parsed=urlsplit(origin)
   host=request.headers.get('host','')
   if not parsed.netloc or parsed.netloc.lower()!=host.lower():
    return JSONResponse({'detail':'Cross-origin form submission rejected'},status_code=403)
 return await call_next(request)

def authorize(creds:HTTPBasicCredentials|None=Depends(security)):
 user=os.getenv('SALES_ADMIN_USER','admin');password=os.getenv('SALES_ADMIN_PASSWORD','')
 if not creds or not password or not (hmac.compare_digest(creds.username,user) and hmac.compare_digest(creds.password,password)):
  raise HTTPException(status_code=401,detail='Unauthorized',headers={'WWW-Authenticate':'Basic realm="Daily Sales"'})

def conn_dep(_=Depends(authorize)):
 con=dbconnect(DB)
 try:yield con
 finally:con.close()

STYLE='''
:root{color-scheme:light;--ink:#182337;--navy:#132c42;--muted:#728293;--bg:#f4f7fa;--line:#e4eaf0;--blue:#1273c4}
*{box-sizing:border-box}body{font-family:Tahoma,Arial,sans-serif;direction:rtl;margin:0;color:var(--ink);background:var(--bg);line-height:1.8}
header{background:#fff;border-bottom:1px solid var(--line);padding:16px max(20px,calc((100vw - 1250px)/2));display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px}
header b{font-size:19px}nav{display:flex;gap:8px;flex-wrap:wrap}nav a{color:var(--navy);border:1px solid var(--line);background:#f9fbfd;text-decoration:none;border-radius:11px;padding:6px 14px;font-size:13px}
main{max-width:1250px;margin:26px auto;padding:0 18px}.hero{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}
h1{font-size:25px;margin:0}p{margin:4px 0;color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:14px}
.card,.panel{background:#fff;border:1px solid var(--line);border-radius:17px;padding:20px;box-shadow:0 5px 20px #16263e07}.card small{display:block;color:var(--muted)}.card strong{font-size:24px;display:block;direction:ltr;text-align:right}.card.warn{border-color:#f1cf9c}.panel{margin-top:18px}
label{font-size:13px;display:block;margin-bottom:5px;color:#536579}input,select,button{font:inherit;border-radius:10px;padding:10px 12px;border:1px solid #dbe3ea;background:white;max-width:100%}
input[type=file]{width:100%}button,.button{background:var(--navy);border:1px solid var(--navy);color:#fff;cursor:pointer;text-decoration:none;padding:10px 16px;border-radius:10px;display:inline-block}
button:hover,.button:hover{background:#245075}.forms{display:flex;gap:15px;align-items:end;flex-wrap:wrap}.forms>*{flex:1 1 180px}.forms button{flex:0 0 auto}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:11px;text-align:right;vertical-align:top}th{background:#f8fafc;color:#50657b;white-space:nowrap}td.num{text-align:left;direction:ltr;white-space:nowrap}td.title{min-width:260px;max-width:560px} .scroll{overflow:auto}
.notice{background:#fff8e9;border:1px solid #efd9b3;padding:12px 15px;border-radius:11px;margin:15px 0}.error{background:#fff1f0;border-color:#edb5b0}.ok{background:#eef8f1;border-color:#b9dfc5}
.faint{color:var(--muted)}footer{margin:40px auto;text-align:center;color:#8795a2;font-size:12px}code{direction:ltr;display:inline-block}
@media(max-width:650px){header{padding:14px}h1{font-size:20px}.card strong{font-size:19px}th,td{padding:8px}.panel{padding:13px}}
'''

def fmt(n):return '—' if n is None else f'{int(n):,}'
def e(x):return escape(str(x if x is not None else ''))
def notice(content,kind='notice'):return f'<div class="notice {kind}">{content}</div>'
def table(headers,body):return '<div class="scroll"><table><thead><tr>'+''.join(f'<th>{e(x)}</th>' for x in headers)+'</tr></thead><tbody>'+body+'</tbody></table></div>'
def tr(cells):return '<tr>'+''.join(f'<td class="{cls}">{cell}</td>' for cell,cls in cells)+'</tr>'
def page(title,body,desc=''):
 nav=[('داشبورد',ROOT+'/'),('ورود فروش',ROOT+'/import'),('تعریف محصولات اصلی',ROOT+'/master'),('موجودی کالا',ROOT+'/master/stock'),('پلتفرم‌ها',ROOT+'/platforms'),('گزارش جامع سرمایه',ROOT+'/capital-report'),('تنظیمات مالی',ROOT+'/settings')]
 return HTMLResponse('''<!doctype html><html lang="fa"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+e(title)+''' | فروش روزانه</title><style>'''+STYLE+'''</style></head><body><header><b>فروش روزانه · پنل دوم دیجی‌کالا</b><nav>'''+''.join(f'<a href="{p}">{n}</a>' for n,p in nav)+'''</nav></header><main><div class="hero"><div><h1>'''+e(title)+'''</h1><p>'''+e(desc)+'''</p></div></div>'''+body+'''</main><footer>هزینه‌ها به تومان هستند • نرخ‌ها و بهای تمام‌شده در لحظه ثبت فروش فریز می‌شوند</footer></body></html>''')

def fail(err):return page('خطای عملیات',notice(e(err),'error')+f'<a class="button" href="{ROOT}/import">بازگشت به ورود فروش</a>')

@app.get(ROOT+'/healthz')
def health():return {'ok':True}

@app.get(ROOT+'/',response_class=HTMLResponse)
def dashboard(request:Request,start:str|None=None,end:str|None=None,conn=Depends(conn_dep)):
 stats=report(conn,start,end)
 cards=[('فروش ناخالص',fmt(stats['gross'])+' تومان'),('هزینه دیجی‌کالا',fmt(stats['fee'])+' تومان'),('دریافتی پس از دیجی‌کالا',fmt(stats['net_after_digikala'])+' تومان'),('سود پس از بهای تمام‌شده',fmt(stats['profit'])+' تومان' if stats['profit'] is not None else 'نامشخص'),('تعداد فروخته‌شده',fmt(stats['units'])),('ردیف فاقد بهای تمام‌شده',fmt(stats['unknown_cost_lines']))]
 body='<div class="grid">'+''.join(f'<div class="card"><small>{e(k)}</small><strong>{e(v)}</strong></div>' for k,v in cards)+'</div>'
 from .platform_catalog import PLATFORMS,sale_summary
 platform_stats=sale_summary(conn,start,end)
 platform_rows=''
 for channel in ('basalam','site','mold'):
  st=platform_stats.get(channel,{})
  platform_rows+=tr([(e(PLATFORMS[channel]),'title'),(fmt(st.get('orders',0)),'num'),
      (fmt(st.get('units',0)),'num'),(fmt(st.get('gross',0)),'num'),
      ('نامشخص؛ کارمزد هنوز تعریف نشده','title')])
 body+='<div class="panel"><h3>فروش ثبت‌شده پلتفرم‌های دیگر</h3>'+table(
  ['پلتفرم','سفارش','تعداد کالای فیزیکی','فروش ناخالص (تومان)','سود خالص'],
  platform_rows)+'</div>'

 if stats['unknown_cost_lines']:body+=notice(f"محاسبه سود قطعی نیست: {stats['unknown_cost_lines']} ردیف فروش هنوز بهای تمام‌شده ندارد. «دریافتی پس از دیجی‌کالا» سود نیست.")
 body+=f'''<div class="panel"><form class="forms" method="get"><div><label>از تاریخ (میلادی)</label><input type="date" name="start" value="{e(start or '')}"></div><div><label>تا تاریخ (میلادی)</label><input type="date" name="end" value="{e(end or '')}"></div><button type="submit">نمایش گزارش</button></form></div>'''
 catrows=''.join(tr([(e(cat),'title'),(fmt(v['units']),'num'),(fmt(v['gross']),'num'),(fmt(v['fee']),'num'),(fmt(v['profit_known']) if not v['unknown_cost_lines'] else 'نامشخص','num')]) for cat,v in stats['categories'].items())
 body+='<div class="panel"><h3>گزارش تفکیک گروه کالا</h3>'+table(['گروه','تعداد','فروش','هزینه دیجی‌کالا','سود'],catrows)+'</div>'
 rows=''.join(tr([(e(r['sale_date']),'num'),(e(r['source']),'num'),(e(r['variant_id']),'num'),(e(r['title']),'title'),(fmt(r['qty']),'num'),(fmt(r['gross']),'num'),(fmt(r['total_fee']),'num'),(fmt(r['profit']),'num')]) for r in stats['rows'][:300])
 body+='<div class="panel"><h3>ریز فروش‌ها (حداکثر ۳۰۰ ردیف)</h3>'+table(['تاریخ','مبدأ موجودی','کد تنوع','محصول','تعداد','فروش','هزینه دیجی‌کالا','سود'],rows)+'</div>'
 body+=f'<div class="panel"><a href="{ROOT}/api/report.csv">دریافت CSV فروش‌ها</a></div>'
 return page('داشبورد فروش روزانه',body,'تفکیک فروش، کارمزد دیجی‌کالا، موجودی و سود واقعی')

@app.get(ROOT+'/import',response_class=HTMLResponse)
def import_page(_=Depends(authorize)):
 body=notice('ابتدا پیش‌نمایش می‌گیری؛ تا تأیید نهایی هیچ موجودی کم نمی‌شود. تکرار فایل برای همان تاریخ و مبدأ جایگزین فروش قبلی می‌شود، نه فروش جدید.')
 body+=f'''<div class="panel"><h3>بارگذاری فایل‌های فروش روزانه</h3><form method="post" action="{ROOT}/preview" enctype="multipart/form-data"><div class="forms"><div><label>تاریخ فروش (میلادی)</label><input required type="date" name="sale_date" value="{date.today().isoformat()}"></div><div><label>کسر از کدام انبار؟</label><select name="source"><option value="seller">خانه</option><option value="khorshid">خورشید</option></select></div><div><label>فایل XLSX (امکان انتخاب چند فایل)</label><input name="files" type="file" required multiple accept=".xlsx"></div><button type="submit">نمایش پیش‌نمایش</button></div></form></div>'''
 body+=notice('فایل مرجع موجودی با گزارش فروش روزانه فرق دارد. گزارش فروش باید «عنوان یا کد تنوع» و «تعداد ارسالی» داشته باشد. اگر قیمت معامله در فایل نباشد، قیمت فروش ثبت‌شده در کاتالوگ مبنا می‌شود؛ آن را قبل از تأیید کنترل کن.')
 return page('بارگذاری فروش روزانه',body,'پیش‌نمایش، کنترل موجودی و ثبت اتمیک')

@app.post(ROOT+'/preview',response_class=HTMLResponse)
async def preview(sale_date:str=Form(...),source:str=Form(...),files:list[UploadFile]=File(...),conn=Depends(conn_dep)):
 try:
  if len(files)>15:raise ImportErrorDetail('حداکثر ۱۵ فایل در هر نوبت قابل پذیرش است.')
  reports=[]
  for f in files:
   if not f.filename.lower().endswith('.xlsx'):raise ImportErrorDetail(f'پسوند XLSX لازم است: {f.filename}')
   reports.append((Path(f.filename).name,await f.read()))
  result=create_preview(conn,sale_date,source,reports)
 except (ImportErrorDetail,ValueError,KeyError) as ex:return fail(ex)
 if result.get('errors'):
  return page('پیش‌نمایش رد شد',notice('<ul>'+''.join('<li>'+e(error)+'</li>' for error in result['errors'][:80])+'</ul>','error')+f'<a class="button" href="{ROOT}/import">اصلاح و بارگذاری مجدد</a>')
 total=sum(x['qty']*x['price'] for x in result['rows'])
 fee=sum(x['qty']*x['fee'] for x in result['rows'])
 body=f'<div class="grid"><div class="card"><small>تعداد کالا</small><strong>{fmt(sum(x["qty"] for x in result["rows"]))}</strong></div><div class="card"><small>فروش ناخالص</small><strong>{fmt(total)}</strong></div><div class="card"><small>هزینه دیجی‌کالا</small><strong>{fmt(fee)}</strong></div><div class="card"><small>خالص بعد از دیجی‌کالا</small><strong>{fmt(total-fee)}</strong></div></div>'
 if result['fallback_prices']:body+=notice(f"قیمت {result['fallback_prices']} ردیف از قیمت پیش‌فرض کاتالوگ آمده؛ تخفیف‌ها یا قیمت واقعی را بررسی کن.")
 if result['known_cost_count']<len(result['rows']):body+=notice('برخی محصولات فاقد بهای تمام‌شده‌اند؛ سود قطعی فقط برای ردیف‌های قیمت‌گذاری‌شده قابل محاسبه است.')
 body+='<div class="panel">'+table(['کد تنوع','محصول','تعداد','قیمت واحد','کارمزد %','هزینه واحد دیجی‌کالا','بهای تمام‌شده واحد'],''.join(tr([(e(x['variant_id']),'num'),(e(x['title']),'title'),(fmt(x['qty']),'num'),(fmt(x['price']),'num'),(e(x['commission_percent']),'num'),(fmt(x['fee']),'num'),(fmt(x['cost']),'num')]) for x in result['rows']))+'</div>'
 body+=f'''<div class="panel"><form action="{ROOT}/commit" method="post"><input name="token" type="hidden" value="{e(result['token'])}"><button type="submit">تأیید نهایی، ذخیره فروش و اصلاح موجودی</button></form></div>'''
 return page('پیش‌نمایش فروش',body,f'{e(sale_date)} • {e(source)} • {result["files_count"]} فایل • {result["ignored"]} ردیف کنار گذاشته شد')

@app.post(ROOT+'/commit',response_class=HTMLResponse)
def commit(token:str=Form(...),conn=Depends(conn_dep)):
 try:result=commit_preview(conn,token)
 except (ImportErrorDetail,ValueError) as exc:return fail(exc)
 return page('فروش ثبت شد',notice(f"ثبت موفق: {result['units']} کالا، {result['lines']} ردیف، تاریخ {e(result['date'])}. موجودی کسر/اصلاح شد.",'ok')+f'<a class="button" href="{ROOT}/">مشاهده داشبورد</a>')

@app.get(ROOT+'/inventory',response_class=HTMLResponse)
def inventory(q:str='',conn=Depends(conn_dep)):
 if os.getenv('SALES_MASTER_STRICT','1') != '0':
  return RedirectResponse(ROOT+'/catalog',status_code=302)
 rows=conn.execute('SELECT * FROM products WHERE title LIKE ? OR CAST(variant_id AS TEXT) LIKE ? ORDER BY category,title LIMIT 538',(f'%{q}%',f'%{q}%')).fetchall()
 body=f'''<div class="panel"><form method="get" class="forms"><div><label>نام یا کد تنوع</label><input name="q" value="{e(q)}" placeholder="جست‌وجو..." /></div><button type="submit">جست‌وجو</button></form></div>'''
 table_rows=''
 for x in rows:
  table_rows+=tr([(e(x['variant_id']),'num'),(e(x['title']),'title'),(e(x['category']),'title'),(fmt(x['seller_stock']),'num'),(fmt(x['digikala_stock']),'num'),(fmt(x['list_price_rial']//10),'num'),(fmt(x['cost_toman']),'num'),(f'''<form method="post" action="{ROOT}/cost"><input type="hidden" name="variant_id" value="{x['variant_id']}"><input type="number" min="0" name="cost" placeholder="هزینه تومان" style="width:120px"><button type="submit">ثبت</button></form>''','')])
 body+='<div class="panel"><h3>موجودی و بهای تمام‌شده</h3>'+table(['کد تنوع','محصول','گروه','فروشنده','دیجی‌کالا','قیمت کاتالوگ (تومان)','بهای تمام‌شده','ویرایش'],table_rows)+'</div>'
 body+=f'''<div class="panel"><h3>اصلاح دستی موجودی با ثبت سند</h3><form class="forms" action="{ROOT}/stock/adjust" method="post"><div><label>کد تنوع</label><input name="variant_id" required type="number"></div><div><label>مبدأ</label><select name="source"><option value="seller">فروشنده</option><option value="digikala">دیجی‌کالا</option></select></div><div><label>موجودی جدید</label><input name="stock" min="0" required type="number"></div><div><label>علت اصلاح</label><input name="reason" required placeholder="مثلاً شمارش فیزیکی"></div><button type="submit">ثبت اصلاح</button></form></div>'''
 body+=f'''<div class="panel"><h3>ثبت گروهی بهای تمام‌شده از اکسل</h3><form class="forms" enctype="multipart/form-data" method="post" action="{ROOT}/costs/upload"><div><label>XLSX با ستون «کد تنوع» و «بهای تمام‌شده (تومان)»</label><input type="file" name="file" accept=".xlsx" required></div><button>بارگذاری هزینه‌ها</button></form></div>'''
 return page('موجودی محصولات',body,f'{len(rows)} تنوع از ۵۳۸ تنوع ثبت‌شده')

@app.post(ROOT+'/cost')
def cost(variant_id:int=Form(...),cost:str=Form(...),conn=Depends(conn_dep)):
 if os.getenv('SALES_MASTER_STRICT','1') != '0':
  return fail('بهای تمام‌شده باید در تعریف کالای اصلی اصلاح شود، نه کد تنوع دیجی‌کالا.')
 try:set_cost(conn,variant_id,cost)
 except (ImportErrorDetail,ValueError) as ex:return fail(ex)
 return RedirectResponse(ROOT+'/inventory?q='+str(variant_id),status_code=303)

@app.post(ROOT+'/costs/upload',response_class=HTMLResponse)
async def costs_upload(file:UploadFile=File(...),conn=Depends(conn_dep)):
 if os.getenv('SALES_MASTER_STRICT','1') != '0':
  return fail('بهای تمام‌شده در کالای اصلی ثبت می‌شود. از بخش تعریف محصولات استفاده کن.')
 try:
  if not file.filename.lower().endswith('.xlsx'):raise ImportErrorDetail('فایل باید XLSX باشد.')
  values=xlsx_rows(await file.read());header=next((i for i,row in enumerate(values[:10]) if any(normalize(v)=='کد تنوع' for v in row) and any('بهای تمام شده' in normalize(v).replace('‌',' ') or 'بهای تمام‌شده' in normalize(v) for v in row)),None)
  if header is None:raise ImportErrorDetail('ستون‌های کد تنوع و بهای تمام‌شده یافت نشدند.')
  cols={normalize(x).replace('‌',' '):i for i,x in enumerate(values[header])}
  vi=cols['کد تنوع'];ci=next(i for k,i in cols.items() if 'بهای تمام' in k)
  updates=[]
  for row in values[header+1:]:
   if not row or vi>=len(row) or not row[vi]:continue
   if ci>=len(row) or row[ci] in ('',None):continue
   updates.append((money(row[ci]),money(row[vi])))
  if not updates:raise ImportErrorDetail('هیچ هزینه معتبری در فایل یافت نشد.')
  conn.execute('BEGIN IMMEDIATE')
  for amount,vid in updates:
   changed=conn.execute('UPDATE products SET cost_toman=? WHERE variant_id=?',(amount,vid))
   if not changed.rowcount:raise ImportErrorDetail(f'کد تنوع {vid} ناشناخته است.')
  conn.execute('COMMIT')
 except Exception as ex:
  if conn.in_transaction:conn.execute('ROLLBACK')
  return fail(ex)
 return page('هزینه‌ها ثبت شدند',notice(f'{len(updates)} بهای تمام‌شده به‌روز شد. فروش‌های قدیمی دست‌نخورده‌اند.','ok')+f'<a class="button" href="{ROOT}/inventory">بازگشت</a>')

@app.post(ROOT+'/stock/adjust',response_class=HTMLResponse)
def stock_adjust(variant_id:int=Form(...),source:str=Form(...),stock:int=Form(...),reason:str=Form(...),conn=Depends(conn_dep)):
 if os.getenv('SALES_MASTER_STRICT','1') != '0':
  return fail('موجودی باید در بخش موجودی کالای اصلی وارد شود، نه در تنوع دیجی‌کالا.')
 try:
  if source not in ('seller','digikala') or stock<0 or not reason.strip():raise ImportErrorDetail('اطلاعات اصلاح موجودی نامعتبر است.')
  col='seller_stock' if source=='seller' else 'digikala_stock'
  conn.execute('BEGIN IMMEDIATE');r=conn.execute(f'SELECT {col} FROM products WHERE variant_id=?',(variant_id,)).fetchone()
  if not r:raise ImportErrorDetail('کد تنوع نامعتبر است.')
  delta=stock-int(r[0]);conn.execute(f'UPDATE products SET {col}=? WHERE variant_id=?',(stock,variant_id))
  conn.execute('INSERT INTO stock_events(occurred_at,variant_id,source,delta,reference) VALUES (?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),variant_id,source,delta,'manual:'+reason[:200]))
  conn.execute('COMMIT')
 except Exception as ex:
  if conn.in_transaction:conn.execute('ROLLBACK')
  return fail(ex)
 return RedirectResponse(ROOT+'/inventory?q='+str(variant_id),status_code=303)

@app.get(ROOT+'/settings',response_class=HTMLResponse)
def settings(conn=Depends(conn_dep)):
 cfg=settings_for(conn)
 names={'commission_men':'کمیسیون کالای مردانه (%)','commission_women':'کمیسیون کالای زنانه (%)','commission_shoe':'کمیسیون قالب و لوازم کفش (%)','commission_other':'کمیسیون سایر کالاها (%)','processing_percent':'هزینه پردازش (%)','processing_floor':'کف پردازش (تومان)','floor_taxable_part':'بخش مشمول مالیات کف (تومان)','vat_percent':'مالیات ارزش افزوده هزینه‌ها (%)'}
 body=notice('این نرخ‌ها تنها روی فروش‌هایی که در آینده ثبت می‌شوند اثر می‌گذارند. فروش‌های قبلی با نرخ تاریخی خود محفوظ‌اند.')
 body+='<div class="panel">'+''.join(f'<form action="{ROOT}/setting" method="post" class="forms"><input type="hidden" name="key" value="{k}"><div><label>{label}</label><input name="value" value="{e(cfg[k])}" type="number" step="0.01" min="0" required></div><button>ذخیره</button></form><hr style="border:0;border-top:1px solid #e8edf2">' for k,label in names.items())+'</div>'
 return page('تنظیمات مالی دیجی‌کالا',body)

@app.post(ROOT+'/setting')
def setting(key:str=Form(...),value:str=Form(...),conn=Depends(conn_dep)):
 try:set_setting(conn,key,value)
 except (ValueError,ImportErrorDetail) as ex:return fail(ex)
 return RedirectResponse(ROOT+'/settings',status_code=303)

@app.get(ROOT+'/api/report.json')
def api_report(start:str|None=None,end:str|None=None,conn=Depends(conn_dep)):return JSONResponse(report(conn,start,end))

@app.get(ROOT+'/api/report.csv')
def report_csv(conn=Depends(conn_dep)):
 data=report(conn)['rows'];output=io.StringIO();w=csv.writer(output)
 fields=['sale_date','source','variant_id','category','title','qty','price_toman','gross','commission_toman','processing_toman','vat_toman','total_fee','net_after_digikala','cost_toman','cogs','profit']
 w.writerow(fields)
 for x in data:w.writerow([x.get(k) for k in fields])
 return StreamingResponse(iter(['\ufeff'+output.getvalue()]),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="daily-sales.csv"'})

# Defined after page/auth helpers to allow master UI reuse without circular imports.
from .master_v2_api import router as master_router
app.include_router(master_router)
