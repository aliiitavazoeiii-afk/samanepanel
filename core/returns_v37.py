import re
from collections import OrderedDict, defaultdict
from datetime import date
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .final_services import sync_inventory_adjustment
from .inventory_valuation_v17 import finished_inventory_value_v17
from .models import (
    Brand, Color, InventoryAdjustment, InventoryMovement, ProductComposition,
    ProductSize, Size, StockBalance, StockLocation,
)

RETURN_BRANDS = ("دارما", "تکوین")
SIZE_MAP = {
    "دارما": ("M", "L", "XL", "XXL", "3XL", "4XL"),
    "تکوین": ("M", "L", "XL", "XXL"),
}
NOTE_PREFIX = "[standalone-return-v37]"
GROUP_RE = re.compile(r"^[0-9a-f]{12}$")
COLOR_SOURCE_RE = re.compile(r"^color=(\d+)$")
CODE_SOURCE_RE = re.compile(r"^code=(.*?) ps=(\d+) packs=(\d+)$")


def _int(value):
    try:
        return max(0, int(str(value or "0").replace(",", "").replace("٬", "").strip()))
    except (TypeError, ValueError):
        return 0


def _selected_brand(brand_name):
    if brand_name not in RETURN_BRANDS:
        return None
    return Brand.objects.filter(name=brand_name, active=True).first()


def _sizes_for_brand(brand):
    if not brand:
        return []
    by_name = {obj.name: obj for obj in Size.objects.filter(name__in=SIZE_MAP[brand.name])}
    return [by_name[name] for name in SIZE_MAP[brand.name] if name in by_name]


def _colors_for_brand(brand):
    if not brand:
        return []
    color_ids = set(
        ProductComposition.objects.filter(
            product__brand=brand,
            product__active=True,
        ).values_list("color_id", flat=True)
    )
    return list(Color.objects.filter(id__in=color_ids, active=True).order_by("id"))


def _products_for(brand, size):
    if not brand or not size:
        return []
    rows = []
    qs = (
        ProductSize.objects.filter(
            product__brand=brand,
            product__active=True,
            active=True,
            size=size,
        )
        .select_related("product", "size")
        .prefetch_related("product__composition__color")
        .order_by("product__code", "id")
    )
    for ps in qs:
        comps = list(ps.product.composition.all())
        comp_total = sum(int(c.qty or 0) for c in comps)
        fixed = bool(comps) and comp_total == int(ps.product.pack_qty or 0)
        rows.append({
            "ps": ps,
            "code": ps.product.code,
            "pack_qty": int(ps.product.pack_qty or 0),
            "fixed": fixed,
        })
    return rows


def _validate_group(group):
    group = str(group or "").strip().lower()
    if not GROUP_RE.fullmatch(group):
        raise ValueError("شناسه صورت مرجوعی معتبر نیست.")
    return group


def _parse_return_note(note):
    text = str(note or "")
    prefix = f"{NOTE_PREFIX} group="
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix):]
    if " " not in rest:
        return None
    group, source = rest.split(" ", 1)
    if not GROUP_RE.fullmatch(group):
        return None

    match = COLOR_SOURCE_RE.fullmatch(source)
    if match:
        return {"group": group, "mode": "color", "color_id": int(match.group(1))}

    match = CODE_SOURCE_RE.fullmatch(source)
    if match:
        return {
            "group": group,
            "mode": "code",
            "code": match.group(1),
            "ps_id": int(match.group(2)),
            "packs": int(match.group(3)),
        }
    return None


def _build_return_batch(group, rows):
    group = _validate_group(group)
    rows = list(rows)
    if not rows:
        raise ValueError("صورت مرجوعی پیدا نشد.")

    first = rows[0]
    base = (first.date, first.brand_id, first.size_id, first.location_id)
    safe = True
    errors = []
    modes = set()
    shorts_total = 0
    color_entries = OrderedDict()
    code_entries = OrderedDict()

    for row in rows:
        parsed = _parse_return_note(row.note)
        if (
            not parsed
            or parsed["group"] != group
            or not row.applied
            or int(row.delta or 0) <= 0
            or row.location.key != StockLocation.HOME
            or (row.date, row.brand_id, row.size_id, row.location_id) != base
        ):
            safe = False
            errors.append(f"adjustment:{row.id}")
            continue

        modes.add(parsed["mode"])
        shorts_total += int(row.delta or 0)

        if parsed["mode"] == "color":
            if parsed["color_id"] != row.color_id:
                safe = False
                errors.append(f"color:{row.id}")
                continue
            color_entries[row.color_id] = color_entries.get(row.color_id, 0) + int(row.delta or 0)
        else:
            key = parsed["ps_id"]
            item = code_entries.setdefault(
                key,
                {
                    "ps_id": parsed["ps_id"],
                    "code": parsed["code"],
                    "packs": parsed["packs"],
                    "shorts": 0,
                },
            )
            if item["code"] != parsed["code"] or item["packs"] != parsed["packs"]:
                safe = False
                errors.append(f"code:{row.id}")
                continue
            item["shorts"] += int(row.delta or 0)

    if len(modes) != 1:
        safe = False
        errors.append("mixed-mode")
        mode = ""
    else:
        mode = next(iter(modes))

    details = []
    edit_values = {}
    if mode == "color":
        color_map = {c.id: c for c in Color.objects.filter(id__in=list(color_entries.keys()))}
        for color_id, qty in color_entries.items():
            color = color_map.get(color_id)
            details.append({
                "label": color.name if color else f"رنگ #{color_id}",
                "qty": int(qty),
                "meta": "شورت تکی",
            })
            edit_values[color_id] = int(qty)
    elif mode == "code":
        for ps_id, item in code_entries.items():
            details.append({
                "label": item["code"],
                "qty": int(item["packs"]),
                "meta": f"{item['shorts']:,} شورت",
            })
            edit_values[ps_id] = int(item["packs"])

    return {
        "group": group,
        "date": first.date,
        "date_j": format_jalali(first.date),
        "brand": first.brand,
        "size": first.size,
        "mode": mode,
        "mode_title": "بر اساس رنگ" if mode == "color" else "بر اساس کد",
        "shorts": int(shorts_total),
        "details": details,
        "edit_values": edit_values,
        "latest_id": max(row.id for row in rows),
        "rows_count": len(rows),
        "safe": safe,
        "errors": errors,
    }


def _return_group_rows(group, *, lock=False):
    group = _validate_group(group)
    qs = (
        InventoryAdjustment.objects.filter(note__startswith=f"{NOTE_PREFIX} group={group} ")
        .select_related("brand", "size", "color", "location")
        .order_by("id")
    )
    if lock:
        qs = qs.select_for_update()
    rows = list(qs)
    if not rows:
        raise ValueError("این صورت مرجوعی پیدا نشد.")
    return rows


def _load_return_batch(group, *, lock=False, require_safe=True):
    rows = _return_group_rows(group, lock=lock)
    batch = _build_return_batch(group, rows)
    if require_safe and not batch["safe"]:
        raise ValueError(
            "گردش‌های این صورت مرجوعی کامل و قابل تطبیق نیستند؛ "
            "برای جلوگیری از خراب‌شدن موجودی، حذف/ویرایش متوقف شد."
        )
    return batch, rows


def _return_history(limit=100):
    rows = list(
        InventoryAdjustment.objects.filter(note__startswith=NOTE_PREFIX)
        .select_related("brand", "size", "color", "location")
        .order_by("-id")
    )
    grouped = OrderedDict()
    for row in rows:
        parsed = _parse_return_note(row.note)
        if not parsed:
            continue
        grouped.setdefault(parsed["group"], []).append(row)

    batches = []
    for group, group_rows in grouped.items():
        try:
            batch = _build_return_batch(group, list(reversed(group_rows)))
        except Exception:
            continue
        batches.append(batch)
        if len(batches) >= int(limit):
            break
    return batches


def _create_adjustment(*, when, brand, size, color, qty, group, source):
    group = _validate_group(group)
    home = StockLocation.objects.get(key=StockLocation.HOME)
    obj = InventoryAdjustment.objects.create(
        date=when,
        brand=brand,
        size=size,
        color=color,
        location=home,
        delta=int(qty),
        note=f"{NOTE_PREFIX} group={group} {source}",
    )
    sync_inventory_adjustment(obj)
    return obj


def _apply_color_batch(*, when, brand, size, entries, group=None):
    allowed = {c.id: c for c in _colors_for_brand(brand)}
    group = _validate_group(group) if group else uuid4().hex[:12]
    shorts_total = 0
    for color, qty in entries:
        qty = _int(qty)
        if not qty:
            continue
        if color.id not in allowed:
            raise ValueError("این رنگ برای برند انتخاب‌شده معتبر نیست.")
        _create_adjustment(
            when=when, brand=brand, size=size, color=color, qty=qty,
            group=group, source=f"color={color.id}",
        )
        shorts_total += qty
    if shorts_total <= 0:
        raise ValueError("حداقل یک تعداد وارد کن.")
    return {"shorts": shorts_total, "group": group}


def _apply_code_batch(*, when, brand, size, entries, group=None):
    allowed = {row["ps"].id: row for row in _products_for(brand, size)}
    group = _validate_group(group) if group else uuid4().hex[:12]
    shorts_total = 0
    for product_size, packs in entries:
        packs = _int(packs)
        if not packs:
            continue
        row = allowed.get(product_size.id)
        if not row:
            raise ValueError("این کد برای برند/سایز انتخاب‌شده معتبر نیست.")
        if not row["fixed"]:
            raise ValueError(f"کد {row['code']} ترکیب رنگ ثابت ندارد؛ آن را از مسیر «بر اساس رنگ» ثبت کن.")
        components = list(product_size.product.composition.select_related("color").all())
        component_total = 0
        for comp in components:
            units = packs * int(comp.qty or 0)
            if not units:
                continue
            _create_adjustment(
                when=when, brand=brand, size=size, color=comp.color, qty=units,
                group=group, source=f"code={row['code']} ps={product_size.id} packs={packs}",
            )
            component_total += units
        expected = packs * int(row["pack_qty"])
        if component_total != expected:
            raise ValueError(f"ترکیب کد {row['code']} با تعداد پک همخوان نیست؛ عملیات کامل برگشت.")
        shorts_total += component_total
    if shorts_total <= 0:
        raise ValueError("حداقل یک تعداد وارد کن.")
    return {"shorts": shorts_total, "group": group}


def _apply_multi_size_return(*, when, mode, brand, size_entries):
    """Apply one user submit across any number of sizes, atomically by the caller.

    Each populated size intentionally keeps its own V57 return group so existing
    view/edit/delete semantics stay exact and simple. The surrounding transaction
    makes the whole submit all-or-nothing: if any size fails, none are kept.
    """
    results = []
    shorts_total = 0
    for size, entries in size_entries:
        if not entries:
            continue
        if mode == "color":
            result = _apply_color_batch(when=when, brand=brand, size=size, entries=entries)
        elif mode == "code":
            result = _apply_code_batch(when=when, brand=brand, size=size, entries=entries)
        else:
            raise ValueError("روش مرجوعی معتبر نیست.")
        results.append({"size": size, **result})
        shorts_total += int(result["shorts"])

    if not results or shorts_total <= 0:
        raise ValueError("حداقل در یکی از سایزها تعداد وارد کن.")
    return {"shorts": shorts_total, "sizes": len(results), "results": results}


@transaction.atomic
def _reverse_return_group(group):
    batch, rows = _load_return_batch(group, lock=True, require_safe=True)
    references = [f"adjust:{row.id}" for row in rows]
    movement_rows = list(
        InventoryMovement.objects.select_for_update().filter(
            movement_type=InventoryMovement.ADJUST,
            reference__in=references,
        )
    )
    by_reference = defaultdict(list)
    for movement in movement_rows:
        by_reference[movement.reference].append(movement)

    cell_deltas = defaultdict(int)
    verified_movements = []
    for row in rows:
        reference = f"adjust:{row.id}"
        movements = by_reference.get(reference, [])
        if len(movements) != 1:
            raise ValueError(
                "گردش دقیق یکی از ردیف‌های مرجوعی پیدا نشد؛ "
                "برای حفظ موجودی، حذف/ویرایش انجام نشد."
            )
        movement = movements[0]
        if (
            movement.brand_id != row.brand_id
            or movement.size_id != row.size_id
            or movement.color_id != row.color_id
            or movement.location_id != row.location_id
            or int(movement.delta or 0) != int(row.delta or 0)
        ):
            raise ValueError(
                "گردش موجودی با صورت مرجوعی همخوان نیست؛ "
                "برای حفظ حساب موجودی، عملیات متوقف شد."
            )
        cell_deltas[(row.brand_id, row.size_id, row.color_id, row.location_id)] += int(row.delta or 0)
        verified_movements.append(movement)

    for (brand_id, size_id, color_id, location_id), delta in cell_deltas.items():
        balance, _ = StockBalance.objects.get_or_create(
            brand_id=brand_id,
            size_id=size_id,
            color_id=color_id,
            location_id=location_id,
            defaults={"qty": 0},
        )
        balance = StockBalance.objects.select_for_update().get(pk=balance.pk)
        balance.qty = int(balance.qty or 0) - int(delta)
        balance.save(update_fields=["qty"])

    InventoryMovement.objects.filter(id__in=[m.id for m in verified_movements]).delete()
    InventoryAdjustment.objects.filter(id__in=[row.id for row in rows]).delete()
    return batch


def _entries_from_post(request, *, mode, brand, size):
    """Legacy/single-size parser retained for V57 edit and stale open forms."""
    if mode == "color":
        allowed = {c.id: c for c in _colors_for_brand(brand)}
        entries = []
        for key, value in request.POST.items():
            if not key.startswith("qty_color_") or not _int(value):
                continue
            suffix = key.removeprefix("qty_color_")
            if "_" in suffix:
                continue
            try:
                color_id = int(suffix)
            except ValueError:
                raise ValueError("شناسه رنگ نامعتبر است.")
            color = allowed.get(color_id)
            if not color:
                raise ValueError("این رنگ برای برند انتخاب‌شده معتبر نیست.")
            entries.append((color, value))
        return entries

    allowed = {row["ps"].id: row for row in _products_for(brand, size)}
    entries = []
    for key, value in request.POST.items():
        if not key.startswith("qty_code_") or not _int(value):
            continue
        suffix = key.removeprefix("qty_code_")
        if "_" in suffix:
            continue
        try:
            ps_id = int(suffix)
        except ValueError:
            raise ValueError("شناسه کد نامعتبر است.")
        row = allowed.get(ps_id)
        if not row:
            raise ValueError("این کد برای برند/سایز انتخاب‌شده معتبر نیست.")
        entries.append((row["ps"], value))
    return entries


def _entries_from_multisize_post(request, *, mode, brand, sizes):
    sizes_by_id = {size.id: size for size in sizes}
    grouped = defaultdict(list)

    if mode == "color":
        allowed_colors = {color.id: color for color in _colors_for_brand(brand)}
        prefix = "qty_color_"
        for key, value in request.POST.items():
            if not key.startswith(prefix) or not _int(value):
                continue
            parts = key[len(prefix):].split("_", 1)
            if len(parts) != 2:
                continue
            try:
                size_id, color_id = int(parts[0]), int(parts[1])
            except ValueError:
                raise ValueError("شناسه سایز/رنگ نامعتبر است.")
            size = sizes_by_id.get(size_id)
            color = allowed_colors.get(color_id)
            if not size or not color:
                raise ValueError("این سایز/رنگ برای مرجوعی انتخاب‌شده معتبر نیست.")
            grouped[size_id].append((color, value))
    elif mode == "code":
        prefix = "qty_code_"
        allowed_by_size = {
            size.id: {row["ps"].id: row for row in _products_for(brand, size)}
            for size in sizes
        }
        for key, value in request.POST.items():
            if not key.startswith(prefix) or not _int(value):
                continue
            parts = key[len(prefix):].split("_", 1)
            if len(parts) != 2:
                continue
            try:
                size_id, ps_id = int(parts[0]), int(parts[1])
            except ValueError:
                raise ValueError("شناسه سایز/کد نامعتبر است.")
            size = sizes_by_id.get(size_id)
            row = allowed_by_size.get(size_id, {}).get(ps_id)
            if not size or not row:
                raise ValueError("این کد برای سایز انتخاب‌شده معتبر نیست.")
            grouped[size_id].append((row["ps"], value))
    else:
        raise ValueError("روش مرجوعی معتبر نیست.")

    return [(size, grouped.get(size.id, [])) for size in sizes if grouped.get(size.id)]


def _multi_size_sections(*, mode, brand, sizes):
    if not brand or mode not in {"color", "code"}:
        return []
    shared_colors = _colors_for_brand(brand) if mode == "color" else []
    sections = []
    for size in sizes:
        sections.append({
            "size": size,
            "colors": shared_colors if mode == "color" else [],
            "products": _products_for(brand, size) if mode == "code" else [],
        })
    return sections


@login_required
def returns_home(request):
    edit_group = (request.GET.get("edit") or "").strip().lower()
    view_group = (request.GET.get("view") or "").strip().lower()
    edit_batch = None
    view_batch = None

    if edit_group:
        try:
            edit_batch, _ = _load_return_batch(edit_group)
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("returns")
    elif view_group:
        try:
            view_batch, _ = _load_return_batch(view_group, require_safe=False)
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("returns")

    if edit_batch:
        mode = edit_batch["mode"]
        brand = edit_batch["brand"]
        sizes = _sizes_for_brand(brand)
        size = edit_batch["size"]
    else:
        mode = (request.GET.get("mode") or "").strip().lower()
        if mode not in {"color", "code"}:
            mode = ""
        brand_name = (request.GET.get("brand") or "").strip()
        brand = _selected_brand(brand_name)
        sizes = _sizes_for_brand(brand)
        size = None

    colors = _colors_for_brand(brand) if edit_batch and mode == "color" else []
    products = _products_for(brand, size) if edit_batch and mode == "code" else []
    size_sections = [] if edit_batch else _multi_size_sections(mode=mode, brand=brand, sizes=sizes)

    if edit_batch and mode == "color":
        for color in colors:
            color.return_qty = int(edit_batch["edit_values"].get(color.id, 0))
    elif edit_batch and mode == "code":
        for row in products:
            row["return_packs"] = int(edit_batch["edit_values"].get(row["ps"].id, 0))

    return render(request, "core/returns_v37.html", {
        "mode": mode,
        "brand": brand,
        "brands": [b for name in RETURN_BRANDS if (b := _selected_brand(name))],
        "sizes": sizes,
        "size": size,
        "colors": colors,
        "products": products,
        "size_sections": size_sections,
        "today_j": format_jalali(date.today()),
        "form_date_j": edit_batch["date_j"] if edit_batch else format_jalali(date.today()),
        "edit_batch": edit_batch,
        "view_batch": view_batch,
        "return_history": _return_history(),
    })


@login_required
@require_POST
def return_apply(request):
    mode = (request.POST.get("mode") or "").strip().lower()
    brand = _selected_brand((request.POST.get("brand") or "").strip())
    edit_group = (request.POST.get("edit_group") or "").strip().lower()

    if mode not in {"color", "code"} or not brand:
        messages.error(request, "مسیر مرجوعی معتبر نیست.")
        return redirect("returns")

    try:
        when = parse_jalali_date(request.POST.get("date") or format_jalali(date.today()))

        if edit_group:
            size_name = (request.POST.get("size") or "").strip()
            if size_name not in SIZE_MAP[brand.name]:
                raise ValueError("سایز صورت مرجوعی معتبر نیست.")
            size = Size.objects.filter(name=size_name).first()
            if not size:
                raise ValueError("سایز معتبر نیست.")
            entries = _entries_from_post(request, mode=mode, brand=brand, size=size)

            with transaction.atomic():
                before_value = int(finished_inventory_value_v17())
                old_batch, _ = _load_return_batch(edit_group, lock=True)
                if (
                    old_batch["mode"] != mode
                    or old_batch["brand"].id != brand.id
                    or old_batch["size"].id != size.id
                ):
                    raise ValueError(
                        "برای ویرایش امن، روش/برند/سایز صورت باید همان قبلی بماند. "
                        "اگر این موارد اشتباه است، صورت را حذف و دوباره ثبت کن."
                    )
                _reverse_return_group(edit_group)
                if mode == "color":
                    result = _apply_color_batch(
                        when=when, brand=brand, size=size, entries=entries, group=edit_group,
                    )
                else:
                    result = _apply_code_batch(
                        when=when, brand=brand, size=size, entries=entries, group=edit_group,
                    )
                after_value = int(finished_inventory_value_v17())
                value_delta = after_value - before_value

            direction = "افزایش" if value_delta >= 0 else "کاهش"
            messages.success(
                request,
                f"صورت مرجوعی ویرایش شد: جمع جدید {result['shorts']:,} شورت. "
                f"تغییر خالص ارزش موجودی/سرمایه نسبت به قبل {abs(value_delta):,} تومان {direction} بود. "
                "فروش، سود، کارمزد و طلب دیجی تغییر نکردند.",
            )
            return redirect(f"/returns/?view={result['group']}")

        sizes = _sizes_for_brand(brand)
        size_entries = _entries_from_multisize_post(request, mode=mode, brand=brand, sizes=sizes)

        # Backward compatibility for a browser tab opened before V58 deployment.
        if not size_entries:
            legacy_size_name = (request.POST.get("size") or "").strip()
            if legacy_size_name in SIZE_MAP[brand.name]:
                legacy_size = Size.objects.filter(name=legacy_size_name).first()
                if legacy_size:
                    legacy_entries = _entries_from_post(
                        request, mode=mode, brand=brand, size=legacy_size,
                    )
                    if legacy_entries:
                        size_entries = [(legacy_size, legacy_entries)]

        with transaction.atomic():
            before_value = int(finished_inventory_value_v17())
            multi = _apply_multi_size_return(
                when=when, mode=mode, brand=brand, size_entries=size_entries,
            )
            after_value = int(finished_inventory_value_v17())
            value_delta = after_value - before_value
            if value_delta <= 0:
                raise ValueError(
                    "ارزش موجودی با مرجوعی افزایش پیدا نکرد؛ "
                    "برای جلوگیری از ثبت ناقص، کل ثبت همه سایزها برگشت خورد."
                )

        messages.success(
            request,
            f"مرجوعی یکجا ثبت شد: {multi['shorts']:,} شورت در {multi['sizes']} سایز به موجودی HOME {brand.name} اضافه شد؛ "
            f"ارزش موجودی/سرمایه {value_delta:,} تومان افزایش یافت. "
            "همه سایزها در یک تراکنش ثبت شدند؛ فروش، سود، دیجی و حساب‌ها تغییر نکردند.",
        )
        return redirect(f"/returns/?mode={mode}&brand={brand.name}#return-history")

    except Exception as exc:
        messages.error(request, f"مرجوعی اعمال نشد و کل عملیات برگشت: {exc}")
        if edit_group:
            return redirect(f"/returns/?edit={edit_group}")
        return redirect(f"/returns/?mode={mode}&brand={brand.name}")


@login_required
@require_POST
def return_delete(request, group):
    try:
        group = _validate_group(group)
        with transaction.atomic():
            before_value = int(finished_inventory_value_v17())
            batch = _reverse_return_group(group)
            after_value = int(finished_inventory_value_v17())
            value_delta = after_value - before_value

        direction = "افزایش" if value_delta >= 0 else "کاهش"
        messages.success(
            request,
            f"صورت مرجوعی {batch['date_j']} حذف شد و {batch['shorts']:,} شورت از اثر مرجوعی موجودی برگشت. "
            f"ارزش موجودی/سرمایه {abs(value_delta):,} تومان {direction} یافت. "
            "فروش، دیجی و حساب‌ها دست‌نخورده ماندند.",
        )
    except Exception as exc:
        messages.error(request, f"صورت مرجوعی حذف نشد: {exc}")
    return redirect("returns")
