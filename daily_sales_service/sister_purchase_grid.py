"""All active physical SKUs for one selected category, in Excel-style grids.

Display grouping never changes stock identity. Every input represents one exact
master_products.id, even when multiple legacy codes share a model/color/size.
"""
import json
import re

from .sister_purchases import CATEGORIES
from .master_v2_logic import SIZES

def _family_title(row):
    title=str(row["title"] or "").strip()
    color=str(row["color"] or "").strip()
    if color not in ("", "-"):
        # Legacy imported products often append the actual color to the title.
        normalized=lambda x: re.sub(r"[\s\u200c\u200f-]+"," ",x).strip().replace("ي","ی").replace("ك","ک")
        # Only remove the literal suffix delimiter when the suffix equals
        # the SKU color; never guess or strip a model identifier.
        parts=re.split(r"\s+[-–—]\s+",title)
        if len(parts)>1 and normalized(parts[-1])==normalized(color):
            title=" - ".join(parts[:-1])
    return title or str(row["code"])

def purchase_catalog(conn):
    """Category => visible models => exact SKU rows (including legacy color codes)."""
    groups={}
    for category in CATEGORIES:
        query="""SELECT id,code,title,subtype,color,size,seller_stock,khorshid_stock
               FROM master_products WHERE category=? AND active=1
               ORDER BY subtype,title,code,color,size,id"""
        for row in conn.execute(query,(category,)):
            r=dict(row)
            subtype=r["subtype"] or ""
            title=_family_title(r)
            key=json.dumps([category,subtype,title],ensure_ascii=False)
            group=groups.setdefault(key,{"key":key,"category":category,
                "subtype":subtype,"label":title,
                "rows":[],"sizes":list(SIZES[category])})
            sku={"id":r["id"],"code":r["code"],"color":r["color"] or "-",
                 "size":r["size"],"home":r["seller_stock"],
                 "khorshid":r["khorshid_stock"]}
            group["rows"].append(sku)
            if r["size"] not in group["sizes"]:
                group["sizes"].append(r["size"])
    # The front-end groups all models under the selected category and puts
    # Bodyguard slip before padar, without altering any SKU identifiers.
    def group_order(x):
        subtype_rank={"اسلیپ":0,"پادار":1}.get(x["subtype"],2)
        return (CATEGORIES.index(x["category"]),subtype_rank,x["label"],x["key"])
    return sorted(groups.values(),key=group_order)

def purchase_grid(conn):
    # Escaping script-breaking characters is important for user-defined model names.
    safe=(json.dumps(purchase_catalog(conn),ensure_ascii=False)
          .replace("<","\\u003c").replace(">","\\u003e")
          .replace("&","\\u0026"))
    body = """
<style>
.purchase-grid-controls{display:grid;grid-template-columns:minmax(230px,400px);gap:12px;margin:16px 0}
.purchase-grid-section{margin:17px 0 24px}
.purchase-grid-section h3{margin:0 0 12px;font-size:18px}
.purchase-grid-subtype{border-bottom:1px solid #385470;padding:11px 2px 9px;margin:22px 0 11px;font-size:18px}
.purchase-grid-table{min-width:690px;table-layout:auto}
.purchase-grid-table th:first-child{min-width:120px;position:sticky;right:0;background:#17324d;z-index:2}
.purchase-grid-table input{width:100%;min-width:76px;max-width:122px;text-align:center}
.purchase-grid-table .unit-price{min-width:100px}
.purchase-grid-meta{font-size:12px;opacity:.75;margin-top:5px;white-space:nowrap}
.purchase-grid-actions{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:12px 0}
.purchase-grid-summary{margin:12px 0;line-height:2}
.purchase-grid-summary strong{font-size:18px}
.purchase-grid-empty{padding:18px;border:1px dashed #385470;border-radius:12px}
@media(max-width:640px){.purchase-grid-controls{grid-template-columns:1fr}}
</style>
<div class="purchase-grid-controls">
 <div><label>دسته کالا</label><select id="purchase-category" aria-label="دسته کالا"></select></div>
</div>
<p class="m2-hint">همه مدل‌های دسته انتخاب‌شده پایین همین صفحه نمایش داده می‌شوند. هر مدل، رنگ‌ها و سایزهای خودش را دارد. می‌توانی چند مدل و حتی چند دسته را در یک فاکتور خرید ثبت کنی.</p>
<div id="purchase-grids" aria-live="polite"></div>
<div class="purchase-grid-actions">
 <strong id="purchase-selected-count" role="status">۰ قلم انتخاب‌شده</strong>
 <button type="button" id="purchase-clear-all" class="m2-btn">پاک کردن همه تعدادهای واردشده</button>
</div>
<div class="m2-card purchase-grid-summary">
  <div>تعداد کل: <strong id="purchase-total-qty">۰</strong></div>
  <div>جمع قبل از تخفیف: <strong id="purchase-subtotal">۰</strong> تومان</div>
  <div>مبلغ تخفیف: <strong id="purchase-discount-amount">۰</strong> تومان</div>
  <div>جمع نهایی خرید: <strong id="purchase-total">۰</strong> تومان</div>
  <div class="m2-hint" id="purchase-overview"></div>
</div>
<div id="purchase-hidden-lines"></div>
<script type="application/json" id="purchase-stock-data">__DATA__</script>
<script>
(function(){
 const catalog=JSON.parse(document.getElementById("purchase-stock-data").textContent);
 const cats=[...new Set(catalog.map(g=>g.category))];
 const category=document.getElementById("purchase-category");
 const gridRoot=document.getElementById("purchase-grids");
 const selected=document.getElementById("purchase-selected-count");
 const hidden=document.getElementById("purchase-hidden-lines");
 const form=document.getElementById("purchase-entry-form");
 const discount=document.getElementById("purchase-discount-percent");
 const qty={};const unitPrice={};
 const format=new Intl.NumberFormat("fa-IR");
 const fmt=n=>format.format(Math.round(n||0));
 const norm=v=>String(v||"").replace(/[۰-۹٠-٩]/g,c=>{
   let p="۰۱۲۳۴۵۶۷۸۹".indexOf(c);
   return String(p<0?"٠١٢٣٤٥٦٧٨٩".indexOf(c):p);
 });
 const val=v=>Math.max(0,Number(norm(v))||0);
 function mk(parent,tag,content,attrs={}){
   const el=document.createElement(tag);
   if(content!==undefined)el.textContent=content;
   Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));
   parent.appendChild(el);return el;
 }
 function allRecords(){
   const records=[];
   for(const group of catalog){
     for(const sku of group.rows){
       const count=qty[sku.id]||0;if(!count)continue;
       const price=unitPrice[group.key+"|"+sku.size]||0;
       records.push({id:sku.id,count,price,title:group.label,
                     subtype:group.subtype,color:sku.color,size:sku.size});
     }
   }
   return records;
 }
 function totals(){
   const records=allRecords();
   const n=records.reduce((v,r)=>v+r.count,0);
   const subtotal=records.reduce((v,r)=>v+r.count*r.price,0);
   const pct=val(discount.value);
   let net=0;
   for(const r of records)net+=r.count*Math.round(r.price*(1-pct/100));
   selected.textContent=fmt(records.length)+" قلم انتخاب‌شده";
   document.getElementById("purchase-total-qty").textContent=fmt(n);
   document.getElementById("purchase-subtotal").textContent=fmt(subtotal);
   document.getElementById("purchase-discount-amount").textContent=fmt(subtotal-net);
   document.getElementById("purchase-total").textContent=fmt(net);
   document.getElementById("purchase-overview").textContent=records.length?
       records.slice(0,20).map(r=>r.title+" / "+(r.subtype?r.subtype+" / ":"")+
        r.color+" / "+r.size+" × "+fmt(r.count)).join("، "):"هنوز کالایی انتخاب نشده است.";
   return records;
 }
 function modelRows(group){
   // Legacy inventory can have a different code per color. Combine those
   // into one model table while keeping exact code/ID per quantity cell.
   const byColor=new Map();
   for(const sku of group.rows){
     const key=sku.code+"\\u0001"+sku.color;
     if(!byColor.has(key))byColor.set(key,{color:sku.color,code:sku.code,skus:[]});
     byColor.get(key).skus.push(sku);
   }
   const rows=[...byColor.values()];
   const countForColor={};
   for(const r of rows)countForColor[r.color]=(countForColor[r.color]||0)+1;
   for(const r of rows){
     r.label=r.color+(countForColor[r.color]>1?" ("+r.code+")":"");
   }
   return rows;
 }
 function renderGroup(g){
   const section=mk(gridRoot,"section",undefined,{class:"m2-card purchase-grid-section"});
   mk(section,"h3",g.label);
   const wrapper=mk(section,"div",undefined,{class:"m2-table-scroll"});
   const table=mk(wrapper,"table",undefined,{class:"m2-table purchase-grid-table"});
   const head=mk(table,"thead"),tbody=mk(table,"tbody"),foot=mk(table,"tfoot");
   const heading=mk(head,"tr");mk(heading,"th","رنگ / سایز");
   for(const size of g.sizes){
     const th=mk(heading,"th",size);
     mk(th,"div","قیمت خرید هر عدد (تومان)",{class:"purchase-grid-meta"});
     const input=mk(th,"input",undefined,{
        type:"number",min:"1",step:"1",placeholder:"قیمت",class:"unit-price",
        "aria-label":"قیمت "+g.label+" سایز "+size
     });
     input.value=unitPrice[g.key+"|"+size]||"";
     input.addEventListener("input",()=>{
       unitPrice[g.key+"|"+size]=val(input.value);totals();
     });
   }
   const rows=modelRows(g);
   // Each physical SKU has one unique editable cell even if legacy product
   // codes repeat a color/size combination. Never silently merge SKUs.
   for(const row of rows){
     const tr=mk(tbody,"tr");mk(tr,"th",row.label);
     for(const size of g.sizes){
       const cell=mk(tr,"td");
       const candidates=row.skus.filter(s=>s.size===size);
       if(!candidates.length){mk(cell,"span","—");continue;}
       for(const sku of candidates){
         const input=mk(cell,"input",undefined,{
           type:"number",min:"0",max:"100000",step:"1",placeholder:"—",
           "aria-label":g.label+" "+row.label+" "+size+" "+sku.code
         });
         input.value=qty[sku.id]||"";
         input.addEventListener("input",()=>{
           qty[sku.id]=val(input.value);refreshFooter();totals();
         });
         if(candidates.length>1)mk(cell,"div",sku.code,{class:"purchase-grid-meta"});
         mk(cell,"div","خانه: "+fmt(sku.home)+" / خورشید: "+fmt(sku.khorshid),
            {class:"purchase-grid-meta"});
       }
     }
   }
   const final=mk(foot,"tr");mk(final,"th","تعداد کل");
   const footCells=g.sizes.map(()=>mk(final,"th","۰"));
   function refreshFooter(){
     for(const [i,size] of g.sizes.entries()){
       footCells[i].textContent=fmt(g.rows.filter(s=>s.size===size)
           .reduce((v,s)=>v+(qty[s.id]||0),0));
     }
   }
   refreshFooter();
   const actions=mk(section,"div",undefined,{class:"purchase-grid-actions"});
   const clear=mk(actions,"button","پاک کردن تعدادهای این مدل",
      {type:"button",class:"m2-btn"});
   clear.addEventListener("click",()=>{
     for(const sku of g.rows)delete qty[sku.id];
     redraw();
   });
 }
 function redraw(){
   gridRoot.replaceChildren();
   const shown=catalog.filter(x=>x.category===category.value);
   if(!shown.length){
     mk(gridRoot,"p","برای این دسته کالای فعال تعریف نشده است.",
        {class:"purchase-grid-empty"});
     totals();return;
   }
   let currentSubtype=null;
   for(const g of shown){
     if(category.value==="بادیگارد"&&currentSubtype!==g.subtype){
       currentSubtype=g.subtype;
       mk(gridRoot,"h2",g.subtype?"بادیگارد — "+g.subtype:"بادیگارد — بدون نوع",
          {class:"purchase-grid-subtype"});
     }
     renderGroup(g);
   }
   totals();
 }
 cats.forEach(name=>mk(category,"option",name,{value:name}));
 category.addEventListener("change",redraw);
 discount.addEventListener("input",totals);
 document.getElementById("purchase-clear-all").addEventListener("click",()=>{
   for(const k of Object.keys(qty))delete qty[k];
   redraw();
 });
 form.addEventListener("submit",event=>{
   hidden.replaceChildren();
   const records=totals();
   if(!records.length){event.preventDefault();alert("حداقل یک تعداد کالا انتخاب کن.");return;}
   if(records.length>120){event.preventDefault();alert("در هر رسید حداکثر ۱۲۰ رنگ/سایز ثبت کن.");return;}
   const pct=val(discount.value);
   if(pct>=100||!Number.isFinite(pct)){event.preventDefault();alert("تخفیف باید کمتر از ۱۰۰٪ باشد.");return;}
   if(records.some(r=>!Number.isInteger(r.count)||r.count<=0||r.count>100000||
                        !Number.isInteger(r.price)||r.price<=0)){
     event.preventDefault();alert("تعداد و قیمت خرید صحیح هر سایز را وارد کن.");return;
   }
   records.forEach((r,i)=>{
     for(const [name,value] of [["master",r.id],["qty",r.count],["cost",r.price]]){
       mk(hidden,"input",undefined,{type:"hidden",name:name+"_"+(i+1),value:String(value)});
     }
   });
 });
 redraw();
})();
</script>
""".replace("__DATA__",safe)
    return body
