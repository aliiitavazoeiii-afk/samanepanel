"""Isolated Digikala daily-sales engine. Amounts are TOMAN unless *_rial."""
from __future__ import annotations
import base64, hashlib, io, json, re, sqlite3, unicodedata, uuid, zipfile, zlib
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(__file__).resolve().parent
SCHEMA = '''
CREATE TABLE IF NOT EXISTS products (
 variant_id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, category TEXT NOT NULL,
 title TEXT NOT NULL, title_key TEXT NOT NULL, active INTEGER NOT NULL,
 list_price_rial INTEGER NOT NULL, promotion_price_rial INTEGER NOT NULL,
 seller_stock INTEGER NOT NULL, digikala_stock INTEGER NOT NULL, reserved INTEGER NOT NULL,
 cost_toman INTEGER, seeded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_title_key ON products(title_key);
CREATE TABLE IF NOT EXISTS sales (
 sale_date TEXT NOT NULL, source TEXT NOT NULL, variant_id INTEGER NOT NULL,
 qty INTEGER NOT NULL, price_toman INTEGER NOT NULL, commission_toman INTEGER NOT NULL,
 processing_toman INTEGER NOT NULL, vat_toman INTEGER NOT NULL, fee_toman INTEGER NOT NULL,
 cost_toman INTEGER, PRIMARY KEY(sale_date,source,variant_id),
 FOREIGN KEY(variant_id) REFERENCES products(variant_id)
);
CREATE TABLE IF NOT EXISTS stock_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL, variant_id INTEGER NOT NULL,
 source TEXT NOT NULL, delta INTEGER NOT NULL, reference TEXT NOT NULL,
 FOREIGN KEY(variant_id) REFERENCES products(variant_id)
);
CREATE TABLE IF NOT EXISTS previews (token TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS import_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, committed_at TEXT NOT NULL,
 sale_date TEXT NOT NULL, source TEXT NOT NULL, file_sha256 TEXT NOT NULL,
 item_count INTEGER NOT NULL, line_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''
DEFAULT_SETTINGS = {
 'commission_men':'24.3', 'commission_women':'24', 'commission_shoe':'22.5',
 'commission_other':'24', 'processing_percent':'7', 'processing_floor':'36000',
 'floor_taxable_part':'18000', 'vat_percent':'10'
}
MAX_UPLOAD_BYTES=12*1024*1024
NS={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')

class ImportErrorDetail(ValueError): pass

def dbconnect(path):
 c=sqlite3.connect(str(path),timeout=30, isolation_level=None, check_same_thread=False)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA busy_timeout=30000')
 c.execute('PRAGMA foreign_keys=ON')
 c.execute('PRAGMA journal_mode=WAL')
 return c

def normalize(value):
 s=unicodedata.normalize('NFKC',str(value or '')).translate(DIGITS).replace('ي','ی').replace('ك','ک').replace('\u200c',' ').replace('\xa0',' ')
 s=re.sub(r'[\u064b-\u065f\u0670]','',s).strip().lower()
 s=re.sub(r'\s*\|\s*گارانتی.*$','',s)
 return re.sub(r'\s+',' ',s)

def money(value):
 s=str(value or '0').translate(DIGITS).replace(',','').replace('٬','').replace(' ','').strip()
 try:
  v=Decimal(s)
 except Exception: raise ImportErrorDetail(f'مقدار عددی نامعتبر: {value!r}')
 if v < 0: raise ImportErrorDetail('مبلغ یا تعداد نمی‌تواند منفی باشد.')
 return int(v.quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def init_db(db_path, catalog_path=None):
 conn=dbconnect(db_path)
 try:
  conn.executescript(SCHEMA)
  with conn:
   for key,value in DEFAULT_SETTINGS.items():
    conn.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)',(key,value))
   if conn.execute('SELECT COUNT(*) FROM products').fetchone()[0]==0:
    path=Path(catalog_path or (BASE/'catalog_seed.b64'))
    data=json.loads(zlib.decompress(base64.b64decode(path.read_text().strip())))
    now=datetime.now(timezone.utc).isoformat()
    for variant_id,product_id,cat,title,active,price,promo,seller,dk,reserved in data:
     conn.execute('INSERT INTO products(variant_id,product_id,category,title,title_key,active,list_price_rial,promotion_price_rial,seller_stock,digikala_stock,reserved,seeded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
      (variant_id,product_id,cat,title,normalize(title),active,price,promo,seller,dk,reserved,now))
  return conn
 except Exception:
  conn.close();raise

def fee_unit(price_toman, category, settings):
 """Matches darma-general/core/finance.py fee formula, category-specific commission."""
 price=Decimal(price_toman)
 if 'قالب کفش' in category or 'مراقبت کفش' in category: rate='commission_shoe'
 elif 'مردانه' in category: rate='commission_men'
 elif 'زنانه' in category: rate='commission_women'
 else: rate='commission_other'
 commission=price*Decimal(settings[rate])/100
 raw_processing=price*Decimal(settings['processing_percent'])/100
 floor=Decimal(settings['processing_floor'])
 if raw_processing<floor:
  processing=floor; taxable_processing=Decimal(settings['floor_taxable_part'])
 else: processing=raw_processing;taxable_processing=processing/2
 vat=(commission+taxable_processing)*Decimal(settings['vat_percent'])/100
 rnd=lambda v:int(v.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
 total=rnd(commission+processing+vat)
 cc=rnd(commission); pp=rnd(processing)
 return {'commission':cc,'processing':pp,'vat':total-cc-pp,'fee':total,'commission_percent':str(settings[rate])}

def settings_for(conn):
 return {x['key']:x['value'] for x in conn.execute('SELECT key,value FROM settings')}

def xlsx_rows(data):
 if not data or len(data)>MAX_UPLOAD_BYTES: raise ImportErrorDetail('فایل خالی یا بزرگ‌تر از ۱۲ مگابایت است.')
 if not zipfile.is_zipfile(io.BytesIO(data)): raise ImportErrorDetail('فقط فایل XLSX معتبر پذیرفته می‌شود.')
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  names=set(z.namelist());strings=[]
  if 'xl/sharedStrings.xml' in names:
   root=ET.fromstring(z.read('xl/sharedStrings.xml'))
   for item in root.findall('x:si',NS):strings.append(''.join(t.text or '' for t in item.iterfind('.//x:t',NS)))
  sheet=next((x for x in sorted(names) if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',x)),None)
  if not sheet:raise ImportErrorDetail('برگه اکسل پیدا نشد.')
  root=ET.fromstring(z.read(sheet));result=[]
  for row in root.findall('.//x:sheetData/x:row',NS):
   values={}
   for cell in row.findall('x:c',NS):
    addr=cell.get('r','');col=re.match(r'[A-Z]+',addr)
    if not col:continue
    index=0
    for letter in col.group():index=index*26+ord(letter)-64
    cell_value=cell.find('x:v',NS)
    inline=cell.find('x:is',NS)
    value=cell_value.text if cell_value is not None else ''
    if cell.get('t')=='s' and value!='':value=strings[int(value)]
    if cell.get('t')=='inlineStr' and inline is not None:value=''.join(t.text or '' for t in inline.iterfind('.//x:t',NS))
    values[index-1]=value
   result.append([values.get(i,'') for i in range(max(values.keys(),default=-1)+1)])
  return result

HEADER_VARIANT=('کد تنوع','شناسه تنوع','variant_id','variant id','کد تنوع کالا')
HEADER_TITLE=('عنوان','عنوان کالا','عنوان تنوع کالا','نام کالا','نام محصول')
HEADER_QTY=('تعداد ارسالی','تعداد فروش','تعداد فروخته شده','quantity','تعداد')
HEADER_STATUS=('وضعیت','status')
HEADER_PRICE_TOMAN=('قیمت واحد (تومان)','قیمت فروش (تومان)','unit_price_toman')
HEADER_PRICE_RIAL=('قیمت واحد (ریال)','قیمت فروش (ریال)','(ریال)قیمت فروش','unit_price_rial')

def parse_sales_xlsx(data):
 rows=xlsx_rows(data)
 headers=None;offset=-1
 for i,row in enumerate(rows[:15]):
  lookup={normalize(x):j for j,x in enumerate(row) if normalize(x)}
  if any(normalize(k) in lookup for k in HEADER_QTY) and (any(normalize(k) in lookup for k in HEADER_VARIANT) or any(normalize(k) in lookup for k in HEADER_TITLE)):
   headers=lookup;offset=i;break
 if headers is None:raise ImportErrorDetail('ستون عنوان یا کد تنوع و ستون تعداد ارسالی/فروش پیدا نشد.')
 def val(row,names):
  for name in names:
   index=headers.get(normalize(name))
   if index is not None:return row[index] if index<len(row) else ''
  return ''
 out=[];ignored=0
 for pos,row in enumerate(rows[offset+1:],start=offset+2):
  quantity=money(val(row,HEADER_QTY))
  if not quantity:ignored+=1;continue
  status=normalize(val(row,HEADER_STATUS))
  if status and ('مرجوع' in status or 'بازگشت' in status or 'return' in status):ignored+=1;continue
  if status and 'دریافت' not in status and 'received' not in status and 'تحویل' not in status:ignored+=1;continue
  explicit_toman=val(row,HEADER_PRICE_TOMAN);explicit_rial=val(row,HEADER_PRICE_RIAL)
  if explicit_toman not in ('',None) and explicit_rial not in ('',None):raise ImportErrorDetail(f'ردیف {pos}: دو ستون قیمت دارد.')
  price=money(explicit_toman) if explicit_toman not in ('',None) else (money(explicit_rial)//10 if explicit_rial not in ('',None) else None)
  if explicit_rial not in ('',None) and money(explicit_rial)%10:raise ImportErrorDetail(f'ردیف {pos}: قیمت ریالی به تومان قابل تبدیل دقیق نیست.')
  code=str(val(row,HEADER_VARIANT) or '').translate(DIGITS).strip()
  if code.endswith('.0'):code=code[:-2]
  out.append({'row':pos,'variant_id':code,'title':str(val(row,HEADER_TITLE) or ''),'qty':quantity,'price':price})
 if not out:raise ImportErrorDetail('هیچ ردیف فروش قطعی یافت نشد.')
 return out,ignored

def prepare_preview(conn,sale_date,source,files):
 try:date.fromisoformat(sale_date)
 except ValueError:raise ImportErrorDetail('تاریخ باید میلادی و به شکل YYYY-MM-DD باشد.')
 if source not in ('seller','digikala'):raise ImportErrorDetail('منبع موجودی نامعتبر است.')
 products={int(x['variant_id']):x for x in conn.execute('SELECT * FROM products')}
 by_title=defaultdict(list)
 for item in products.values():by_title[item['title_key']].append(item)
 entries={};errors=[];ignored=0;file_hash=hashlib.sha256();fallback=0
 for filename,data in files:
  file_hash.update(filename.encode());file_hash.update(data)
  parsed,skip=parse_sales_xlsx(data);ignored+=skip
  for x in parsed:
   product=None
   if x['variant_id']:
    try:product=products.get(int(x['variant_id']))
    except ValueError:pass
   elif x['title']:
    matches=by_title.get(normalize(x['title']),[])
    if len(matches)==1:product=matches[0]
   if product is None:
    errors.append(f"{filename} / ردیف {x['row']}: محصول ناشناخته یا عنوان مبهم است؛ کد تنوع: {x['variant_id']}, عنوان: {x['title'][:90]}")
    continue
   if not product['active']: errors.append(f"{filename} / ردیف {x['row']}: کالای غیرفعال {product['variant_id']}");continue
   p=x['price']
   if p is None:
    p=product['list_price_rial']//10
    fallback+=1
   if p<=0:errors.append(f"{filename} / ردیف {x['row']}: قیمت فروش صفر است");continue
   key=(int(product['variant_id']),p)
   entries[key]=entries.get(key,0)+x['qty']
 if errors: return {'errors':errors,'rows':[],'ignored':ignored,'fallback_prices':fallback}
 by_variant=defaultdict(list)
 for (variant_id,price),quantity in entries.items():by_variant[variant_id].append((price,quantity))
 for vid,v in by_variant.items():
  if len(v)>1:errors.append(f'کد تنوع {vid} با دو قیمت فروش متفاوت در فایل‌ها وجود دارد؛ این واردکننده هر کالا را با یک قیمت روز ثبت می‌کند.')
 if errors:return {'errors':errors,'rows':[],'ignored':ignored,'fallback_prices':fallback}
 current={x['variant_id']:x for x in conn.execute('SELECT * FROM sales WHERE sale_date=? AND source=?',(sale_date,source))}
 cfg=settings_for(conn);prepared=[];known_cost_count=0
 for variant_id,detail in sorted(by_variant.items()):
  price,qty=detail[0];product=products[variant_id];f=fee_unit(price,product['category'],cfg)
  cost=product['cost_toman']
  if cost is not None:known_cost_count+=1
  prepared.append({'variant_id':variant_id,'title':product['title'],'category':product['category'],'qty':qty,'price':price,'cost':cost,**f})
 changes=[]
 for variant_id in set(current)|{r['variant_id'] for r in prepared}:
  old=int(current[variant_id]['qty']) if variant_id in current else 0
  new=next((x['qty'] for x in prepared if x['variant_id']==variant_id),0)
  stock_column='seller_stock' if source=='seller' else 'digikala_stock'
  available=int(products[variant_id][stock_column])+old-new
  if available<0:errors.append(f"موجودی ناکافی برای کد تنوع {variant_id}: موجودی {products[variant_id][stock_column]}، فروش قبلی {old}، جدید {new}")
  changes.append({'variant_id':variant_id,'delta':old-new,'stock_after':available})
 return {'errors':errors,'rows':prepared,'sale_date':sale_date,'source':source,'ignored':ignored,'fallback_prices':fallback,'files_count':len(files),'files_sha256':file_hash.hexdigest(),'known_cost_count':known_cost_count,'stock_changes':changes}

def create_preview(conn,sale_date,source,files):
 preview=prepare_preview(conn,sale_date,source,files)
 if preview['errors']:return preview
 token=uuid.uuid4().hex
 conn.execute('INSERT INTO previews(token,created_at,payload) VALUES (?,?,?)',(token,datetime.now(timezone.utc).isoformat(),json.dumps(preview,ensure_ascii=False)))
 return {**preview,'token':token}

def commit_preview(conn,token):
 """Replacement, atomic, inventory invariant. Confirm only fresh preview."""
 conn.execute('BEGIN IMMEDIATE')
 try:
  row=conn.execute('SELECT * FROM previews WHERE token=?',(token,)).fetchone()
  if row is None:raise ImportErrorDetail('پیش‌نمایش یافت نشد یا قبلاً ثبت شده است.')
  payload=json.loads(row['payload']);created=datetime.fromisoformat(row['created_at'])
  if (datetime.now(timezone.utc)-created).total_seconds()>1800:raise ImportErrorDetail('پیش‌نمایش منقضی شده است؛ فایل را دوباره بارگذاری کن.')
  day=payload['sale_date'];source=payload['source'];column='seller_stock' if source=='seller' else 'digikala_stock'
  old={r['variant_id']:r for r in conn.execute('SELECT * FROM sales WHERE sale_date=? AND source=?',(day,source))}
  new={x['variant_id']:x for x in payload['rows']}
  for vid in set(old)|set(new):
   prior=int(old[vid]['qty']) if vid in old else 0;next_qty=int(new[vid]['qty']) if vid in new else 0
   delta=prior-next_qty
   if not delta:continue
   current=conn.execute(f'SELECT {column} FROM products WHERE variant_id=?',(vid,)).fetchone()
   if current is None or int(current[0])+delta<0:raise ImportErrorDetail(f'موجودی کد {vid} تغییر کرده؛ پیش‌نمایش جدید بگیر.')
   conn.execute(f'UPDATE products SET {column}={column}+? WHERE variant_id=?',(delta,vid))
   conn.execute('INSERT INTO stock_events(occurred_at,variant_id,source,delta,reference) VALUES (?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),vid,source,delta,f'daily-sale:{day}:{source}:{token}'))
  conn.execute('DELETE FROM sales WHERE sale_date=? AND source=?',(day,source))
  for x in payload['rows']:
   conn.execute('INSERT INTO sales(sale_date,source,variant_id,qty,price_toman,commission_toman,processing_toman,vat_toman,fee_toman,cost_toman) VALUES (?,?,?,?,?,?,?,?,?,?)',
   (day,source,x['variant_id'],x['qty'],x['price'],x['commission'],x['processing'],x['vat'],x['fee'],x['cost']))
  conn.execute('INSERT INTO import_audit(committed_at,sale_date,source,file_sha256,item_count,line_count) VALUES (?,?,?,?,?,?)',
  (datetime.now(timezone.utc).isoformat(),day,source,payload['files_sha256'],sum(r['qty'] for r in payload['rows']),len(payload['rows'])))
  conn.execute('DELETE FROM previews WHERE token=?',(token,))
  conn.execute('COMMIT')
  return {'date':day,'source':source,'units':sum(r['qty'] for r in payload['rows']),'lines':len(payload['rows'])}
 except Exception:
  conn.execute('ROLLBACK');raise

def report(conn,start=None,end=None):
 sql='SELECT s.*,p.category,p.title FROM sales s JOIN products p ON p.variant_id=s.variant_id WHERE 1=1';args=[]
 if start:sql+=' AND sale_date>=?';args.append(start)
 if end:sql+=' AND sale_date<=?';args.append(end)
 sql+=' ORDER BY sale_date DESC,p.category,p.title'
 rows=[dict(r) for r in conn.execute(sql,args)]
 summary={'gross':0,'fee':0,'cogs_known':0,'profit_known':0,'units':0,'unknown_cost_lines':0,'unknown_cost_units':0,'rows':rows,'categories':{}}
 for x in rows:
  qty=x['qty'];gross=qty*x['price_toman'];fee=qty*x['fee_toman'];cogs=qty*x['cost_toman'] if x['cost_toman'] is not None else None
  x.update(gross=gross,total_fee=fee,cogs=cogs,profit=(gross-fee-cogs if cogs is not None else None),net_after_digikala=gross-fee)
  summary['gross']+=gross;summary['fee']+=fee;summary['units']+=qty
  if cogs is None:summary['unknown_cost_lines']+=1;summary['unknown_cost_units']+=qty
  else:summary['cogs_known']+=cogs;summary['profit_known']+=x['profit']
  b=summary['categories'].setdefault(x['category'],{'gross':0,'fee':0,'units':0,'profit_known':0,'unknown_cost_lines':0})
  b['gross']+=gross;b['fee']+=fee;b['units']+=qty
  if cogs is None:b['unknown_cost_lines']+=1
  else:b['profit_known']+=x['profit']
 summary['net_after_digikala']=summary['gross']-summary['fee']
 summary['profit']=summary['profit_known'] if summary['unknown_cost_lines']==0 else None
 return summary

def set_cost(conn,variant_id,cost_toman):
 cost=money(cost_toman)
 with conn:
  r=conn.execute('UPDATE products SET cost_toman=? WHERE variant_id=?',(cost,variant_id))
  if r.rowcount==0:raise ImportErrorDetail('کد تنوع در کاتالوگ نیست.')
 # Existing sales deliberately keep historical cost snapshots unchanged.
 return True

def set_setting(conn,key,value):
 if key not in DEFAULT_SETTINGS:raise ImportErrorDetail('تنظیم مالی ناشناخته است.')
 v=Decimal(str(value))
 if v<0 or (key.endswith('percent') or key.startswith('commission_')) and v>100:raise ImportErrorDetail('درصد نامعتبر است.')
 conn.execute('UPDATE settings SET value=? WHERE key=?',(str(v),key))
