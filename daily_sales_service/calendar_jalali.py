"""Offline Persian date picker; stored dates are ISO Gregorian."""
from html import escape

def picker(day,today_iso=None):
    d=escape(str(day),quote=True)
    now=escape(str(today_iso or day),quote=True)
    return (f'<div class="jal-box" data-jal data-today="{now}">'
            f'<input class="jal-native" type="date" name="sale_date" value="{d}" required>'
            f'<input class="jal-iso" type="hidden" name="sale_date" value="{d}" disabled>'
            '<button class="jal-button" type="button" hidden>تقویم شمسی</button>'
            '<div class="jal-panel" hidden></div></div>')

def label(day):
    d=escape(str(day),quote=True)
    return f'<span data-jal-label="{d}">{d}</span>'

CSS = """
<style>
.jal-box{position:relative;width:100%}
.jal-button{width:100%;min-height:46px;text-align:right;cursor:pointer;background:#142f49!important;color:#fff!important;border:1px solid #45647e!important}
.jal-button[hidden],.jal-panel[hidden]{display:none!important}
.jal-panel{position:absolute;z-index:600;top:calc(100% + 4px);right:0;padding:13px;width:min(335px,90vw);background:#10283e;border:1px solid #527492;border-radius:13px;box-shadow:0 17px 35px #0009;direction:rtl;color:white}
.jal-nav,.jal-foot{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px}
.jal-nav button,.jal-foot button{background:#25465e!important;color:white!important;padding:6px 9px!important;cursor:pointer;border:1px solid #496c86!important}
.jal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:5px;text-align:center}.jal-grid small{color:#acc1d2}.jal-grid button{background:#173b5b!important;color:white!important;padding:7px 0!important;cursor:pointer;border:1px solid #3a5974!important}.jal-grid button[aria-current=date]{background:#f1944a!important;color:#122437!important}
.m2-dk-delete{margin:17px 0;padding:14px;border:1px solid #8b4b50;border-radius:12px;background:#2a202d;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.m2-dk-delete button{background:#9e3443!important;color:#fff!important}
</style>
"""

JS1 = r"""
<script>
(function(){
"use strict";
var mons=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
var fmt=new Intl.DateTimeFormat("fa-IR-u-ca-persian",{year:"numeric",month:"numeric",day:"numeric",timeZone:"UTC"});
function en(x){var a="۰۱۲۳۴۵۶۷۸۹",b="٠١٢٣٤٥٦٧٨٩";return String(x).replace(/[۰-۹٠-٩]/g,function(ch){var i=a.indexOf(ch);return String(i>=0?i:b.indexOf(ch));});}
function fa(x){return String(x).replace(/[0-9]/g,function(d){return "۰۱۲۳۴۵۶۷۸۹"[Number(d)];});}
function g2j(s){var z={};fmt.formatToParts(new Date(s+"T12:00:00Z")).forEach(function(k){z[k.type]=en(k.value);});return [Number(z.year),Number(z.month),Number(z.day)];}
function j2g(y,m,d){
 y+=1595;var days=-355668+365*y+Math.floor(y/33)*8+Math.floor((y%33+3)/4)+d+(m<7?(m-1)*31:(m-7)*30+186);
 var gy=400*Math.floor(days/146097);days%=146097;
 if(days>36524){days--;gy+=100*Math.floor(days/36524);days%=36524;if(days>=365)days++;}
 gy+=4*Math.floor(days/1461);days%=1461;
 if(days>365){gy+=Math.floor((days-1)/365);days=(days-1)%365;}
 var gd=days+1,a=[0,31,(gy%4===0&&(gy%100!==0||gy%400===0))?29:28,31,30,31,30,31,31,30,31,30,31];
 for(var gm=1;gm<=12;gm++){if(gd<=a[gm])return [gy,gm,gd];gd-=a[gm];}
}
function iso(g){return g[0]+"-"+String(g[1]).padStart(2,"0")+"-"+String(g[2]).padStart(2,"0");}
function next(y,m,n){m+=n;if(m>12){m=1;y++;}if(m<1){m=12;y--;}return [y,m];}
function display(s){var j=g2j(s);return fa(j[2])+" "+mons[j[1]-1]+" "+fa(j[0]);}

"""
JS2 = r"""
document.querySelectorAll("[data-jal]").forEach(function(box){
 var native=box.querySelector(".jal-native"),isoField=box.querySelector(".jal-iso");
 var toggle=box.querySelector(".jal-button"),panel=box.querySelector(".jal-panel");
 var value=isoField.value,j=g2j(value),yy=j[0],mm=j[1];
 function node(tag,text,parent,click){var el=document.createElement(tag);el.textContent=text;if(click)el.onclick=click;parent.appendChild(el);return el;}
 function close(){panel.hidden=true;}
 function select(s){isoField.value=s;toggle.textContent=display(s)+" ▾";close();}
 function draw(){
  panel.replaceChildren();
  var nav=node("div","",panel);nav.className="jal-nav";
  node("button","ماه قبل",nav,function(){var a=next(yy,mm,-1);yy=a[0];mm=a[1];draw();});
  node("strong",mons[mm-1]+" "+fa(yy),nav);
  node("button","ماه بعد",nav,function(){var a=next(yy,mm,1);yy=a[0];mm=a[1];draw();});
  var a=j2g(yy,mm,1),b=next(yy,mm,1),c=j2g(b[0],b[1],1);
  var start=Date.UTC(a[0],a[1]-1,a[2]);
  var days=Math.round((Date.UTC(c[0],c[1]-1,c[2])-start)/86400000);
  var weekday=(new Date(start).getUTCDay()+1)%7;
  var grid=node("div","",panel);grid.className="jal-grid";
  ["ش","ی","د","س","چ","پ","ج"].forEach(function(x){node("small",x,grid);});
  for(var k=0;k<weekday;k++)node("span","",grid);
  for(var d=1;d<=days;d++){
   (function(day){var date=iso(j2g(yy,mm,day));
    var button=node("button",fa(day),grid,function(){select(date);});
    button.type="button";
    if(date===isoField.value)button.setAttribute("aria-current","date");
   })(d);
  }
  var foot=node("div","",panel);foot.className="jal-foot";
  node("button","امروز",foot,function(){select(box.dataset.today);});
  node("button","بستن",foot,close);
 }
 native.hidden=true;native.disabled=true;isoField.disabled=false;toggle.hidden=false;
 toggle.textContent=display(isoField.value)+" ▾";
 toggle.onclick=function(){if(!panel.hidden){close();return;}
  j=g2j(isoField.value);yy=j[0];mm=j[1];draw();panel.hidden=false;};
 box.jalClose=close;
});

"""
JS3 = r"""
document.querySelectorAll("[data-jal-label]").forEach(function(x){
 try{x.textContent=display(x.dataset.jalLabel);}catch(err){}
});
document.addEventListener("pointerdown",function(ev){
 document.querySelectorAll("[data-jal]").forEach(function(el){
  if(!el.contains(ev.target)&&el.jalClose)el.jalClose();
 });
});
document.addEventListener("keydown",function(ev){
 if(ev.key==="Escape")document.querySelectorAll("[data-jal]").forEach(
  function(el){if(el.jalClose)el.jalClose();});
});
})();
"""
ASSETS = CSS + JS1 + JS2 + JS3 + ("</scr" + "ipt>")
