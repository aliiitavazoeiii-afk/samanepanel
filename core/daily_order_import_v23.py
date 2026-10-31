from __future__ import annotations

import os
import re
from collections import defaultdict

from django.db import transaction

from . import daily_order_import_v8 as base
from . import daily_order_import_v12 as v12
from .cost_accounting_v14 import snapshot_sale_line
from .final_services import sync_sale_inventory
from .models import AccountEntry, ProductSize, SaleDay, SaleLine
from .variant_sale_v12 import (
    VARIANT_PRODUCT_CODE,
    assert_stock_invariant,
    is_variable_color_product_code,
    sold_units_by_brand,
    sync_variant_inventory,
)


NEGATIVE_STATUS_MARKERS = (
    "مرجوع",
    "برگشت",
    "لغو",
    "کنسل",
    "عدمتحویل",
    "عدمارسال",
    "ناموفق",
    "ردشده",
)


def _compact_status(value: str) -> str:
    text = base._norm_text(value).lower()
    text = text.replace("آ", "ا")
    return re.sub(r"[\s\u200c_\-]+", "", text)


def _status_is_delivery(value: str) -> bool:
    """Accept known positive Digikala delivery-report statuses only."""
    status = _compact_status(value)
    if not status:
        return True
    if any(marker in status for marker in NEGATIVE_STATUS_MARKERS):
        return False
    if "دریافت" in status:
        return True
    if "ارسال/تحویل" in status:
        return True
    if "اماده" in status and "ارسال" in status and "تحویل" in status:
        return True
    return False


def parse_delivery_report(file_bytes: bytes, filename: str = ""):
    basename = os.path.basename(filename or "")
    if basename in base.BLOCKED_RETURN_FILENAMES:
        raise base.DailyOrderImportError(
            "این فایل قبلاً به‌عنوان صورت مرجوعی مشخص شده و نباید وارد فروش روزانه شود."
        )
    if not file_bytes:
        raise base.DailyOrderImportError("فایل خالی است.")
    if len(file_bytes) > base.MAX_UPLOAD_BYTES:
        raise base.DailyOrderImportError("حجم فایل بیشتر از ۱۰ مگابایت است.")

    rows = base._read_first_sheet(file_bytes)
    if not rows:
        raise base.DailyOrderImportError("فایل هیچ ردیفی ندارد.")

    header_index = None
    headers = {}
    for idx, row in enumerate(rows[:10]):
        current = {base._norm_text(value): col for col, value in enumerate(row) if base._norm_text(value)}
        if base.REQUIRED_HEADERS.issubset(current):
            header_index = idx
            headers = current
            break
    if header_index is None:
        raise base.DailyOrderImportError("ستون‌های «عنوان» و «تعداد ارسالی» در فایل پیدا نشد.")

    result = []
    ignored = 0
    raw_qty = 0
    ignored_statuses = defaultdict(int)

    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        def value(name: str) -> str:
            col = headers.get(name)
            if col is None or col >= len(row):
                return ""
            return base._norm_text(row[col])

        quantity = max(0, base._safe_int(value("تعداد ارسالی")))
        status = value("وضعیت")
        title = value("عنوان")
        if quantity <= 0:
            ignored += 1
            continue
        if not _status_is_delivery(status):
            ignored += 1
            ignored_statuses[status or "(خالی)"] += 1
            continue

        # Intentionally discard Digikala's «کد فروشنده» at parse time. Product
        # identity and s3 color are derived from title only.
        result.append(
            base.ParsedOrderRow(
                source_row=row_number,
                seller_code="",
                title=title,
                quantity=quantity,
                status=status,
            )
        )
        raw_qty += quantity

    if not result:
        detail = ""
        if ignored_statuses:
            shown = "، ".join(f"{key}: {count}" for key, count in sorted(ignored_statuses.items()))
            detail = f" وضعیت‌های دیده‌شده: {shown}."
        raise base.DailyOrderImportError(
            "هیچ ردیف قابل‌قبول با تعداد ارسالی بیشتر از صفر در فایل پیدا نشد." + detail
        )

    return result, {
        "source_rows": len(result),
        "ignored_rows": ignored,
        "raw_quantity": raw_qty,
    }


def preview_delivery_report(file_bytes: bytes, filename: str = "") -> dict:
    parsed, meta = parse_delivery_report(file_bytes, filename)
    resolved, errors = v12.resolve_rows_v12(parsed)
    grouped = v12._aggregate(resolved)
    rows = [
        {
            "brand": brand,
            "code": code,
            "size": size,
            "color": color,
            "quantity": qty,
        }
        for (brand, code, size, color), qty in sorted(
            grouped.items(), key=lambda x: (x[0][0], x[0][2], x[0][1], x[0][3])
        )
    ]
    return {
        **meta,
        "filename": os.path.basename(filename or ""),
        "rows": rows,
        "errors": errors,
        "grouped_lines": len(rows),
        "total_quantity": sum(row["quantity"] for row in rows),
    }


def merge_delivery_previews(previews: list[dict]) -> dict:
    """Merge multiple Digikala shipment files into one authoritative day preview.

    A day may be split into more than one Digikala shipment. Overlapping
    product/size/color rows are summed. The merged result, not each file
    individually, becomes the authoritative Darma/Takvin target for that day.
    """
    if not previews:
        raise base.DailyOrderImportError("حداقل یک فایل اکسل دیجی‌کالا لازم است.")

    grouped = defaultdict(int)
    errors = []
    filenames = []
    source_rows = 0
    ignored_rows = 0
    raw_quantity = 0

    for preview in previews:
        filename = os.path.basename(preview.get("filename") or "")
        filenames.append(filename)
        source_rows += int(preview.get("source_rows") or 0)
        ignored_rows += int(preview.get("ignored_rows") or 0)
        raw_quantity += int(preview.get("raw_quantity") or 0)
        for error in preview.get("errors") or []:
            errors.append(f"{filename}: {error}" if filename else str(error))
        for row in preview.get("rows") or []:
            key = (
                row.get("brand") or "",
                row.get("code") or "",
                row.get("size") or "",
                row.get("color") or "",
            )
            grouped[key] += int(row.get("quantity") or 0)

    rows = [
        {
            "brand": brand,
            "code": code,
            "size": size,
            "color": color,
            "quantity": qty,
        }
        for (brand, code, size, color), qty in sorted(
            grouped.items(), key=lambda x: (x[0][0], x[0][2], x[0][1], x[0][3])
        )
        if qty > 0
    ]
    return {
        "source_rows": source_rows,
        "ignored_rows": ignored_rows,
        "raw_quantity": raw_quantity,
        "filename": " + ".join(name for name in filenames if name),
        "filenames": filenames,
        "files_count": len(previews),
        "rows": rows,
        "errors": errors,
        "grouped_lines": len(rows),
        "total_quantity": sum(row["quantity"] for row in rows),
    }


def preview_delivery_reports(reports: list[tuple[bytes, str]]) -> dict:
    previews = [preview_delivery_report(file_bytes, filename) for file_bytes, filename in reports]
    return merge_delivery_previews(previews)


@transaction.atomic
def apply_delivery_preview(day: SaleDay, preview: dict) -> dict:
    if preview["errors"]:
        raise base.DailyOrderImportError("\n".join(preview["errors"]))

    quantity_by_key = defaultdict(int)
    variant_colors_by_key = defaultdict(lambda: defaultdict(int))
    for row in preview["rows"]:
        key = (row["brand"], row["code"], row["size"])
        quantity_by_key[key] += int(row["quantity"])
        if row.get("color"):
            variant_colors_by_key[key][row["color"]] += int(row["quantity"])

    targets = {}
    product_sizes = {}
    key_by_ps = {}
    for key, qty in quantity_by_key.items():
        brand_name, code, size_name = key
        ps = ProductSize.objects.select_related("product__brand", "size").get(
            product__brand__name=brand_name,
            product__code=code,
            size__name=size_name,
            active=True,
            product__active=True,
        )
        targets[ps.id] = qty
        product_sizes[ps.id] = ps
        key_by_ps[ps.id] = key

    # Digikala XLSX remains authoritative only for Darma/Takvin. Manual Anbaresh
    # rows on the same date must remain untouched.
    existing_lines = {
        line.product_size_id: line
        for line in SaleLine.objects.select_for_update()
        .filter(day=day, product_size__product__brand__name__in=v12.IMPORT_BRANDS)
        .select_related("product_size__product__brand", "product_size__size")
    }

    before_stock = v12._stock_totals()
    old_sold = sold_units_by_brand(list(existing_lines.values()))

    all_ps_ids = set(existing_lines) | set(targets)
    shortage_count = 0
    changed_lines = 0
    for ps_id in all_ps_ids:
        ps = product_sizes.get(ps_id)
        line = existing_lines.get(ps_id)
        if ps is None and line is not None:
            ps = line.product_size
        qty = int(targets.get(ps_id, 0))
        if line is None:
            price = int(ps.default_sale_price or 0)
            line = SaleLine.objects.create(day=day, product_size=ps, quantity=0, sale_price=price)
        else:
            price = int(line.sale_price or ps.default_sale_price or 0)

        if qty > 0 and price <= 0:
            raise base.DailyOrderImportError(
                f"قیمت فروش {ps.product.code} / {ps.size.name} صفر است؛ قبل از Import قیمت را تعیین کن."
            )

        if int(line.quantity or 0) != qty or int(line.sale_price or 0) != price:
            changed_lines += 1
        line.quantity = qty
        line.sale_price = price
        line.save(update_fields=["quantity", "sale_price"])

        if ps.product.brand.name == "دارما" and is_variable_color_product_code(ps.product.code):
            key = key_by_ps.get(ps_id, (ps.product.brand.name, ps.product.code, ps.size.name))
            result = sync_variant_inventory(line, dict(variant_colors_by_key.get(key, {})))
        else:
            result = sync_sale_inventory(line)
        shortage_count += len(result.get("shortages") or [])

        if qty > 0:
            snapshot_sale_line(line, ps, price)

        AccountEntry.objects.filter(reference=f"sale:{line.id}:digikala").delete()

    current_lines = list(
        SaleLine.objects.filter(
            day=day,
            quantity__gt=0,
            product_size__product__brand__name__in=v12.IMPORT_BRANDS,
        ).select_related("product_size__product__brand", "product_size__size")
    )
    after_stock = v12._stock_totals()
    new_sold = sold_units_by_brand(current_lines)
    try:
        assert_stock_invariant(before_stock, after_stock, old_sold, new_sold)
    except ValueError as exc:
        raise base.DailyOrderImportError(str(exc)) from exc

    preview["changed_lines"] = changed_lines
    preview["shortage_count"] = shortage_count
    preview["sale_day_id"] = day.id
    return preview


@transaction.atomic
def apply_delivery_report(day: SaleDay, file_bytes: bytes, filename: str = "") -> dict:
    return apply_delivery_preview(day, preview_delivery_report(file_bytes, filename))


@transaction.atomic
def apply_delivery_reports(day: SaleDay, reports: list[tuple[bytes, str]]) -> dict:
    return apply_delivery_preview(day, preview_delivery_reports(reports))
