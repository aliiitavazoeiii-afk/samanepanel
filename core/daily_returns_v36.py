from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .final_services import sync_inventory_adjustment
from .models import Brand, InventoryAdjustment, ProductComposition, ProductSize, SaleDay, StockLocation

RETURN_BRANDS = ("دارما", "تکوین")
RETURN_NOTE_PREFIX = "[daily-return-v36]"


def _int(value):
    try:
        return max(0, int(str(value or "0").replace(",", "").replace("٬", "").strip()))
    except (TypeError, ValueError):
        return 0


def _brand_size_guard(brand, size):
    if brand.name not in RETURN_BRANDS:
        raise ValueError("مرجوعی روزانه فقط برای دارما و تکوین فعال است.")
    if brand.name == "تکوین" and size.name in {"3XL", "4XL", "S"}:
        raise ValueError("این سایز برای تکوین فعال نیست.")
    if brand.name == "دارما" and size.name == "S":
        raise ValueError("سایز S برای دارما فعال نیست.")


def _create_adjustment(*, day, brand, size, color, qty, group, source):
    if qty <= 0:
        return None
    home = StockLocation.objects.get(key=StockLocation.HOME)
    obj = InventoryAdjustment.objects.create(
        date=day.date,
        brand=brand,
        size=size,
        color=color,
        location=home,
        delta=int(qty),
        note=f"{RETURN_NOTE_PREFIX} group={group} {source}",
    )
    sync_inventory_adjustment(obj)
    return obj


def _apply_return_batch(*, day, brand, size, loose_by_color, pack_by_product_size):
    """Apply an isolated HOME stock return batch. No sale/finance objects are touched."""
    _brand_size_guard(brand, size)
    group = uuid4().hex[:12]
    created = []
    shorts_total = 0

    for color, qty in loose_by_color:
        qty = _int(qty)
        if not qty:
            continue
        obj = _create_adjustment(
            day=day,
            brand=brand,
            size=size,
            color=color,
            qty=qty,
            group=group,
            source=f"loose color={color.id}",
        )
        if obj:
            created.append(obj)
            shorts_total += qty

    for product_size, packs in pack_by_product_size:
        packs = _int(packs)
        if not packs:
            continue
        if product_size.product.brand_id != brand.id or product_size.size_id != size.id:
            raise ValueError("کد/سایز مرجوعی با برند یا سایز انتخاب‌شده همخوان نیست.")
        if not product_size.active or not product_size.product.active:
            raise ValueError(f"کد {product_size.product.code} برای این سایز فعال نیست.")

        components = list(
            ProductComposition.objects.filter(product=product_size.product).select_related("color")
        )
        if not components:
            raise ValueError(
                f"کد {product_size.product.code} ترکیب رنگ ثابت ندارد؛ این مرجوعی را از بخش «شورت تکی / رنگ» ثبت کن."
            )

        component_shorts = 0
        for comp in components:
            units = packs * int(comp.qty or 0)
            if not units:
                continue
            obj = _create_adjustment(
                day=day,
                brand=brand,
                size=size,
                color=comp.color,
                qty=units,
                group=group,
                source=f"pack ps={product_size.id} code={product_size.product.code} packs={packs}",
            )
            if obj:
                created.append(obj)
                component_shorts += units
        expected = packs * int(product_size.product.pack_qty or 0)
        if component_shorts != expected:
            raise ValueError(
                f"ترکیب کد {product_size.product.code} با pack_qty همخوان نیست: ترکیب={component_shorts}، انتظار={expected}. "
                "هیچ مرجوعی اعمال نشد."
            )
        shorts_total += component_shorts

    if not created:
        raise ValueError("حداقل یک تعداد مرجوعی وارد کن.")

    return {"group": group, "rows": len(created), "shorts": shorts_total}


@login_required
@require_POST
def daily_return_add(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)
    try:
        with transaction.atomic():
            brand = get_object_or_404(Brand, id=request.POST.get("brand_id"), active=True)
            size_id = request.POST.get("size_id")
            product_sizes = list(
                ProductSize.objects.filter(
                    product__brand=brand,
                    size_id=size_id,
                    active=True,
                    product__active=True,
                ).select_related("product", "size")
            )
            if not product_sizes:
                raise ValueError("برای این برند/سایز کد فعالی پیدا نشد.")
            size = product_sizes[0].size
            _brand_size_guard(brand, size)

            color_ids = []
            for key in request.POST.keys():
                if key.startswith("return_loose_") and _int(request.POST.get(key)):
                    try:
                        color_ids.append(int(key.removeprefix("return_loose_")))
                    except ValueError:
                        raise ValueError("شناسه رنگ مرجوعی نامعتبر است.")
            from .models import Color
            color_map = {
                obj.id: obj
                for obj in Color.objects.filter(id__in=color_ids, active=True)
            }
            loose = []
            for color_id in color_ids:
                color = color_map.get(color_id)
                if not color:
                    raise ValueError("یکی از رنگ‌های مرجوعی معتبر/فعال نیست.")
                loose.append((color, request.POST.get(f"return_loose_{color_id}")))

            ps_map = {obj.id: obj for obj in product_sizes}
            pack = []
            for key in request.POST.keys():
                if key.startswith("return_pack_") and _int(request.POST.get(key)):
                    try:
                        ps_id = int(key.removeprefix("return_pack_"))
                    except ValueError:
                        raise ValueError("شناسه کد مرجوعی نامعتبر است.")
                    ps = ps_map.get(ps_id)
                    if not ps:
                        raise ValueError("یکی از کدهای مرجوعی متعلق به برند/سایز انتخاب‌شده نیست.")
                    pack.append((ps, request.POST.get(key)))

            result = _apply_return_batch(
                day=day,
                brand=brand,
                size=size,
                loose_by_color=loose,
                pack_by_product_size=pack,
            )
        messages.success(
            request,
            f"مرجوعی ثبت شد: {result['shorts']:,} شورت مستقیم به موجودی خانه {brand.name} اضافه شد؛ "
            "فروش، سود، هزینه دیجی و طلب دیجی تغییر نکرد.",
        )
    except Exception as exc:
        messages.error(request, f"مرجوعی اعمال نشد و کل عملیات برگشت: {exc}")
    return redirect("daily_report", day_id=day.id)
