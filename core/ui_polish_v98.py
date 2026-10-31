class V98PresentationMiddleware:
    """Presentation cache guard for ERP HTML.

    V103 renders Finance navigation natively in base.html. This middleware no
    longer rewrites navigation HTML; it only prevents stale rendered ERP pages
    and provides a cache-busted helper fallback if a page omits it.
    """

    SCRIPT = '<script src="/static/core/number_format.js?v=103"></script>'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(response, "streaming", False):
            return response
        content_type = response.get("Content-Type", "")
        if response.status_code != 200 or "text/html" not in content_type:
            return response

        content = response.content.decode("utf-8", errors="replace")
        if "core/number_format.js" not in content:
            return response

        if self.SCRIPT not in content and "</body>" in content:
            content = content.replace("</body>", self.SCRIPT + "</body>", 1)

        response.content = content.encode("utf-8")
        native_finance = 'data-finance-root-nav="base-v103"' in content
        response["X-Darma-Finance-Nav-V103"] = "native" if native_finance else "missing"
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response
