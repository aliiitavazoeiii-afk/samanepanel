"""Excel-style supplier purchase grid. Rows are colors, columns are sizes."""
import json
from .app import e
from .sister_purchases import CATEGORIES
from .master_v2_logic import SIZES

def purchase_grid(conn):
    groups={}
    for category in CATEGORIES:
        for row in conn.execute("""SELECT id,code,title,subtype,color,size,seller_stock,khorshid_stock
           FROM master_products WHERE category=? AND active=1
           ORDER BY title,code,subtype,color,size,id""",(category,)):
            r=dict(row)
            # SKU identity is exact; never infer that different codes are the same product.
            key="|".join((category,r["code"],r["title"],r["subtype"] or ""))
            group=groups.setdefault(key,{"key":key,"category":category,
                "label":r["title"]+(" / "+r["subtype"] if r["subtype"] else "")+
                " ("+r["code"]+")","rows":[],"sizes":list(SIZES[category])})
            group["rows"].append({"id":r["id"],"color":r["color"] or "-",
                "size":r["size"],"home":r["seller_stock"],"khorshid":r["khorshid_stock"]})
    safe=json.dumps(list(groups.values()),ensure_ascii=False).replace("</","<\\/")
    body = """
<style>
  .purchase-grid-controls{display:grid;grid-template-columns:minmax(170px,1fr) minmax(230px,2fr);gap:12px;margin:16px 0}
  .purchase-grid-table{min-width:650px}
  .purchase-grid-table th:first-child{min-width:115px;position:sticky;right:0;background:#17324d;z-index:2}
  .purchase-grid-table input{width:100%;min-width:76px;max-width:128px;text-align:center}
  .purchase-grid-table .unit-price{min-width:104px}
  .purchase-grid-meta{font-size:12px;opacity:.7;margin-top:5px;white-space:nowrap}
  .purchase-grid-actions{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}
  .purchase-grid-summary{margin:12px 0;line-height:2}
  .purchase-grid-summary strong{font-size:18px}
  @media(max-width:640px){.purchase-grid-controls{grid-template-columns:1fr}}
</style>
<div class="purchase-grid-controls">
 <div><label>دسته کالا</label><select id="purchase-category" aria-label="دسته کالا"></select></div>
 <div><label>مدل</label><select id="purchase-model" aria-label="مدل"></select></div>
</div>
<p class="m2-hint">مثل جدول خرید تکوین: قیمت هر سایز بالای ستون، تعداد هر رنگ داخل جدول. مدل‌های مختلف را یکی‌یکی تکمیل کن؛ ردیف‌ها در فاکتور خرید باقی می‌مانند.</p>
<div class="m2-table-scroll"><table class="m2-table purchase-grid-table">
<thead id="purchase-grid-head"></thead><tbody id="purchase-grid-body"></tbody>
<tfoot id="purchase-grid-foot"></tfoot></table></div>
<div class="purchase-grid-actions">
<button type="button" id="purchase-clear-grid" class="m2-btn">پاک کردن تعدادهای این مدل</button>
<span id="purchase-selected-count" role="status">۰ قلم انتخاب‌شده</span>
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
 const model=document.getElementById("purchase-model");
 const head=document.getElementById("purchase-grid-head");
 const tbody=document.getElementById("purchase-grid-body");
 const foot=document.getElementById("purchase-grid-foot");
 const selected=document.getElementById("purchase-selected-count");
 const hidden=document.getElementById("purchase-hidden-lines");
 const form=document.getElementById("purchase-entry-form");
 const discount=document.getElementById("purchase-discount-percent");
 const data={};const unitPrice={};
 const persian=new Intl.NumberFormat("fa-IR");
 const fmt=n=>persian.format(Math.round(n||0));
 const norm=v=>String(v||"").replace(/[۰-۹٠-٩]/g,c=>{let p="۰۱۲۳۴۵۶۷۸۹".indexOf(c);return String(p<0?"٠١٢٣٤٥٦٧٨٩".indexOf(c):p)});
 const val=v=>Math.max(0,Number(norm(v))||0);
 const grid=()=>catalog.find(g=>g.key===model.value);
 function mk(parent,tag,content,attrs={}){
   const el=document.createElement(tag);if(content!==undefined)el.textContent=content;
   Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));parent.appendChild(el);return el;
 }
 function refreshModels(){
   model.replaceChildren();
   catalog.filter(x=>x.category===category.value).forEach(g=>mk(model,"option",g.label,{value:g.key}));
   redraw();
 }
 function totals(){
   let n=0,subtotal=0;const records=[];
   for(const g of catalog){
     for(const s of g.rows){
       const count=data[s.id]||0;if(!count)continue;
       const price=unitPrice[g.key+"|"+s.size]||0;
       n+=count;subtotal+=count*price;
       records.push({id:s.id,count,price,title:g.label,color:s.color,size:s.size});
     }
   }
   const percent=Math.min(99.999,Math.max(0,val(discount.value)));
   let net=0;for(const r of records)net+=r.count*Math.round(r.price*(1-percent/100));
   selected.textContent=fmt(records.length)+" قلم انتخاب‌شده";
   document.getElementById("purchase-total-qty").textContent=fmt(n);
   document.getElementById("purchase-subtotal").textContent=fmt(subtotal);
   document.getElementById("purchase-discount-amount").textContent=fmt(subtotal-net);
   document.getElementById("purchase-total").textContent=fmt(net);
   document.getElementById("purchase-overview").textContent=records.length?
      records.slice(0,12).map(r=>r.title+" / "+r.color+" / "+r.size+" × "+fmt(r.count)).join("، "):"هنوز کالایی انتخاب نشده است.";
   return records;
 }
 function redraw(){
   head.replaceChildren();tbody.replaceChildren();foot.replaceChildren();
   const g=grid();if(!g){totals();return;}
   const tr=mk(head,"tr");
   mk(tr,"th","رنگ / سایز");
   for(const size of g.sizes){
     const th=mk(tr,"th",size);
     mk(th,"div","قیمت خرید هر عدد (تومان)",{class:"purchase-grid-meta"});
     const input=mk(th,"input",undefined,{type:"number",min:"1",step:"1",placeholder:"قیمت",class:"unit-price"});
     input.value=unitPrice[g.key+"|"+size]||"";
     input.addEventListener("input",()=>{unitPrice[g.key+"|"+size]=val(input.value);totals();});
   }
   const colors=[...new Set(g.rows.map(s=>s.color))];
   for(const color of colors){
     const tr=mk(tbody,"tr");mk(tr,"th",color);
     for(const size of g.sizes){
       const cell=mk(tr,"td");
       const sku=g.rows.find(s=>s.color===color&&s.size===size);
       if(!sku){mk(cell,"span","—");continue;}
       const input=mk(cell,"input",undefined,{type:"number",min:"0",step:"1",placeholder:"—","aria-label":color+" "+size});
       input.value=data[sku.id]||"";
       input.addEventListener("input",()=>{data[sku.id]=val(input.value);refreshFoot();totals();});
       mk(cell,"div","خانه: "+fmt(sku.home)+" / خورشید: "+fmt(sku.khorshid),{class:"purchase-grid-meta"});
     }
   }
   const final=mk(foot,"tr");mk(final,"th","تعداد کل");
   for(const size of g.sizes)mk(final,"th","۰",{id:"purchase-foot-"+g.sizes.indexOf(size)});
   refreshFoot();totals();
 }
 function refreshFoot(){
   const g=grid();if(!g)return;
   for(const [i,size] of g.sizes.entries()){
     const el=document.getElementById("purchase-foot-"+i);
     if(el)el.textContent=fmt(g.rows.filter(x=>x.size===size).reduce((v,x)=>v+(data[x.id]||0),0));
   }
 }
 cats.forEach(name=>mk(category,"option",name,{value:name}));
 category.addEventListener("change",refreshModels);
 model.addEventListener("change",redraw);
 discount.addEventListener("input",totals);
 document.getElementById("purchase-clear-grid").addEventListener("click",()=>{
   const g=grid();if(!g)return;for(const sku of g.rows)delete data[sku.id];
   redraw();
 });
 form.addEventListener("submit",event=>{
   hidden.replaceChildren();
   const rows=totals();
   if(rows.length===0){event.preventDefault();alert("حداقل یک تعداد کالا انتخاب کن.");return;}
   if(rows.length>20){event.preventDefault();alert("در هر رسید حداکثر ۲۰ رنگ/سایز ثبت کن.");return;}
   const pct=val(discount.value);
   if(pct<0||pct>=100||!Number.isFinite(pct)){
     event.preventDefault();alert("درصد تخفیف باید کمتر از ۱۰۰ باشد.");return;
   }
   if(rows.some(r=>!Number.isInteger(r.count)||r.count<=0||r.count>100000||!Number.isInteger(r.price)||r.price<=0)){
     event.preventDefault();alert("برای تمام تعدادهای واردشده، قیمت صحیح همان سایز را وارد کن.");return;
   }
   rows.forEach((r,i)=>{
     for(const [label,value] of [["master",r.id],["qty",r.count],["cost",r.price]]){
       mk(hidden,"input",undefined,{type:"hidden",name:label+"_"+(i+1),value:String(value)});
     }
   });
 });
 refreshModels();
})();
</script>
""".replace("__DATA__",safe)
    return body
