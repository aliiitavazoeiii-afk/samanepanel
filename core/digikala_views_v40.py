from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .digikala_center_v44 import (
    get_daily_orders_center,
    get_package_detail,
    get_packages_board,
    get_products_board,
    get_returns_board,
    get_sales_board,
)
from .digikala_client_v40 import DigikalaAPIError, get_summary
from .digikala_delivery_v41 import DELIVERY_CACHE_KEY, get_delivery_board
from .digikala_warehouse_v42 import get_free_warehouse_board


@login_required
@require_GET
def digikala_home(request):
    # V44: center home must open immediately. Do not fan out to Digikala here.
    # Show the latest cached delivery value if another Digikala page already loaded it.
    delivery = cache.get(DELIVERY_CACHE_KEY) or {
        "effective_total": None,
        "total_commitments": None,
        "delayed_total": None,
    }
    return render(
        request,
        "core/digikala_center_v43.html",
        {
            "delivery": delivery,
            "dk_section": "home",
        },
    )


@login_required
@require_GET
def digikala_summary(request):
    try:
        force = request.GET.get("refresh") == "1"
        summary = get_summary(force=force)
        delivery = get_delivery_board(force=force)
        summary["delivery_effective_total"] = delivery.get("effective_total", 0)
        summary["delivery_total_commitments"] = delivery.get("total_commitments", 0)
        summary["delivery_delayed_total"] = delivery.get("delayed_total", 0)
        summary["delivery_variant_count"] = delivery.get("variant_count", 0)
        summary["delivery_counts_match"] = delivery.get("counts_match", True)
        return JsonResponse({"ok": True, "data": summary})
    except DigikalaAPIError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)


@login_required
@require_GET
def digikala_orders(request):
    force = request.GET.get("refresh") == "1"
    try:
        orders = get_daily_orders_center(force=force)
        page_error = ""
    except DigikalaAPIError as exc:
        orders = {
            "tomorrow_products": [], "day_after_products": [], "later_products": [], "delayed_products": [],
            "tomorrow_total": 0, "day_after_total": 0, "later_total": 0, "delayed_total": 0,
            "date_split_ok": False, "date_split_error": str(exc),
        }
        page_error = str(exc)
    order_sections = [
        (f"تحویل فردا · {orders.get('tomorrow_jalali', '—')}", orders.get("tomorrow_products", []), orders.get("tomorrow_total", 0)),
        (f"تحویل پس‌فردا · {orders.get('day_after_jalali', '—')}", orders.get("day_after_products", []), orders.get("day_after_total", 0)),
        ("روزهای بعد", orders.get("later_products", []), orders.get("later_total", 0)),
        ("عقب‌افتاده", orders.get("delayed_products", []), orders.get("delayed_total", 0)),
    ]
    return render(request, "core/digikala_orders_v43.html", {
        "orders": orders, "order_sections": order_sections, "digikala_error": page_error, "dk_section": "orders",
    })


@login_required
@require_GET
def digikala_products(request):
    force = request.GET.get("refresh") == "1"
    try:
        products = get_products_board(force=force)
        page_error = ""
    except DigikalaAPIError as exc:
        products = {"rows": [], "product_count": 0, "variant_count": 0}
        page_error = str(exc)
    return render(request, "core/digikala_products_v44.html", {
        "products": products, "digikala_error": page_error, "dk_section": "products",
    })


@login_required
@require_GET
def digikala_packages(request):
    force = request.GET.get("refresh") == "1"
    packages = get_packages_board(force=force)
    return render(request, "core/digikala_packages_v43.html", {"packages": packages, "dk_section": "packages"})


@login_required
@require_GET
def digikala_package_detail(request, package_id):
    try:
        package = get_package_detail(package_id)
        page_error = ""
    except DigikalaAPIError as exc:
        package = {"package_id": package_id, "status": "—", "variants": [], "total_quantity": 0}
        page_error = str(exc)
    return render(request, "core/digikala_package_detail_v43.html", {
        "package": package, "digikala_error": page_error, "dk_section": "packages",
    })


@login_required
@require_GET
def digikala_sales(request):
    force = request.GET.get("refresh") == "1"
    try:
        sales = get_sales_board(force=force)
        page_error = ""
    except DigikalaAPIError as exc:
        sales = {
            "jalali_month": "—", "total_quantity": 0, "order_rows": 0, "product_count": 0,
            "top_products": [], "bottom_products": [], "source_rows_scanned": 0, "price_ready": False,
        }
        page_error = str(exc)
    return render(request, "core/digikala_sales_v43.html", {
        "sales": sales, "digikala_error": page_error, "dk_section": "sales",
    })


@login_required
@require_GET
def digikala_warehouse(request):
    force = request.GET.get("refresh") == "1"
    try:
        warehouse = get_free_warehouse_board(force=force)
        page_error = ""
    except DigikalaAPIError as exc:
        warehouse = {
            "rows": [], "sellable_total": 0, "reserved_total": 0, "free_total": 0,
            "variant_count": 0, "free_variant_count": 0, "zero_variant_count": 0, "reserve_over_stock_total": 0,
        }
        page_error = str(exc)
    return render(request, "core/digikala_warehouse_v42.html", {
        "warehouse": warehouse, "digikala_error": page_error, "dk_section": "warehouse",
    })


@login_required
@require_GET
def digikala_returns(request):
    force = request.GET.get("refresh") == "1"
    try:
        returns = get_returns_board(force=force)
        page_error = ""
    except DigikalaAPIError as exc:
        returns = {"rows": [], "total": 0, "variant_count": 0, "source_rows_scanned": 0}
        page_error = str(exc)
    return render(request, "core/digikala_returns_v43.html", {
        "returns": returns, "digikala_error": page_error, "dk_section": "returns",
    })
