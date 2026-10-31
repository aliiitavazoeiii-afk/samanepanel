import json
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .material_flow import ELASTIC, FABRIC, WAREHOUSE, add_warehouse_stock, q
from .material_purchase_v13 import build_purchase_from_post, parse_purchase_note, purchase_summary
from .models import BusinessPayment, MoneyMovement, RawMaterialStock

LEDGER_PREFIX = "material-purchase:"


def _round(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ledger_title(payment_id):
    return f"{LEDGER_PREFIX}{int(payment_id)}"


def encode_ledger_data(data):
    payload = dict(data or {})
    payload["v"] = 14
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode_ledger_data(text):
    try:
        value = json.loads(str(text or ""))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def ledger_for_payment(payment):
    row = MoneyMovement.objects.filter(
        kind=MoneyMovement.PURCHASE,
        title=ledger_title(payment.id),
    ).order_by("-id").first()
    return row


def purchase_data_for_payment(payment):
    ledger = ledger_for_payment(payment)
    if ledger:
        data = decode_ledger_data(ledger.note)
        if data:
            return data
    # v13 compatibility only; v14 never depends on this fallback for new purchases.
    return parse_purchase_note(payment.note)


def create_purchase_ledger(payment, data):
    MoneyMovement.objects.filter(
        kind=MoneyMovement.PURCHASE,
        title=ledger_title(payment.id),
    ).delete()
    return MoneyMovement.objects.create(
        date=payment.date,
        kind=MoneyMovement.PURCHASE,
        amount=int(payment.amount or 0),
        title=ledger_title(payment.id),
        affects_capital=False,
        note=encode_ledger_data(data),
    )


def apply_purchase_stock(payment, data):
    kind = data.get("k")
    material_key = data.get("m") or ""
    title = data.get("t") or material_key
    stock_note = f"خرید از پرداخت #{payment.id}"

    if kind == "fabric":
        return [
            add_warehouse_stock(
                kind=FABRIC,
                material_key=material_key,
                title=title,
                quantity=data.get("q"),
                unit_price=int(data.get("p") or 0),
                unit="کیلو",
                note=stock_note,
                location=WAREHOUSE,
            )
        ]

    if kind == "elastic":
        rows = []
        for variant in ("16", "25"):
            qty = q(data.get(f"q{variant}"))
            price = int(data.get(f"p{variant}") or 0)
            if qty <= 0:
                continue
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

    raise ValueError("نوع خرید مواد اولیه معتبر نیست.")


def _reverse_fabric(payment, data):
    qty = q(data.get("q"))
    price = int(data.get("p") or 0)
    material_key = data.get("m") or ""
    title = data.get("t") or ""
    expected_note = f"خرید از پرداخت #{payment.id}"

    rows = list(
        RawMaterialStock.objects.select_for_update().filter(
            active=True,
            kind=FABRIC,
            location=WAREHOUSE,
            material_key=material_key,
            title=title,
        ).order_by("id")
    )
    rows.sort(key=lambda row: (0 if row.note == expected_note else 1, 0 if int(row.unit_price or 0) == price else 1, row.id))
    remaining = qty
    for row in rows:
        if remaining <= 0:
            break
        # A v14 fabric purchase is its own row; only consume rows at the same purchase price.
        if int(row.unit_price or 0) != price:
            continue
        available = max(q(row.quantity), Decimal("0"))
        take = min(available, remaining)
        if take <= 0:
            continue
        row.quantity = available - take
        row.save(update_fields=["quantity", "updated_at"])
        remaining -= take
    if remaining > 0:
        raise ValueError(
            f"حذف خرید پارچه ممکن نیست؛ {remaining} کیلو از همان خرید دیگر در انبار موجود نیست. "
            "اگر به خیاط منتقل شده، ابتدا آن را به انبار برگردان."
        )


def _reverse_elastic_variant(payment, data, variant):
    qty = q(data.get(f"q{variant}"))
    price = int(data.get(f"p{variant}") or 0)
    if qty <= 0:
        return
    material_key = data.get("m") or ""
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
    if total_qty < qty:
        raise ValueError(
            f"حذف خرید کش {variant} ممکن نیست؛ موجودی انبار {total_qty} کیلو و مقدار خرید {qty} کیلو است."
        )
    purchase_value = qty * Decimal(price)
    remaining_qty = total_qty - qty
    remaining_value = total_value - purchase_value
    if remaining_value < 0:
        raise ValueError(
            f"ارزش موجودی کش {variant} برای Reverse این خرید کافی نیست؛ حذف متوقف شد تا سرمایه خراب نشود."
        )

    # Warehouse elastic is an aggregate pool. Rebuild that pool after removing the exact
    # purchase quantity and exact purchase cost basis.
    if not rows and remaining_qty > 0:
        raise ValueError("ردیف موجودی کش پیدا نشد.")
    for row in rows:
        row.delete()
    if remaining_qty > 0:
        avg_price = _round(remaining_value / remaining_qty)
        RawMaterialStock.objects.create(
            kind=ELASTIC,
            location=WAREHOUSE,
            material_key=material_key,
            variant=variant,
            title=data.get("t") or material_key,
            quantity=remaining_qty,
            unit_price=max(0, avg_price),
            unit="کیلو",
            note=f"مانده پس از حذف خرید #{payment.id}",
            active=True,
        )


def reverse_purchase_stock(payment, data):
    kind = data.get("k")
    if kind == "fabric":
        _reverse_fabric(payment, data)
        return
    if kind == "elastic":
        _reverse_elastic_variant(payment, data, "16")
        _reverse_elastic_variant(payment, data, "25")
        return
    raise ValueError("نوع خرید مواد اولیه برای حذف معتبر نیست.")


@transaction.atomic
def backfill_v13_ledger(payment):
    if ledger_for_payment(payment):
        return ledger_for_payment(payment)
    data = parse_purchase_note(payment.note)
    if not data:
        return None
    return create_purchase_ledger(payment, data)
