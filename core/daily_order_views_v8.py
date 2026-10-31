from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .daily_order_import_v8 import DailyOrderImportError
from .daily_order_import_v23 import apply_delivery_report
from .finance_excel_v9 import sync_sale_receivable
from .models import SaleDay, StockBalance


BRANDS = ("دارما", "تکوین")


def _brand_stock_totals():
    result = {}
    for brand_name in BRANDS:
        result[brand_name] = int(
            StockBalance.objects.filter(brand__name=brand_name).aggregate(v=Sum("qty"))["v"] or 0
        )
    return result


def _day_applied_shorts(day):
    totals = {name: 0 for name in BRANDS}
    for line in day.lines.select_related("product_size__product__brand", "product_size__product").all():
        brand_name = line.product_size.product.brand.name
        if brand_name in totals:
            totals[brand_name] += int(line.inventory_applied_quantity or 0) * int(line.product_size.product.pack_qty or 0)
    return totals


@login_required
@require_POST
@transaction.atomic
def import_daily_orders(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)
    uploaded = request.FILES.get("orders_file")
    if uploaded is None:
        messages.error(request, "فایل اکسل سفارش روزانه را انتخاب کن.")
        return redirect("sale_brand", day_id=day.id)

    filename = uploaded.name or "orders.xlsx"
    if not filename.lower().endswith(".xlsx"):
        messages.error(request, "فقط فایل XLSX دیجی‌کالا قابل قبول است.")
        return redirect("sale_brand", day_id=day.id)

    try:
        before_stock = _brand_stock_totals()
        before_applied = _day_applied_shorts(day)

        data = uploaded.read()
        result = apply_delivery_report(day, data, filename)

        after_stock = _brand_stock_totals()
        after_applied = _day_applied_shorts(day)
        for brand_name in BRANDS:
            expected_stock_change = before_applied[brand_name] - after_applied[brand_name]
            actual_stock_change = after_stock[brand_name] - before_stock[brand_name]
            if actual_stock_change != expected_stock_change:
                raise DailyOrderImportError(
                    f"محافظ موجودی {brand_name}: تغییر واقعی موجودی {actual_stock_change:+d} عدد بود، "
                    f"ولی بر اساس صورت باید {expected_stock_change:+d} عدد می‌بود. کل ورود فایل لغو شد."
                )

        receivable_added = 0
        for line in day.lines.select_related(
            "day", "product_size__product", "product_size__size"
        ).all():
            receivable_added += int(sync_sale_receivable(line) or 0)
        result["digikala_receivable_added"] = receivable_added
    except DailyOrderImportError as exc:
        transaction.set_rollback(True)
        for line in str(exc).splitlines():
            if line.strip():
                messages.error(request, line.strip())
        return redirect("sale_brand", day_id=day.id)
    except Exception as exc:
        transaction.set_rollback(True)
        messages.error(request, f"ورود فایل انجام نشد: {exc}")
        return redirect("sale_brand", day_id=day.id)

    receivable_text = f"{result['digikala_receivable_added']:,}".replace(",", "٬")
    messages.success(
        request,
        f"فایل {result['filename']} ثبت شد: {result['grouped_lines']} ردیف تجمیعی، "
        f"{result['total_quantity']} کالا. طلب خالص دیجی‌کالا برای این روز: "
        f"{receivable_text} تومان.",
    )
    if result.get("shortage_count"):
        messages.warning(
            request,
            f"{result['shortage_count']} کمبود موجودی ایجاد شد؛ از ویرایش روز می‌توانی جایگزینی رنگ را مشخص کنی.",
        )
    return redirect("daily_report", day_id=day.id)
