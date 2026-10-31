from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .dateutils import format_jalali
from .dia_gallery_v45 import dia_gallery_day_metrics
from .finance import sale_line_metrics
from .models import SaleDay, SaleLine
from .telegram_inventory_alerts_v20 import notify_after_daily_report


PRIMARY_REPORT_BRANDS = ("تکوین", "دارما")
FILTER_SIZES = {
    "تکوین": ("M", "L", "XL", "XXL"),
    "دارما": ("M", "L", "XL", "XXL", "3XL", "4XL"),
}
MATRIX_SIZE_ORDER = ("M", "L", "XL", "XXL", "3XL", "4XL")
MATRIX_COLOR_ORDER = (
    "مشکی",
    "سفید",
    "سرمه‌ای",
    "صورتی",
    "کرم",
    "طوسی",
    "راه راه",
    "راه راه طوسی",
    "برعکس مشکی",
    "برعکس سفید",
    "برعکس سرمه‌ای",
)


def _normalize_matrix_color(value):
    text = str(value or "").strip().replace("ي", "ی").replace("ك", "ک")
    text = text.replace("توسی", "طوسی")
    for token in (" ", "‌", "-", "_", "/"):
        text = text.replace(token, "")
    return text


def _matrix_color_rank(value):
    normalized = _normalize_matrix_color(value)
    aliases = {
        _normalize_matrix_color("مشکی"): 0,
        _normalize_matrix_color("سفید"): 1,
        _normalize_matrix_color("سرمه‌ای"): 2,
        _normalize_matrix_color("صورتی"): 3,
        _normalize_matrix_color("کرم"): 4,
        _normalize_matrix_color("طوسی"): 5,
        _normalize_matrix_color("راه راه"): 6,
        _normalize_matrix_color("راه راه طوسی"): 7,
        _normalize_matrix_color("طوسی راه راه"): 7,
        _normalize_matrix_color("برعکس مشکی"): 8,
        _normalize_matrix_color("مشکی برعکس"): 8,
        _normalize_matrix_color("برعکس سفید"): 9,
        _normalize_matrix_color("سفید برعکس"): 9,
        _normalize_matrix_color("برعکس سرمه‌ای"): 10,
        _normalize_matrix_color("سرمه‌ای برعکس"): 10,
    }
    return aliases.get(normalized, len(MATRIX_COLOR_ORDER))


def _line_color_breakdown(line):
    """Return the physical colors represented by this sale line.

    SaleAllocation is authoritative because it records what was actually deducted
    from stock, including resolved replacement colors. For older lines that have
    no allocations, fall back to the configured ProductComposition and mark that
    source explicitly so the UI never presents an inferred composition as exact.
    """
    grouped = {}
    replacement_qty = defaultdict(int)

    allocations = list(line.allocations.all())
    if allocations:
        for alloc in allocations:
            name = alloc.color.name
            if name not in grouped:
                grouped[name] = 0
            qty = int(alloc.qty or 0)
            grouped[name] += qty
            if alloc.is_replacement:
                replacement_qty[name] += qty
        source = "allocation"
    else:
        for comp in line.product_size.product.composition.all():
            name = comp.color.name
            if name not in grouped:
                grouped[name] = 0
            grouped[name] += int(line.quantity or 0) * int(comp.qty or 0)
        source = "composition" if grouped else "unknown"

    colors = []
    for name, qty in grouped.items():
        colors.append({
            "name": name,
            "qty": int(qty),
            "replacement_qty": int(replacement_qty.get(name, 0)),
        })
    return colors, source


def _build_filter_brands(detail_rows):
    stats = {
        brand: {
            "name": brand,
            "packs": 0,
            "shorts": 0,
            "line_count": 0,
            "sizes": {size: {"name": size, "packs": 0, "shorts": 0, "line_count": 0}
                      for size in FILTER_SIZES[brand]},
        }
        for brand in PRIMARY_REPORT_BRANDS
    }

    for row in detail_rows:
        brand = row["brand_name"]
        if brand not in stats:
            continue
        values = stats[brand]
        values["packs"] += int(row["packs"])
        values["shorts"] += int(row["shorts"])
        values["line_count"] += 1
        size = row["size_name"]
        if size not in values["sizes"]:
            values["sizes"][size] = {"name": size, "packs": 0, "shorts": 0, "line_count": 0}
        values["sizes"][size]["packs"] += int(row["packs"])
        values["sizes"][size]["shorts"] += int(row["shorts"])
        values["sizes"][size]["line_count"] += 1

    result = []
    for brand in PRIMARY_REPORT_BRANDS:
        values = stats[brand]
        values["sizes"] = list(values["sizes"].values())
        result.append(values)
    return result


def _build_color_size_matrix(detail_rows):
    """Build Darma-only daily matrix: physical color rows × size columns."""
    darma_rows = [
        row for row in detail_rows
        if str(row.get("brand_name") or "").strip() == "دارما"
    ]

    present_sizes = {str(row.get("size_name") or "").strip() for row in darma_rows}
    present_sizes.discard("")
    ordered_sizes = [name for name in MATRIX_SIZE_ORDER if name in present_sizes]
    ordered_sizes.extend(sorted(present_sizes - set(ordered_sizes)))

    grouped = {}
    size_totals = defaultdict(int)
    expected_shorts = 0
    physical_color_total = 0
    has_inferred = False
    has_replacement = False

    for row in darma_rows:
        size_name = str(row.get("size_name") or "")
        expected_shorts += int(row.get("shorts") or 0)
        color_source = row.get("color_source")
        if color_source != "allocation":
            has_inferred = True

        colors = list(row.get("colors") or [])
        if not colors and int(row.get("shorts") or 0) > 0:
            colors = [{
                "name": "رنگ نامشخص",
                "qty": int(row.get("shorts") or 0),
                "replacement_qty": 0,
            }]

        for color in colors:
            qty = int(color.get("qty") or 0)
            if qty <= 0:
                continue
            color_name = str(color.get("name") or "رنگ نامشخص")
            replacement_qty = int(color.get("replacement_qty") or 0)
            if color_name not in grouped:
                grouped[color_name] = {
                    "color_name": color_name,
                    "sizes": defaultdict(int),
                    "total": 0,
                    "replacement_qty": 0,
                }
            grouped[color_name]["sizes"][size_name] += qty
            grouped[color_name]["total"] += qty
            grouped[color_name]["replacement_qty"] += replacement_qty
            size_totals[size_name] += qty
            physical_color_total += qty
            if replacement_qty:
                has_replacement = True

    rows = sorted(
        grouped.values(),
        key=lambda item: (_matrix_color_rank(item["color_name"]), item["color_name"]),
    )
    for item in rows:
        item["size_values"] = [
            {"name": size_name, "qty": int(item["sizes"].get(size_name, 0))}
            for size_name in ordered_sizes
        ]
        item.pop("sizes", None)

    return {
        "sizes": ordered_sizes,
        "rows": rows,
        "size_totals": [
            {"name": size_name, "qty": int(size_totals.get(size_name, 0))}
            for size_name in ordered_sizes
        ],
        "total": int(physical_color_total),
        "expected_shorts": int(expected_shorts),
        "has_mismatch": int(physical_color_total) != int(expected_shorts),
        "has_inferred": has_inferred,
        "has_replacement": has_replacement,
    }


@login_required
def daily_report(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)
    lines = list(
        SaleLine.objects.filter(day=day, quantity__gt=0)
        .select_related("product_size__product__brand", "product_size__size")
        .prefetch_related(
            "allocations__color",
            "product_size__product__composition__color",
        )
        .order_by(
            "product_size__product__brand__name",
            "product_size__size__sort_order",
            "product_size__product__code",
        )
    )

    by_brand = defaultdict(lambda: {
        "gross": 0, "digikala_fee": 0, "cogs": 0, "profit": 0,
        "shorts": 0, "packs": 0, "margin": 0,
    })
    total = {"gross": 0, "digikala_fee": 0, "cogs": 0, "profit": 0, "shorts": 0, "packs": 0, "margin": 0}
    detail_rows = []

    for line in lines:
        metrics = sale_line_metrics(line)
        brand_name = line.product_size.product.brand.name
        size_name = line.product_size.size.name
        colors, color_source = _line_color_breakdown(line)
        color_total = sum(int(item["qty"]) for item in colors)

        for key in ["gross", "digikala_fee", "cogs", "profit", "shorts", "packs"]:
            by_brand[brand_name][key] += metrics[key]
            total[key] += metrics[key]

        detail_rows.append({
            "line": line,
            "brand_name": brand_name,
            "size_name": size_name,
            "code": line.product_size.product.code,
            "colors": colors,
            "color_source": color_source,
            "color_total": color_total,
            "color_mismatch": bool(color_source == "allocation" and color_total != int(metrics["shorts"])),
            **metrics,
        })

    dia_gallery = dia_gallery_day_metrics(day)
    if int(dia_gallery["total"].get("shorts") or 0) > 0:
        dia_values = by_brand["Dia Gallery"]
        for key in ["gross", "digikala_fee", "cogs", "profit", "shorts", "packs"]:
            value = int(dia_gallery["total"].get(key) or 0)
            dia_values[key] += value
            total[key] += value

    for values in by_brand.values():
        values["margin"] = (values["profit"] / values["gross"] * 100) if values["gross"] else 0
    total["margin"] = (total["profit"] / total["gross"] * 100) if total["gross"] else 0

    preferred = ["تکوین", "دارما", "انبارش", "Dia Gallery"]
    ordered_brands = []
    for brand_name in preferred:
        if brand_name in by_brand:
            ordered_brands.append((brand_name, by_brand[brand_name]))
    for brand_name, values in by_brand.items():
        if brand_name not in preferred:
            ordered_brands.append((brand_name, values))

    filter_brands = _build_filter_brands(detail_rows)
    primary_detail_rows = [row for row in detail_rows if row["brand_name"] in PRIMARY_REPORT_BRANDS]
    other_detail_rows = [row for row in detail_rows if row["brand_name"] not in PRIMARY_REPORT_BRANDS]
    color_size_matrix = _build_color_size_matrix(detail_rows)

    default_brand = "دارما"
    if not any(row["brand_name"] == "دارما" for row in primary_detail_rows):
        default_brand = "تکوین"

    if lines or int(dia_gallery["total"].get("shorts") or 0) > 0:
        try:
            notify_after_daily_report(day)
        except Exception:
            pass

    return render(request, "core/daily_report_v45.html", {
        "day": day,
        "jalali_date": format_jalali(day.date),
        "detail_rows": detail_rows,
        "primary_detail_rows": primary_detail_rows,
        "other_detail_rows": other_detail_rows,
        "filter_brands": filter_brands,
        "default_brand": default_brand,
        "by_brand": ordered_brands,
        "total": total,
        "dia_gallery": dia_gallery,
        "color_size_matrix": color_size_matrix,
    })
