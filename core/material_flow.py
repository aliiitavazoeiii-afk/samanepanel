from decimal import Decimal
import re

from django.db import transaction

from .models import MaterialReportConsumption, RawMaterialStock


FABRIC = RawMaterialStock.FABRIC
ELASTIC = RawMaterialStock.ELASTIC
WAREHOUSE = RawMaterialStock.WAREHOUSE
TAILOR = RawMaterialStock.TAILOR
DEPOT = RawMaterialStock.DEPOT


COLOR_LABELS = {
    "black": "مشکی",
    "white": "سفید",
    "navy": "سرمه‌ای",
    "pink": "صورتی",
    "cream": "کرم",
    "red": "قرمز",
    "yellow": "زرد",
    "gray": "طوسی",
    "stripe": "راه راه",
}

OUTPUT_SIZE_KEYS = ["m", "l", "xl", "xxl", "3xl", "4xl"]


def q(value):
    try:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value).replace("٬", "").replace(" ", "").replace(",", "."))
    except Exception:
        return Decimal("0")


def _weighted_price(old_qty, old_price, add_qty, add_price):
    total_qty = old_qty + add_qty
    if total_qty <= 0:
        return int(add_price or old_price or 0)
    total_value = old_qty * Decimal(int(old_price or 0)) + add_qty * Decimal(int(add_price or 0))
    return int(total_value / total_qty)


def _get_or_create_aggregate(kind, location, material_key, title, variant="", unit="کیلو", unit_price=0):
    row = RawMaterialStock.objects.filter(
        active=True, kind=kind, location=location, material_key=material_key,
        variant=variant, title=title,
    ).order_by("id").first()
    if row:
        return row
    return RawMaterialStock.objects.create(
        kind=kind, location=location, material_key=material_key, variant=variant,
        title=title, quantity=Decimal("0"), unit_price=int(unit_price or 0), unit=unit or "کیلو",
    )


@transaction.atomic
def add_warehouse_stock(*, kind, material_key, title, quantity, unit_price, variant="", unit="کیلو", note="", location=WAREHOUSE):
    quantity = q(quantity)
    if quantity <= 0:
        raise ValueError("مقدار باید بیشتر از صفر باشد.")
    unit_price = int(unit_price or 0)
    if location not in {WAREHOUSE, DEPOT}:
        raise ValueError("محل ورود مستقیم معتبر نیست.")
    if kind == FABRIC:
        return RawMaterialStock.objects.create(
            kind=kind, location=location, material_key=material_key, variant="",
            title=title, quantity=quantity, unit_price=unit_price, unit=unit or "کیلو", note=note,
        )
    if location != WAREHOUSE:
        raise ValueError("کش دپو در این بخش تعریف نشده است.")
    row = _get_or_create_aggregate(kind, WAREHOUSE, material_key, title, variant, unit, unit_price)
    row.unit_price = _weighted_price(q(row.quantity), row.unit_price, quantity, unit_price)
    row.quantity = q(row.quantity) + quantity
    if note:
        row.note = note
    row.save()
    return row


def _preferred_source_id(note):
    match = re.search(r"ردیف\s+(\d+)", note or "")
    return int(match.group(1)) if match else None


def _fabric_sources(material_key, title, preferred_id=None):
    qs = RawMaterialStock.objects.select_for_update().filter(
        active=True, kind=FABRIC, location=WAREHOUSE,
        material_key=material_key, title=title,
    ).order_by("id")
    rows = list(qs)
    if preferred_id:
        rows.sort(key=lambda row: 0 if row.id == preferred_id else 1)
    return rows


def _take_fabric_from_warehouse(target, amount):
    amount = q(amount)
    if amount <= 0:
        return
    rows = _fabric_sources(target.material_key, target.title, _preferred_source_id(target.note))
    available = sum((max(q(row.quantity), Decimal("0")) for row in rows), Decimal("0"))
    if available < amount:
        raise ValueError(f"موجودی پارچه {target.title} در انبار کافی نیست؛ موجود {available} کیلو.")
    remaining = amount
    for row in rows:
        take = min(max(q(row.quantity), Decimal("0")), remaining)
        if take <= 0:
            continue
        row.quantity = q(row.quantity) - take
        row.save(update_fields=["quantity", "updated_at"])
        remaining -= take
        if remaining <= 0:
            break


def _return_fabric_to_warehouse(source, amount):
    amount = q(amount)
    if amount <= 0:
        return
    preferred = _preferred_source_id(source.note)
    target = None
    if preferred:
        target = RawMaterialStock.objects.select_for_update().filter(
            id=preferred, active=True, kind=FABRIC, location=WAREHOUSE
        ).first()
    if not target:
        target = RawMaterialStock.objects.select_for_update().filter(
            active=True, kind=FABRIC, location=WAREHOUSE,
            material_key=source.material_key, title=source.title,
            unit_price=source.unit_price,
        ).order_by("id").first()
    if not target:
        target = RawMaterialStock.objects.create(
            kind=FABRIC, location=WAREHOUSE, material_key=source.material_key, variant="",
            title=source.title, quantity=Decimal("0"), unit_price=source.unit_price,
            unit=source.unit, note="برگشت از اصلاح موجودی خیاط",
        )
    target.quantity = q(target.quantity) + amount
    target.save(update_fields=["quantity", "updated_at"])


@transaction.atomic
def transfer_fabric_to_tailor(source_id, quantity):
    """Move fabric to the tailor without creating duplicate rows for the same source lot.

    Warehouse fabric stays lot-based for purchase/reversal traceability. At the tailor,
    repeated transfers from the exact same warehouse row are accumulated into the
    existing row. Different source lots may still remain separate internally so their
    purchase provenance is not destroyed; the report UI groups them by material_key.
    """
    quantity = q(quantity)
    source = RawMaterialStock.objects.select_for_update().get(
        id=source_id, kind=FABRIC, location=WAREHOUSE, active=True
    )
    if quantity <= 0:
        raise ValueError("وزن انتقال باید بیشتر از صفر باشد.")
    if q(source.quantity) < quantity:
        raise ValueError("وزن انتقال از موجودی انبار بیشتر است.")

    source.quantity = q(source.quantity) - quantity
    source.save(update_fields=["quantity", "updated_at"])

    source_note = f"انتقال از انبار / ردیف {source.id}"
    target = (
        RawMaterialStock.objects.select_for_update()
        .filter(
            active=True,
            kind=FABRIC,
            location=TAILOR,
            material_key=source.material_key,
            variant="",
            title=source.title,
            unit_price=source.unit_price,
            note=source_note,
        )
        .order_by("id")
        .first()
    )
    if target:
        target.quantity = q(target.quantity) + quantity
        target.unit = source.unit
        target.save(update_fields=["quantity", "unit", "updated_at"])
        return target

    return RawMaterialStock.objects.create(
        kind=FABRIC, location=TAILOR, material_key=source.material_key, variant="",
        title=source.title, quantity=quantity, unit_price=source.unit_price, unit=source.unit,
        note=source_note,
    )


@transaction.atomic
def update_fabric_stock(row_id, *, quantity, unit_price=None, note=None):
    row = RawMaterialStock.objects.select_for_update().get(id=row_id, kind=FABRIC, active=True)
    new_qty = q(quantity)
    if new_qty < 0:
        raise ValueError("وزن نمی‌تواند منفی باشد.")
    old_qty = q(row.quantity)
    if row.location == TAILOR:
        delta = new_qty - old_qty
        if delta > 0:
            _take_fabric_from_warehouse(row, delta)
        elif delta < 0:
            _return_fabric_to_warehouse(row, -delta)
    row.quantity = new_qty
    if unit_price is not None:
        row.unit_price = max(0, int(unit_price or 0))
    if note is not None:
        row.note = note
    row.save()
    return row


@transaction.atomic
def delete_fabric_stock(row_id):
    row = RawMaterialStock.objects.select_for_update().get(id=row_id, kind=FABRIC, active=True)
    if row.location == TAILOR and q(row.quantity) > 0:
        _return_fabric_to_warehouse(row, row.quantity)
    row.delete()


def _elastic_rows(location, material_key, variant):
    return list(RawMaterialStock.objects.select_for_update().filter(
        active=True, kind=ELASTIC, location=location,
        material_key=material_key, variant=variant,
    ).order_by("id"))


def _elastic_total(location, material_key, variant):
    return sum((q(row.quantity) for row in _elastic_rows(location, material_key, variant)), Decimal("0"))


def _take_elastic_from_warehouse(material_key, variant, amount):
    amount = q(amount)
    rows = _elastic_rows(WAREHOUSE, material_key, variant)
    available = sum((max(q(row.quantity), Decimal("0")) for row in rows), Decimal("0"))
    if available < amount:
        raise ValueError(f"موجودی کش {variant} این رنگ در انبار کافی نیست؛ موجود {available} کیلو.")
    remaining = amount
    for row in rows:
        take = min(max(q(row.quantity), Decimal("0")), remaining)
        if take <= 0:
            continue
        row.quantity = q(row.quantity) - take
        row.save(update_fields=["quantity", "updated_at"])
        remaining -= take
        if remaining <= 0:
            break


def _return_elastic_to_warehouse(material_key, title, variant, amount, unit_price=0):
    amount = q(amount)
    if amount <= 0:
        return
    target = _get_or_create_aggregate(ELASTIC, WAREHOUSE, material_key, title, variant, "کیلو", unit_price)
    target.unit_price = _weighted_price(q(target.quantity), target.unit_price, amount, unit_price)
    target.quantity = q(target.quantity) + amount
    target.save()


@transaction.atomic
def transfer_elastic_to_tailor(material_key, title, qty16=0, qty25=0):
    requested = [("16", q(qty16)), ("25", q(qty25))]
    if not any(amount > 0 for _, amount in requested):
        raise ValueError("حداقل یکی از مقادیر کش 16 یا 25 را وارد کن.")
    for variant, quantity in requested:
        if quantity > 0:
            _take_elastic_from_warehouse(material_key, variant, quantity)
    moved = []
    for variant, quantity in requested:
        if quantity <= 0:
            continue
        source_price = RawMaterialStock.objects.filter(
            active=True, kind=ELASTIC, location=WAREHOUSE,
            material_key=material_key, variant=variant,
        ).values_list("unit_price", flat=True).first() or 0
        target = _get_or_create_aggregate(ELASTIC, TAILOR, material_key, title, variant, "کیلو", source_price)
        target.unit_price = _weighted_price(q(target.quantity), target.unit_price, quantity, source_price)
        target.quantity = q(target.quantity) + quantity
        target.save()
        moved.append(target)
    return moved


@transaction.atomic
def update_elastic_group(*, location, material_key, title, qty16, price16, qty25, price25):
    if location not in {WAREHOUSE, TAILOR}:
        raise ValueError("محل کش معتبر نیست.")
    requested = {
        "16": (q(qty16), max(0, int(price16 or 0))),
        "25": (q(qty25), max(0, int(price25 or 0))),
    }
    for variant, (new_qty, _) in requested.items():
        if new_qty < 0:
            raise ValueError("مقدار کش نمی‌تواند منفی باشد.")
        old_qty = _elastic_total(location, material_key, variant)
        if location == TAILOR:
            delta = new_qty - old_qty
            if delta > 0:
                _take_elastic_from_warehouse(material_key, variant, delta)
            elif delta < 0:
                old_price = RawMaterialStock.objects.filter(
                    active=True, kind=ELASTIC, location=TAILOR,
                    material_key=material_key, variant=variant,
                ).values_list("unit_price", flat=True).first() or 0
                _return_elastic_to_warehouse(material_key, title, variant, -delta, old_price)

    for variant, (new_qty, new_price) in requested.items():
        rows = _elastic_rows(location, material_key, variant)
        if new_qty == 0:
            for row in rows:
                row.delete()
            continue
        target = rows[0] if rows else RawMaterialStock.objects.create(
            kind=ELASTIC, location=location, material_key=material_key, variant=variant,
            title=title, quantity=Decimal("0"), unit_price=new_price, unit="کیلو",
        )
        target.title = title
        target.quantity = new_qty
        target.unit_price = new_price
        target.save()
        for extra in rows[1:]:
            extra.delete()


@transaction.atomic
def delete_elastic_group(*, location, material_key, title):
    rows16 = _elastic_rows(location, material_key, "16")
    rows25 = _elastic_rows(location, material_key, "25")
    p16 = rows16[0].unit_price if rows16 else 0
    p25 = rows25[0].unit_price if rows25 else 0
    update_elastic_group(
        location=location, material_key=material_key, title=title,
        qty16=0, price16=p16, qty25=0, price25=p25,
    )


def _consume_rows(kind, material_key, variant, delta):
    """Positive delta consumes tailor stock; negative delta reverses prior consumption."""
    delta = q(delta)
    if delta == 0:
        return
    rows = list(RawMaterialStock.objects.select_for_update().filter(
        active=True, kind=kind, location=TAILOR,
        material_key=material_key, variant=variant,
    ).order_by("id"))
    title = COLOR_LABELS.get(material_key, rows[0].title if rows else material_key or "نامشخص")

    if delta > 0:
        available_total = sum((max(q(row.quantity), Decimal("0")) for row in rows), Decimal("0"))
        if available_total < delta:
            name = f"{title} / کش {variant}" if kind == ELASTIC else f"پارچه {title}"
            raise ValueError(f"موجودی {name} نزد خیاط کافی نیست؛ موجود {available_total} کیلو، مصرف ثبت‌شده {delta} کیلو.")
        remaining = delta
        for row in rows:
            available = max(q(row.quantity), Decimal("0"))
            if available <= 0:
                continue
            take = min(available, remaining)
            row.quantity = q(row.quantity) - take
            row.save(update_fields=["quantity", "updated_at"])
            remaining -= take
            if remaining <= 0:
                break
    else:
        amount = -delta
        target = rows[0] if rows else _get_or_create_aggregate(kind, TAILOR, material_key, title, variant, "کیلو", 0)
        target.quantity = q(target.quantity) + amount
        target.save(update_fields=["quantity", "updated_at"])


def _color_has_final_receipt(output_data, key):
    values = (output_data or {}).get(key, {}) or {}
    return any(q(values.get(size_key)) > 0 for size_key in OUTPUT_SIZE_KEYS)


def desired_consumption(input_data, output_data):
    """Consume only a color whose finished-goods row has actually been received."""
    desired = {}
    input_data = input_data or {}
    for key in COLOR_LABELS:
        if not _color_has_final_receipt(output_data, key):
            continue
        values = input_data.get(key, {}) or {}
        fabric = max(q(values.get("weight")), Decimal("0"))
        if fabric:
            desired[(FABRIC, key, "")] = fabric

        delivered16 = q(values.get("elastic16"))
        delivered25 = q(values.get("elastic25"))
        remain16_raw = values.get("remain16")
        remain25_raw = values.get("remain25")
        used16 = delivered16 - q(remain16_raw) if remain16_raw not in (None, "") else delivered16
        used25 = delivered25 - q(remain25_raw) if remain25_raw not in (None, "") else delivered25
        used16 = max(used16, Decimal("0"))
        used25 = max(used25, Decimal("0"))
        if used16:
            desired[(ELASTIC, key, "16")] = used16
        if used25:
            desired[(ELASTIC, key, "25")] = used25
    return desired


@transaction.atomic
def sync_report_consumption(block):
    desired = desired_consumption(block.input_data, block.output_data)
    existing = {
        (row.kind, row.material_key, row.variant): row
        for row in MaterialReportConsumption.objects.select_for_update().filter(block=block)
    }
    for key in set(desired) | set(existing):
        old = q(existing[key].quantity) if key in existing else Decimal("0")
        new = q(desired.get(key, 0))
        _consume_rows(key[0], key[1], key[2], new - old)
        if new == 0:
            if key in existing:
                existing[key].delete()
        elif key in existing:
            existing[key].quantity = new
            existing[key].save(update_fields=["quantity"])
        else:
            MaterialReportConsumption.objects.create(
                block=block, kind=key[0], material_key=key[1], variant=key[2], quantity=new
            )


@transaction.atomic
def reverse_report_consumption(block):
    for row in list(MaterialReportConsumption.objects.select_for_update().filter(block=block)):
        _consume_rows(row.kind, row.material_key, row.variant, -q(row.quantity))
    MaterialReportConsumption.objects.filter(block=block).delete()
