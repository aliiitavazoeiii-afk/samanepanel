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
