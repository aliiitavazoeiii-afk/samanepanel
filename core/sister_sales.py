"""Django-authenticated proxy to the isolated, tested Samanepanel DigiKala engine.

All state remains in the separate sister-sales SQLite volume. The legacy Darma
ERP financial ledger is NOT modified by these transactions.
"""
import base64
import os
import re
import secrets
from urllib import error, parse, request as http_request

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.http import require_GET


@login_required
@require_GET
def channels(request):
    return render(request, "core/sister_sales_channels.html", {"selected": None})


def _placeholder(request, title):
    return render(request, "core/sister_sales_channels.html", {"selected": title})


@login_required
@require_GET
def site(request):
    return _placeholder(request, "فروش سایت")


@login_required
@require_GET
def basalam(request):
    return _placeholder(request, "فروش باسلام")


@login_required
@require_GET
def ghaleb(request):
    return _placeholder(request, "فروش قالب")


_ALLOWED = {"", "import", "preview", "commit", "inventory", "cost", "costs/upload",
            "stock/adjust", "settings", "setting", "api/report.json", "api/report.csv"}
_POST = {"preview", "commit", "cost", "costs/upload", "stock/adjust", "setting"}
_LIMIT = 64 * 1024 * 1024
_ROOT = "/sales/digikala"
_API = "/daily-sales"


class NoRedirect(http_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def multipart_body(request):
    boundary = "sb" + secrets.token_hex(16)
    chunks, total = [], 0

    def write(blob):
        nonlocal total
        total += len(blob)
        if total > _LIMIT:
            raise ValueError("حجم فایل‌های اکسل بیش از حد مجاز است.")
        chunks.append(blob)

    for name, values in request.POST.lists():
        if name == "csrfmiddlewaretoken":
            continue
        clean = name.replace('"', "_").replace("\r", "").replace("\n", "")
        for value in values:
            write(('--' + boundary + '\r\nContent-Disposition: form-data; name="' +
                   clean + '"\r\n\r\n').encode("utf-8"))
            write(value.encode("utf-8"))
            write(b"\r\n")
    for name, uploads in request.FILES.lists():
        clean = name.replace('"', "_").replace("\r", "").replace("\n", "")
        for uploaded in uploads:
            filename = os.path.basename(uploaded.name).replace('"', "_").replace("\r", "").replace("\n", "")
            content_type = (uploaded.content_type or "application/octet-stream").split(";")[0]
            if not re.fullmatch(r"[\w.+/-]+", content_type):
                content_type = "application/octet-stream"
            write(('--' + boundary + '\r\nContent-Disposition: form-data; name="' +
                   clean + '"; filename="' + filename + '"\r\nContent-Type: ' +
                   content_type + '\r\n\r\n').encode("utf-8"))
            for block in uploaded.chunks():
                write(block)
            write(b"\r\n")
    write(('--' + boundary + '--\r\n').encode("utf-8"))
    return b"".join(chunks), "multipart/form-data; boundary=" + boundary


def add_csrf(request, html):
    from html import escape
    csrf = escape(get_token(request), quote=True)

    def substitute(match):
        tag = match.group(0)
        if re.search(r"\bmethod=['\"]?post\b", tag, flags=re.I):
            return tag + '<input type="hidden" name="csrfmiddlewaretoken" value="' + csrf + '">'
        return tag
    return re.sub(r"<form\b[^>]*>", substitute, html, flags=re.I)


_DARK_CSS = """</style><style>
body{background:#06111f!important;color:#eef4fa!important}
header{background:#0b1c33!important;border-color:#2e4860!important}
header b,header nav a,h1,h2,h3{color:#fff!important}
header nav a,.card,.panel{background:#102642!important;color:#eef4fa!important;border-color:#2b4864!important}
p,label,.card small,footer,.faint{color:#b4c6d9!important}
table th{background:#163655!important;color:#f0f6ff!important}
table td{border-color:#24415d!important}
input,select{background:#182f4b!important;color:white!important;border-color:#365774!important}
.notice{background:#182d44!important;color:#ecf3fd!important;border-color:#b78a53!important}
</style></head>"""


@login_required
def digikala_proxy(request, tail=""):
    if tail not in _ALLOWED:
        return HttpResponse("مسیر نامعتبر است.", status=404)
    if request.method not in ("GET", "POST"):
        return HttpResponse("متد غیرمجاز است.", status=405)
    if request.method == "POST" and tail not in _POST:
        return HttpResponse("متد غیرمجاز است.", status=405)
    password = os.getenv("SALES_ADMIN_PASSWORD", "")
    if len(password) < 16:
        return HttpResponse("سرویس فروش دیجی‌کالا پیکربندی نشده است.", status=503)

    url = "http://sister-digikala:8018" + _API + "/" + tail
    if request.method == "GET" and request.META.get("QUERY_STRING"):
        url += "?" + request.META["QUERY_STRING"]
    headers = {"Authorization": "Basic " + base64.b64encode(("bridge:" + password).encode()).decode(),
               "Accept-Encoding": "identity"}
    data = None
    if request.method == "POST":
        if request.FILES or (request.content_type or "").startswith("multipart/form-data"):
            try:
                data, content_type = multipart_body(request)
            except ValueError as exc:
                return HttpResponse(str(exc), status=413)
        else:
            fields = [(k, v) for k, values in request.POST.lists() for v in values
                      if k != "csrfmiddlewaretoken"]
            data, content_type = parse.urlencode(fields).encode(), "application/x-www-form-urlencoded"
        if len(data) > _LIMIT:
            return HttpResponse("حجم درخواست بیش از حد مجاز است.", status=413)
        headers["Content-Type"] = content_type

    outbound = http_request.Request(url, data=data, headers=headers, method=request.method)
    try:
        upstream = http_request.build_opener(NoRedirect).open(outbound, timeout=50)
    except error.HTTPError as exc:
        upstream = exc
    except (OSError, error.URLError):
        return HttpResponse("سرویس دیجی‌کالا پاسخ نمی‌دهد. وضعیت کانتینر را بررسی کن.", status=503)

    with upstream:
        status = upstream.status
        raw = upstream.read(_LIMIT + 1)
        mime = upstream.headers.get("Content-Type", "text/plain")
        location = upstream.headers.get("Location", "")
        disposition = upstream.headers.get("Content-Disposition", "")
    if len(raw) > _LIMIT:
        return HttpResponse("پاسخ بیش از حد بزرگ است.", status=502)
    if 300 <= status < 400:
        if not location.startswith(_API + "/"):
            return HttpResponse("مسیر انتقال نامعتبر است.", status=502)
        res = HttpResponse(status=status)
        res["Location"] = _ROOT + location[len(_API):]
        return res
    if "text/html" in mime:
        html = raw.decode("utf-8", errors="replace").replace(_API, _ROOT)
        html = add_csrf(request, html)
        html = html.replace("<header>", '<header><a style="padding:8px 13px;text-decoration:none;border-radius:10px;background:#233f5a;color:#fff" href="/sales/">بازگشت به کانال‌ها</a>', 1)
        html = html.replace("</style></head>", _DARK_CSS, 1)
        res = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    else:
        res = HttpResponse(raw, status=status, content_type=mime)
        if disposition and "\n" not in disposition and "\r" not in disposition:
            res["Content-Disposition"] = disposition
    res["Cache-Control"] = "private, no-store"
    return res
