from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .daily_order_import_v8 import DailyOrderImportError
from .daily_order_import_v23 import (
    apply_delivery_preview,
    preview_delivery_report,
    preview_delivery_reports,
)
from .finance import is_digikala_zero_commission_date
from .finance_excel_v9 import sync_sale_receivable
from .models import ProductSize, SaleDay, SaleLine, StockBalance
from .sale_price_v60 import sale_price_for


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
            totals[brand_name] += (
                int(line.inventory_applied_quantity or 0)
                * int(line.product_size.product.pack_qty or 0)
            )
    return totals


def _preseed_date_effective_prices_from_preview(day, preview):
    if preview.get("errors"):
        raise DailyOrderImportError("\n".join(preview["errors"]))

    unique_keys = {
        (row["brand"], row["code"], row["size"])
        for row in preview.get("rows", [])
        if row.get("brand") in BRANDS
    }
    seeded = 0
    for brand_name, code, size_name in sorted(unique_keys):
        ps = ProductSize.objects.select_related("product__brand", "size").get(
            product__brand__name=brand_name,
            product__code=code,
            size__name=size_name,
            active=True,
            product__active=True,
        )
        line = SaleLine.objects.select_for_update().filter(day=day, product_size=ps).first()
        if line is None:
            price = int(sale_price_for(ps, day.date))
            if price <= 0:
                raise DailyOrderImportError(
                    f"قیمت فروش {code} / {size_name} برای تاریخ صورت صفر است؛ "
                    "قبل از Import قیمت تاریخ‌دار را تعیین کن."
                )
            SaleLine.objects.create(day=day, product_size=ps, quantity=0, sale_price=price)
            seeded += 1
        elif int(line.sale_price or 0) <= 0 and int(line.quantity or 0) <= 0:
            price = int(sale_price_for(ps, day.date))
            if price <= 0:
                raise DailyOrderImportError(
                    f"قیمت فروش {code} / {size_name} برای تاریخ صورت صفر است."
                )
            line.sale_price = price
            line.save(update_fields=["sale_price"])
            seeded += 1
    return seeded


def _preseed_date_effective_prices(day, file_bytes, filename):
    return _preseed_date_effective_prices_from_preview(
        day, preview_delivery_report(file_bytes, filename)
    )


@transaction.atomic
def apply_delivery_report_v60(day, file_bytes, filename=""):
    preview = preview_delivery_report(file_bytes, filename)
    _preseed_date_effective_prices_from_preview(day, preview)
    return apply_delivery_preview(day, preview)


@transaction.atomic
def apply_delivery_reports_v60(day, reports):
    preview = preview_delivery_reports(reports)
    _preseed_date_effective_prices_from_preview(day, preview)
    return apply_delivery_preview(day, preview)


@login_required
@require_POST
@transaction.atomic
def import_daily_orders(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)
    uploads = request.FILES.getlist("orders_file")
    if not uploads:
        messages.error(request, "فایل اکسل سفارش روزانه را انتخاب کن.")
        return redirect("sale_brand", day_id=day.id)

    reports = []
    for uploaded in uploads:
        filename = uploaded.name or "orders.xlsx"
        if not filename.lower().endswith(".xlsx"):
            messages.error(request, f"فقط فایل XLSX دیجی‌کالا قابل قبول است: {filename}")
            return redirect("sale_brand", day_id=day.id)
        reports.append((uploaded.read(), filename))

    try:
        before_stock = _brand_stock_totals()
        before_applied = _day_applied_shorts(day)
        result = apply_delivery_reports_v60(day, reports)

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
    file_count = int(result.get("files_count") or len(reports) or 1)
    source_text = "یک فایل" if file_count == 1 else f"{file_count} فایل تجمیع‌شده"
    messages.success(
        request,
        f"{source_text} ثبت شد: {result['grouped_lines']} ردیف تجمیعی، "
        f"{result['total_quantity']} کالا. طلب خالص دیجی‌کالا برای این روز: "
        f"{receivable_text} تومان.",
    )
    if is_digikala_zero_commission_date(day.date):
        messages.info(
            request,
            "استثنای ۸ مهر ۱۴۰۵ اعمال شد: کمیسیون دیجی‌کالا صفر است؛ هزینه پردازش و مالیات مربوط به پردازش طبق فرمول معمول محاسبه شده است.",
        )
    if result.get("shortage_count"):
        messages.warning(
            request,
            f"{result['shortage_count']} کمبود موجودی ایجاد شد؛ از ویرایش روز می‌توانی جایگزینی رنگ را مشخص کنی.",
        )
    return redirect("daily_report", day_id=day.id)
