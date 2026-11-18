/* Shamsi-only presentation. Never replace ISO values sent to the server. */
(function () {
  "use strict";
  const months=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
  const digits="۰۱۲۳۴۵۶۷۸۹";
  const fmt=new Intl.DateTimeFormat("fa-IR-u-ca-persian", {year:"numeric",month:"numeric",day:"numeric",timeZone:"UTC"});
  function en(s){return String(s).replace(/[۰-۹٠-٩]/g,c=>{let n=digits.indexOf(c);return String(n<0?"٠١٢٣٤٥٦٧٨٩".indexOf(c):n);});}
  function fa(s){return String(s).replace(/[0-9]/g,d=>digits[Number(d)]);}
  function tehranToday(){
    const p={};new Intl.DateTimeFormat("en-US",{year:"numeric",month:"2-digit",day:"2-digit",timeZone:"Asia/Tehran"}).formatToParts(new Date()).forEach(v=>{p[v.type]=v.value;});
    return p.year+"-"+p.month+"-"+p.day;
  }
  function isoToParts(value){
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const date=new Date(value+"T12:00:00Z");
    if(Number.isNaN(date.valueOf()))return null;
    const p={};fmt.formatToParts(date).forEach(v=>{p[v.type]=Number(en(v.value));});
    return [p.year,p.month,p.day];
  }
  function jToG(y,m,d){
    y+=1595;let days=-355668+365*y+Math.floor(y/33)*8+Math.floor((y%33+3)/4)+d+(m<7?(m-1)*31:(m-7)*30+186);
    let gy=400*Math.floor(days/146097);days%=146097;
    if(days>36524){days--;gy+=100*Math.floor(days/36524);days%=36524;if(days>=365)days++;}
    gy+=4*Math.floor(days/1461);days%=1461;
    if(days>365){gy+=Math.floor((days-1)/365);days=(days-1)%365;}
    let gd=days+1,monthDays=[0,31,gy%4===0&&(gy%100!==0||gy%400===0)?29:28,31,30,31,30,31,31,30,31,30,31];
    for(let gm=1;gm<=12;gm++){if(gd<=monthDays[gm])return [gy,gm,gd];gd-=monthDays[gm];}
    return null;
  }
  function toIso(a){return a[0]+"-"+String(a[1]).padStart(2,"0")+"-"+String(a[2]).padStart(2,"0");}
  function show(value){
    const p=isoToParts(value);return p?fa(p[0]+"/"+String(p[1]).padStart(2,"0")+"/"+String(p[2]).padStart(2,"0")):value;
  }
  const css=document.createElement("style");
  css.textContent=".sg-jal-trigger{min-height:40px;display:block;width:100%;text-align:right;border:1px solid rgba(160,180,210,.4);border-radius:9px;padding:9px 12px;color:inherit;background:rgba(100,130,170,.13);cursor:pointer}.sg-jal-overlay{position:fixed;inset:0;z-index:25000;background:#0008;display:grid;place-items:center;padding:12px}.sg-jal-panel{width:min(360px,100%);background:#10283e;color:#fff;border:1px solid #54758a;border-radius:16px;padding:15px;box-shadow:0 16px 50px #0009;direction:rtl}.sg-jal-header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.sg-jal-panel button{color:#fff;background:#234860;border:1px solid #476d89;border-radius:7px;padding:7px;cursor:pointer}.sg-jal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center}.sg-jal-grid small{padding:6px 0}.sg-jal-grid button{padding:8px 0}.sg-jal-grid button:disabled{opacity:.25;cursor:default}.sg-jal-grid button[aria-current=date]{background:#e87734}.sg-jal-footer{display:flex;justify-content:space-between;gap:8px;margin-top:12px}";
  document.head.appendChild(css);
  function picker(field,trigger){
    const overlay=document.createElement("div");overlay.className="sg-jal-overlay";
    const panel=document.createElement("section");panel.className="sg-jal-panel";panel.setAttribute("role","dialog");panel.setAttribute("aria-label","تقویم شمسی");overlay.appendChild(panel);
    const original=isoToParts(field.value)||isoToParts(tehranToday());
    let y=original[0],m=original[1];
    function close(){overlay.remove();trigger.focus();}
    overlay.addEventListener("click",e=>{if(e.target===overlay)close();});
    const onKey=e=>{if(e.key==="Escape"){document.removeEventListener("keydown",onKey);close();}};
    document.addEventListener("keydown",onKey);
    function add(parent,tag,value,click){
      const el=document.createElement(tag);el.textContent=value;if(click)el.addEventListener("click",click);
      parent.appendChild(el);return el;
    }
    function move(delta){m+=delta;if(m>12){m=1;y++;}else if(m<1){m=12;y--;}render();}
    function render(){
      panel.replaceChildren();
      const header=add(panel,"div","");header.className="sg-jal-header";
      add(header,"button","ماه قبل",()=>move(-1)).type="button";
      add(header,"strong",months[m-1]+" "+fa(y));
      add(header,"button","ماه بعد",()=>move(1)).type="button";
      const grid=add(panel,"div","");grid.className="sg-jal-grid";
      ["ش","ی","د","س","چ","پ","ج"].forEach(w=>add(grid,"small",w));
      const start=jToG(y,m,1),next=m===12?jToG(y+1,1,1):jToG(y,m+1,1);
      if(!start||!next)return;
      const from=Date.UTC(start[0],start[1]-1,start[2]),to=Date.UTC(next[0],next[1]-1,next[2]);
      const offset=(new Date(from).getUTCDay()+1)%7,days=Math.round((to-from)/86400000);
      for(let i=0;i<offset;i++)add(grid,"span","");
      for(let d=1;d<=days;d++){
        const date=toIso(jToG(y,m,d));
        const b=add(grid,"button",fa(d),()=>{
          field.value=date;field.dispatchEvent(new Event("change",{bubbles:true}));trigger.textContent=show(date)+" ▾";document.removeEventListener("keydown",onKey);close();
        });b.type="button";b.disabled=!!(field.min&&date<field.min||field.max&&date>field.max);
        if(date===field.value)b.setAttribute("aria-current","date");
      }
      const footer=add(panel,"div","");footer.className="sg-jal-footer";
      add(footer,"button","امروز",()=>{
        const day=tehranToday();
        if((!field.min||day>=field.min)&&(!field.max||day<=field.max)){
          field.value=day;field.dispatchEvent(new Event("change",{bubbles:true}));trigger.textContent=show(day)+" ▾";
        }
        document.removeEventListener("keydown",onKey);close();
      }).type="button";
      add(footer,"button","بستن",()=>{document.removeEventListener("keydown",onKey);close();}).type="button";
    }
    render();document.body.appendChild(overlay);
  }
  function enhanceDates(){
    document.querySelectorAll('input[type="date"]:not(.jal-native):not([data-no-jalali])').forEach(field=>{
      if(field.closest("[data-jal]"))return;
      const button=document.createElement("button");button.type="button";button.className="sg-jal-trigger";
      button.textContent=field.value?show(field.value)+" ▾":"انتخاب تاریخ شمسی ▾";
      field.type="hidden";field.insertAdjacentElement("afterend",button);
      button.addEventListener("click",()=>picker(field,button));
    });
  }
  function translateTextDates(){
    const pattern=/(^|[^\d])((?:19|20)\d{2})[-\/](0[1-9]|1[0-2])[-\/](0[1-9]|[12]\d|3[01])(?=[^\d]|$)/g;
    const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    const replacements=[];
    while(walk.nextNode()){
      const node=walk.currentNode,p=node.parentElement;if(!p||p.closest("script,style,textarea,pre,code,noscript,option,[data-no-jalali]"))continue;
      const value=node.nodeValue;
      if(!pattern.test(value)){pattern.lastIndex=0;continue;}pattern.lastIndex=0;
      const updated=value.replace(pattern,(all,prefix,y,m,d)=>{
        const iso=y+"-"+m+"-"+d,translation=show(iso);return prefix+translation;
      });
      if(updated!==value)replacements.push([node,updated]);
    }
    replacements.forEach(([node,newText])=>{node.nodeValue=newText;});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>{enhanceDates();translateTextDates();});
  else{enhanceDates();translateTextDates();}
})();