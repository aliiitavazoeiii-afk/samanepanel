(function(){
  function moneyNumber(value){return Number(String(value||'').replace(/[٬,\s]/g,''))||0;}
  function qtyNumber(value){return Number(String(value||'').replace(/٬/g,'').replace(/\s/g,'').replace(',','.'))||0;}
  function formatMoney(value){return Math.round(value||0).toLocaleString('en-US').replace(/,/g,'٬');}

  var payloads={};
  var dataNode=document.getElementById('elastic-multi-v60-data');
  if(dataNode){try{payloads=JSON.parse(dataNode.textContent||'{}')||{};}catch(_e){payloads={};}}

  var style=document.createElement('style');
  style.textContent='.elastic-multi-table{display:grid;gap:8px;margin-top:8px}.elastic-multi-head,.elastic-color-row{display:grid;grid-template-columns:minmax(115px,1.2fr) repeat(4,minmax(105px,1fr));gap:8px;align-items:end}.elastic-multi-head{font-size:.68rem;color:#9fb0c4;padding:0 5px}.elastic-color-row{border:1px solid rgba(255,255,255,.09);background:rgba(255,255,255,.025);border-radius:11px;padding:9px}.elastic-color-label{font-weight:850;align-self:center}.elastic-color-row input{text-align:center}.elastic-multi-note{font-size:.76rem;color:#aebdcd;margin-top:8px}@media(max-width:767.98px){.elastic-multi-head{display:none}.elastic-color-row{grid-template-columns:1fr 1fr}.elastic-color-label{grid-column:1/-1}.elastic-color-row .v60-field:before{display:block;font-size:.64rem;color:#91a5bb;margin-bottom:4px}.elastic-color-row .q16:before{content:"کیلو 16"}.elastic-color-row .p16:before{content:"فی 16"}.elastic-color-row .q25:before{content:"کیلو 25"}.elastic-color-row .p25:before{content:"فی 25"}}';
  document.head.appendChild(style);

  function paymentId(form){
    var action=form.getAttribute('action')||'';
    var m=action.match(/\/payments\/(\d+)\/edit\/?/);
    return m?m[1]:null;
  }

  function valuesFromPayload(form, selectedKey, legacy){
    var map={};
    var id=paymentId(form);
    var payload=id?payloads[id]:null;
    if(payload&&payload.k==='elastic_multi'){
      (payload.items||[]).forEach(function(item){map[item.m]=item;});
    }else if(selectedKey&&(legacy.q16||legacy.p16||legacy.q25||legacy.p25)){
      map[selectedKey]={m:selectedKey,q16:legacy.q16,p16:legacy.p16,q25:legacy.q25,p25:legacy.p25};
    }
    return map;
  }

  function field(cls,name,value,inputmode){
    var wrap=document.createElement('div');
    wrap.className='v60-field '+cls;
    var input=document.createElement('input');
    input.className='form-control '+(cls==='q16'||cls==='q25'?'ltr material-qty':'money-input material-price');
    input.name=name;
    input.value=value||'';
    input.inputMode=inputmode;
    wrap.appendChild(input);
    return wrap;
  }

  function upgradeForm(form){
    var box=form.querySelector('.elastic-fields');
    if(!box||box.dataset.v60Multi==='1')return;
    var oldGrid=box.querySelector('.material-grid');
    var select=box.querySelector('select[name="material_key"]');
    if(!oldGrid||!select)return;

    var q16=box.querySelector('[name="elastic16_qty"]');
    var p16=box.querySelector('[name="elastic16_price"]');
    var q25=box.querySelector('[name="elastic25_qty"]');
    var p25=box.querySelector('[name="elastic25_price"]');
    var legacy={q16:q16&&q16.value,p16:p16&&p16.value,q25:q25&&q25.value,p25:p25&&p25.value};
    var selectedKey=select.value;
    var preset=valuesFromPayload(form,selectedKey,legacy);

    var table=document.createElement('div');
    table.className='elastic-multi-table';
    var head=document.createElement('div');
    head.className='elastic-multi-head';
    ['رنگ کش','کیلو کش 16','فی کش 16','کیلو کش 25','فی کش 25'].forEach(function(text){var d=document.createElement('div');d.textContent=text;head.appendChild(d);});
    table.appendChild(head);

    Array.from(select.options).forEach(function(opt){
      var key=opt.value;
      if(!key)return;
      var vals=preset[key]||{};
      var row=document.createElement('div');
      row.className='elastic-color-row';
      row.dataset.materialKey=key;
      var label=document.createElement('div');
      label.className='elastic-color-label';
      label.textContent=opt.textContent.trim();
      row.appendChild(label);
      row.appendChild(field('q16','elastic16_qty__'+key,vals.q16,'decimal'));
      row.appendChild(field('p16','elastic16_price__'+key,vals.p16,'numeric'));
      row.appendChild(field('q25','elastic25_qty__'+key,vals.q25,'decimal'));
      row.appendChild(field('p25','elastic25_price__'+key,vals.p25,'numeric'));
      table.appendChild(row);
    });

    oldGrid.replaceWith(table);
    var sub=box.querySelector('.subheader');
    if(sub)sub.textContent='جزئیات کش — همه رنگ‌های خرید را در همین یک پرداخت وارد کن';
    var hint=document.createElement('div');
    hint.className='elastic-multi-note';
    hint.textContent='فیلدهای خالی نادیده گرفته می‌شوند. می‌توانی چند رنگ و هر دو نوع کش 16 و 25 را همزمان ثبت کنی.';
    table.after(hint);
    box.dataset.v60Multi='1';
  }

  function calcMulti(form){
    var sel=form.querySelector('.payee-select');
    if(!sel||sel.value!=='elastic')return;
    var total=0;
    form.querySelectorAll('.elastic-color-row').forEach(function(row){
      var q16=row.querySelector('[name^="elastic16_qty__"]');
      var p16=row.querySelector('[name^="elastic16_price__"]');
      var q25=row.querySelector('[name^="elastic25_qty__"]');
      var p25=row.querySelector('[name^="elastic25_price__"]');
      total+=qtyNumber(q16&&q16.value)*moneyNumber(p16&&p16.value);
      total+=qtyNumber(q25&&q25.value)*moneyNumber(p25&&p25.value);
    });
    form.querySelectorAll('.elastic-fields .invoice-preview').forEach(function(el){el.textContent=formatMoney(total);});
  }

  document.querySelectorAll('.payment-form').forEach(function(form){
    upgradeForm(form);
    form.addEventListener('input',function(e){if(e.target.closest('.elastic-color-row'))calcMulti(form);});
    var sel=form.querySelector('.payee-select');
    if(sel)sel.addEventListener('change',function(){setTimeout(function(){calcMulti(form);},0);});
    calcMulti(form);
  });
})();
