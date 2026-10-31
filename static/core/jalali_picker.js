(function(){
  if(window.__darmaJalaliPickerLoaded){
    window.DarmaJalaliPicker?.attach?.(document);
    return;
  }
  window.__darmaJalaliPickerLoaded=true;
  window.__darmaJalaliPickerLoading=false;

  const selectors = [
    'input:not([type="hidden"]).jalali-date',
    'input:not([type="hidden"]).jalali-picker',
    'input:not([type="hidden"])[data-jalali-date]',
    'input:not([type="hidden"])[name="date"]',
    'input:not([type="hidden"])[name="start"]',
    'input:not([type="hidden"])[name="end"]',
    'input:not([type="hidden"])[name="effective_from"]',
    'input:not([type="hidden"])[name="effective_to"]',
    'input:not([type="hidden"])[name="receipt_from"]',
    'input:not([type="hidden"])[name="receipt_to"]',
    'input:not([type="hidden"])[name*="date"]',
    'input:not([type="hidden"])[id*="date"]',
    'input:not([type="hidden"])[placeholder*="تاریخ"]'
  ].join(',');
  let activeInput = null;
  let overlay = null;

  function addStyles(){
    if(document.getElementById('jalali-picker-style')) return;
    const style=document.createElement('style');
    style.id='jalali-picker-style';
    style.textContent=`
      .jp-input{cursor:pointer!important;padding-left:38px!important;background-image:linear-gradient(45deg,transparent 50%,#f79009 50%),linear-gradient(135deg,#f79009 50%,transparent 50%)!important;background-position:18px 17px,23px 17px!important;background-size:5px 5px,5px 5px!important;background-repeat:no-repeat!important}
      .jp-overlay{position:fixed;inset:0;z-index:4000;background:rgba(1,8,18,.68);display:grid;place-items:center;padding:18px;backdrop-filter:blur(8px)}
      .jp-modal{width:min(420px,100%);background:linear-gradient(135deg,rgba(18,43,72,.78),rgba(5,19,34,.72));border:1px solid rgba(255,255,255,.18);box-shadow:0 28px 80px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(28px) saturate(140%);border-radius:18px;color:#f7f9fc;padding:16px;direction:rtl}
      .jp-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.jp-title{font-weight:900;font-size:1.08rem}.jp-nav{border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06);color:#fff;border-radius:10px;padding:8px 12px;cursor:pointer}.jp-nav:hover{border-color:#fb6514;background:rgba(251,101,20,.12)}
      .jp-week,.jp-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}.jp-week{margin-bottom:6px}.jp-week span{font-size:.72rem;color:#9fb0c4;text-align:center;padding:5px 0}.jp-day{min-height:48px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.035);color:#eef4fa;border-radius:10px;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;transition:.15s}.jp-day:hover{border-color:#fb6514;background:rgba(251,101,20,.10);transform:translateY(-1px)}.jp-day.today{box-shadow:inset 0 0 0 2px #fb6514}.jp-day.holiday{color:#ff746a;border-color:rgba(240,68,56,.24);background:rgba(240,68,56,.055)}.jp-day small{font-size:.52rem;line-height:1.1;max-width:45px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.jp-empty{min-height:48px}.jp-close{margin-top:12px;width:100%;border:0;background:rgba(255,255,255,.055);color:#cbd7e3;border-radius:10px;padding:9px;cursor:pointer}.jp-close:hover{background:rgba(255,255,255,.09)}
    `;
    document.head.appendChild(style);
  }

  function ensureOverlay(){
    if(overlay) return overlay;
    overlay=document.createElement('div');
    overlay.className='jp-overlay';
    overlay.style.display='none';
    overlay.innerHTML='<div class="jp-modal" role="dialog" aria-modal="true"><div id="jp-body"></div><button type="button" class="jp-close">بستن</button></div>';
    overlay.addEventListener('click',e=>{if(e.target===overlay) close();});
    overlay.querySelector('.jp-close').addEventListener('click',close);
    document.body.appendChild(overlay);
    return overlay;
  }

  function close(){ if(overlay) overlay.style.display='none'; activeInput=null; }

  async function loadMonth(params={}){
    if(!activeInput) return;
    const q=new URLSearchParams();
    if(activeInput.value) q.set('value',activeInput.value);
    if(params.jy) q.set('jy',params.jy);
    if(params.jm) q.set('jm',params.jm);
    const res=await fetch('/calendar/picker/?'+q.toString(),{headers:{'X-Requested-With':'XMLHttpRequest'}});
    if(!res.ok) throw new Error('calendar');
    render(await res.json());
  }

  function render(data){
    const body=ensureOverlay().querySelector('#jp-body');
    let html=`<div class="jp-head"><button type="button" class="jp-nav" data-y="${data.prev_y}" data-m="${data.prev_m}">‹ ماه قبل</button><div class="jp-title">${data.month_name} <span dir="ltr">${data.jy}</span></div><button type="button" class="jp-nav" data-y="${data.next_y}" data-m="${data.next_m}">ماه بعد ›</button></div>`;
    html+='<div class="jp-week">'+data.weekdays.map(w=>`<span>${w}</span>`).join('')+'</div><div class="jp-grid">';
    data.weeks.flat().forEach(cell=>{
      if(!cell){html+='<div class="jp-empty"></div>';return;}
      const cls=['jp-day',cell.is_today?'today':'',cell.is_holiday?'holiday':''].filter(Boolean).join(' ');
      const title=cell.holiday_name?` title="${String(cell.holiday_name).replace(/"/g,'&quot;')}"`:'';
      html+=`<button type="button" class="${cls}" data-value="${cell.value}"${title}><strong>${cell.day}</strong>${cell.holiday_name?`<small>${cell.holiday_name}</small>`:''}</button>`;
    });
    html+='</div>';
    body.innerHTML=html;
    body.querySelectorAll('.jp-nav').forEach(b=>b.addEventListener('click',()=>loadMonth({jy:b.dataset.y,jm:b.dataset.m})));
    body.querySelectorAll('.jp-day').forEach(b=>b.addEventListener('click',()=>{
      if(!activeInput) return;
      activeInput.value=b.dataset.value;
      if(['start','end','receipt_from','receipt_to'].includes(activeInput.name)){
        const period=activeInput.form?.querySelector('select[name="period"]');
        if(period) period.value='custom';
      }
      activeInput.dispatchEvent(new Event('input',{bubbles:true}));
      activeInput.dispatchEvent(new Event('change',{bubbles:true}));
      close();
    }));
  }

  function attach(root=document){
    if(!root) return;
    const inputs=[];
    if(root.matches?.(selectors)) inputs.push(root);
    root.querySelectorAll?.(selectors).forEach(input=>inputs.push(input));
    inputs.forEach(input=>{
      if(input.dataset.jpReady) return;
      input.dataset.jpReady='1';
      input.readOnly=true;
      input.autocomplete='off';
      input.classList.add('jp-input','ltr');
      input.addEventListener('click',()=>{
        activeInput=input;
        ensureOverlay().style.display='grid';
        loadMonth().catch(()=>close());
      });
      input.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click();}});
    });
  }

  addStyles();
  ensureOverlay();
  attach();
  window.DarmaJalaliPicker={attach,close};
  document.addEventListener('DOMContentLoaded',()=>attach(document));
  document.addEventListener('htmx:afterSwap',e=>attach(e.target));
  const observer=new MutationObserver(records=>{
    records.forEach(record=>record.addedNodes.forEach(node=>{
      if(node.nodeType===1) attach(node);
    }));
  });
  observer.observe(document.body,{childList:true,subtree:true});
  document.addEventListener('keydown',e=>{if(e.key==='Escape') close();});
})();
