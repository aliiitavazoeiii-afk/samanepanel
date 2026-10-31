from django.db import transaction

from .models import Brand, ProductCode, ProductComposition, ProductSize


ANBARESH_UNIT_COST = 61000


@transaction.atomic
def sync_anbaresh_catalog():
    """Mirror the Darma manual-sale catalog into Anbaresh without creating stock rows."""
    darma = Brand.objects.get(name="دارما")
    anbaresh, _ = Brand.objects.get_or_create(name="انبارش", defaults={"active": True})
    if not anbaresh.active:
        anbaresh.active = True
        anbaresh.save(update_fields=["active"])

    source_products = list(
        ProductCode.objects.filter(brand=darma).prefetch_related("composition", "sizes__size").order_by("id")
    )
    source_codes = set()

    for source in source_products:
        source_codes.add(source.code)
        target, _ = ProductCode.objects.get_or_create(
            brand=anbaresh,
            code=source.code,
            defaults={
                "pack_qty": source.pack_qty,
                "active": source.active,
                "note": "کاتالوگ خودکار دارما برای انبارش",
            },
        )
        changed = []
        if target.title != source.title:
            target.title = source.title
            changed.append("title")
        if target.pack_qty != source.pack_qty:
            target.pack_qty = source.pack_qty
            changed.append("pack_qty")
        if target.active != source.active:
            target.active = source.active
            changed.append("active")
        desired_note = "کاتالوگ خودکار دارما برای انبارش"
        if target.note != desired_note:
            target.note = desired_note
            changed.append("note")
        if changed:
            target.save(update_fields=changed)

        source_comp = {row.color_id: int(row.qty or 0) for row in source.composition.all()}
        ProductComposition.objects.filter(product=target).exclude(color_id__in=source_comp.keys()).delete()
        for color_id, qty in source_comp.items():
            ProductComposition.objects.update_or_create(
                product=target,
                color_id=color_id,
                defaults={"qty": qty},
            )

        source_sizes = list(source.sizes.select_related("size").all())
        source_size_ids = {row.size_id for row in source_sizes}
        ProductSize.objects.filter(product=target).exclude(size_id__in=source_size_ids).update(active=False)
        for source_ps in source_sizes:
            ProductSize.objects.update_or_create(
                product=target,
                size=source_ps.size,
                defaults={
                    "default_sale_price": int(source_ps.default_sale_price or 0),
                    "unit_cost": ANBARESH_UNIT_COST,
                    "active": bool(source_ps.active),
                },
            )

    ProductCode.objects.filter(brand=anbaresh).exclude(code__in=source_codes).update(active=False)
    return len(source_products)
