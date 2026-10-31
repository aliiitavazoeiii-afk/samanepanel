from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .material_flow import COLOR_LABELS, ELASTIC, WAREHOUSE, add_warehouse_stock, q
from .material_purchase_v13 import (
    build_purchase_from_post as build_purchase_from_post_v13,
    encode_purchase_note as encode_purchase_note_v13,
    purchase_summary as purchase_summary_v13,
)
from .material_purchase_v14 import (
    apply_purchase_stock as apply_purchase_stock_v14,
    reverse_purchase_stock as reverse_purchase_stock_v14,
)
from .models import RawMaterialStock


MULTI_KIND = "elastic_multi"
FIELD_PREFIXES = ("elastic16_qty__", "elastic16_price__", "elastic25_qty__", "elastic25_price__")


def _money(value):
    try:
        return max(0, int(str(value or 0).replace("٬", "").replace(",", "").replace(" ", "")))
    except Exception:
        return 0


def _round(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def has_multi_elastic_fields(post):
    if not hasattr(post, "keys"):
        return False
    for key in post.keys():
        if any(str(key).startswith(prefix) for prefix in FIELD_PREFIXES):
            return True
    return False


def has_multi_elastic_details(post):
    if not has_multi_elastic_fields(post):
        return False
    for material_key in COLOR_LABELS:
        if q(post.get(f"elastic16_qty__{material_key}")) > 0:
            return True
        if q(post.get(f"elastic25_qty__{material_key}")) > 0:
            return True
    return False


def build_purchase_from_post(payee, post):
    if payee != "elastic" or not has_multi_elastic_fields(post):
        return build_purchase_from_post_v13(payee, post)

    note = (post.get("note") or "").strip()[:120]
    items = []
    total = Decimal("0")
    for material_key, label in COLOR_LABELS.items():
        qty16 = max(q(post.get(f"elastic16_qty__{material_key}")), Decimal("0"))
        qty25 = max(q(post.get(f"elastic25_qty__{material_key}")), Decimal("0"))
        price16 = _money(post.get(f"elastic16_price__{material_key}"))
        price25 = _money(post.get(f"elastic25_price__{material_key}"))
        if qty16 <= 0 and qty25 <= 0:
            continue
        if qty16 > 0 and price16 <= 0:
            raise ValueError(f"فی کش 16 رنگ {label} را وارد کن.")
        if qty25 > 0 and price25 <= 0:
            raise ValueError(f"فی کش 25 رنگ {label} را وارد کن.")
        total += qty16 * Decimal(price16) + qty25 * Decimal(price25)
        items.append(
            {
                "m": material_key,
                "t": label,
                "q16": str(qty16),
                "p16": price16,
                "q25": str(qty25),
                "p25": price25,
            }
        )

    if not items:
        raise ValueError("حداقل یک رنگ کش با وزن 16 یا 25 وارد کن.")
    data = {"k": MULTI_KIND, "items": items, "n": note}
    return _round(total), data


def invoice_value(data):
    if not data:
        return 0
    if data.get("k") != MULTI_KIND:
        return None
    total = Decimal("0")
    for item in data.get("items") or []:
        total += q(item.get("q16")) * Decimal(int(item.get("p16") or 0))
        total += q(item.get("q25")) * Decimal(int(item.get("p25") or 0))
    return _round(total)


def purchase_signature(data):
    if not data or data.get("k") != MULTI_KIND:
        return None
    rows = []
    for item in data.get("items") or []:
        rows.append(
            (
                str(item.get("m") or ""),
                q(item.get("q16")),
                int(item.get("p16") or 0),
                q(item.get("q25")),
                int(item.get("p25") or 0),
            )
        )
    return (MULTI_KIND, tuple(sorted(rows)))


def encode_purchase_note(data):
    if not data or data.get("k") != MULTI_KIND:
        return encode_purchase_note_v13(data)
    # The authoritative full multi-color payload is stored in the V14 purchase
    # MoneyMovement ledger (TextField). BusinessPayment.note is deliberately a
    # compact compatibility marker because that field is limited to 250 chars.
    colors = ",".join(str(item.get("m") or "") for item in (data.get("items") or []))[:120]
    note = str(data.get("n") or "")[:80]
    return f"[mp60]elastic_multi:{colors}|{note}"[:250]


def purchase_summary(data):
    if not data:
        return ""
    if data.get("k") != MULTI_KIND:
        return purchase_summary_v13(data)
    parts = []
    for item in data.get("items") or []:
        label = item.get("t") or COLOR_LABELS.get(item.get("m"), item.get("m", ""))
        variants = []
        if q(item.get("q16")) > 0:
            variants.append(f"16: {item.get('q16')} کیلو × {int(item.get('p16') or 0):,}")
        if q(item.get("q25")) > 0:
            variants.append(f"25: {item.get('q25')} کیلو × {int(item.get('p25') or 0):,}")
        if variants:
            parts.append(f"{label} ({' | '.join(variants)})")
    return "کش چندرنگ · " + " · ".join(parts)


def apply_purchase_stock(payment, data):
    if not data or data.get("k") != MULTI_KIND:
        return apply_purchase_stock_v14(payment, data)
    rows = []
    stock_note = f"خرید از پرداخت #{payment.id}"
    for item in data.get("items") or []:
        material_key = str(item.get("m") or "")
        if material_key not in COLOR_LABELS:
            raise ValueError("رنگ کش در صورت خرید معتبر نیست.")
        title = item.get("t") or COLOR_LABELS[material_key]
        for variant in ("16", "25"):
            qty = q(item.get(f"q{variant}"))
            price = int(item.get(f"p{variant}") or 0)
            if qty <= 0:
                continue
            if price <= 0:
                raise ValueError(f"فی کش {variant} رنگ {title} معتبر نیست.")
            rows.append(
                add_warehouse_stock(
                    kind=ELASTIC,
                    material_key=material_key,
                    title=title,
                    quantity=qty,
                    unit_price=price,
                    variant=variant,
                    unit="کیلو",
                    note=stock_note,
                    location=WAREHOUSE,
                )
            )
    return rows


def _reverse_one_elastic(payment, item, variant):
    qty = q(item.get(f"q{variant}"))
    price = int(item.get(f"p{variant}") or 0)
    if qty <= 0:
        return
    material_key = str(item.get("m") or "")
    rows = list(
        RawMaterialStock.objects.select_for_update().filter(
            active=True,
            kind=ELASTIC,
            location=WAREHOUSE,
            material_key=material_key,
            variant=variant,
        ).order_by("id")
    )
    total_qty = sum((max(q(row.quantity), Decimal("0")) for row in rows), Decimal("0"))
    total_value = sum(
        (max(q(row.quantity), Decimal("0")) * Decimal(int(row.unit_price or 0)) for row in rows),
        Decimal("0"),
    )
    label = item.get("t") or COLOR_LABELS.get(material_key, material_key)
    if total_qty < qty:
        raise ValueError(
            f"حذف خرید کش {variant} رنگ {label} ممکن نیست؛ موجودی انبار {total_qty} کیلو و مقدار خرید {qty} کیلو است."
        )
    purchase_value = qty * Decimal(price)
    remaining_qty = total_qty - qty
    remaining_value = total_value - purchase_value
    if remaining_value < 0:
        # material_flow stores weighted elastic price as an integer toman/kg,
        # so the aggregate pool can lose less than one toman per kg to rounding.
        # Allow only that mathematically bounded rounding deficit; anything larger
        # still aborts as a real value/inventory mismatch.
        rounding_tolerance = total_qty + Decimal("1")
        if abs(remaining_value) <= rounding_tolerance:
            remaining_value = Decimal("0")
        else:
            raise ValueError(
                f"ارزش موجودی کش {variant} رنگ {label} برای Reverse این خرید کافی نیست؛ عملیات متوقف شد."
            )
    for row in rows:
        row.delete()
    if remaining_qty > 0:
        avg_price = _round(remaining_value / remaining_qty)
        RawMaterialStock.objects.create(
            kind=ELASTIC,
            location=WAREHOUSE,
            material_key=material_key,
            variant=variant,
            title=label,
            quantity=remaining_qty,
            unit_price=max(0, avg_price),
            unit="کیلو",
            note=f"مانده پس از حذف خرید #{payment.id}",
            active=True,
        )


@transaction.atomic
def reverse_purchase_stock(payment, data):
    if not data or data.get("k") != MULTI_KIND:
        return reverse_purchase_stock_v14(payment, data)
    for item in data.get("items") or []:
        _reverse_one_elastic(payment, item, "16")
        _reverse_one_elastic(payment, item, "25")
