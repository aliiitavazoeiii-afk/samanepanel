from django.db import migrations, models
import django.db.models.deletion


DARMA_COLORS = [
    "مشکی", "سفید", "سرمه ای", "صورتی", "کرم", "قرمز", "زرد", "طوسی",
    "راه راه", "راه راه طوسی", "برعکس مشکی", "برعکس سفید", "برعکس سرمه ای",
]
UNIT_COST = 61000


def norm(value):
    return (
        (value or "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("‌", "")
        .replace(" ", "")
        .strip()
        .lower()
    )


def seed_v19(apps, schema_editor):
    Brand = apps.get_model("core", "Brand")
    Color = apps.get_model("core", "Color")
    Size = apps.get_model("core", "Size")
    ProductCode = apps.get_model("core", "ProductCode")
    ProductComposition = apps.get_model("core", "ProductComposition")
    ProductSize = apps.get_model("core", "ProductSize")
    StockLocation = apps.get_model("core", "StockLocation")
    StockBalance = apps.get_model("core", "StockBalance")
    StockThreshold = apps.get_model("core", "StockThreshold")
    InventoryModelCost = apps.get_model("core", "InventoryModelCost")
    MaterialReportBlock = apps.get_model("core", "MaterialReportBlock")

    darma = Brand.objects.get(name="دارما")
    anbaresh, _ = Brand.objects.get_or_create(name="انبارش", defaults={"active": True})
    novani, _ = Brand.objects.get_or_create(name="Novani", defaults={"active": True})
    if not anbaresh.active:
        anbaresh.active = True
        anbaresh.save(update_fields=["active"])
    if not novani.active:
        novani.active = True
        novani.save(update_fields=["active"])

    # Every historical material report belongs to Darma unless explicitly created
    # under the new brand-aware workflow after this migration.
    MaterialReportBlock.objects.filter(brand__isnull=True).update(brand=darma)

    # Anbaresh is now a sales channel backed by Darma physical stock. Remove its
    # legacy inventory scaffolding. The deploy script refuses to migrate if any
    # Anbaresh stock is non-zero, so this does not silently discard asset value.
    StockBalance.objects.filter(brand=anbaresh).delete()
    StockThreshold.objects.filter(brand=anbaresh).delete()
    InventoryModelCost.objects.filter(brand=anbaresh).delete()

    # Mirror the Darma manual-sale catalog into Anbaresh. The mirror owns no stock;
    # it only gives the daily-sales UI the same codes, sizes and default prices.
    source_products = list(ProductCode.objects.filter(brand=darma).order_by("id"))
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
        target.pack_qty = source.pack_qty
        target.active = source.active
        target.note = "کاتالوگ خودکار دارما برای انبارش"
        target.save(update_fields=["pack_qty", "active", "note"])

        source_comp = list(ProductComposition.objects.filter(product=source))
        source_color_ids = {row.color_id for row in source_comp}
        ProductComposition.objects.filter(product=target).exclude(color_id__in=source_color_ids).delete()
        for row in source_comp:
            ProductComposition.objects.update_or_create(
                product=target,
                color_id=row.color_id,
                defaults={"qty": int(row.qty or 0)},
            )

        source_sizes = list(ProductSize.objects.filter(product=source))
        source_size_ids = {row.size_id for row in source_sizes}
        ProductSize.objects.filter(product=target).exclude(size_id__in=source_size_ids).update(active=False)
        for row in source_sizes:
            ProductSize.objects.update_or_create(
                product=target,
                size_id=row.size_id,
                defaults={
                    "default_sale_price": int(row.default_sale_price or 0),
                    "unit_cost": UNIT_COST,
                    "active": bool(row.active),
                },
            )
    ProductCode.objects.filter(brand=anbaresh).exclude(code__in=source_codes).update(active=False)

    # Novani is a real inventory/production brand. It intentionally uses only the
    # HOME location under the hood, which is rendered as one inventory table.
    home = StockLocation.objects.get(key="home")
    sizes = list(Size.objects.all().order_by("sort_order", "id"))
    colors = list(Color.objects.all().order_by("id"))
    by_norm = {}
    for color in colors:
        by_norm.setdefault(norm(color.name), color)

    for color_name in DARMA_COLORS:
        color = by_norm.get(norm(color_name))
        if color is None:
            color = Color.objects.create(name=color_name, active=True)
            by_norm[norm(color_name)] = color
        elif not color.active:
            color.active = True
            color.save(update_fields=["active"])
        for size in sizes:
            StockBalance.objects.get_or_create(
                brand=novani,
                color=color,
                size=size,
                location=home,
                defaults={"qty": 0},
            )
            InventoryModelCost.objects.update_or_create(
                brand=novani,
                color=color,
                size=size,
                defaults={"unit_cost": UNIT_COST},
            )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_takvin_cost_rule_and_anbaresh"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialreportblock",
            name="brand",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="material_reports",
                to="core.brand",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, reverse_noop),
        migrations.AlterField(
            model_name="materialreportblock",
            name="brand",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="material_reports",
                to="core.brand",
            ),
        ),
    ]
