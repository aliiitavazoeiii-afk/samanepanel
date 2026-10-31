from django.db import migrations


NOVANI_UNIT_COST = 61000


def seed_novani_s(apps, schema_editor):
    Brand = apps.get_model("core", "Brand")
    Color = apps.get_model("core", "Color")
    Size = apps.get_model("core", "Size")
    StockLocation = apps.get_model("core", "StockLocation")
    StockBalance = apps.get_model("core", "StockBalance")
    InventoryModelCost = apps.get_model("core", "InventoryModelCost")

    novani = Brand.objects.filter(name="Novani").first()
    if novani is None:
        return

    # S is a global Size row because StockBalance references Size globally, but it is
    # exposed/used only by Novani in v33. Existing size rows and their sort_order are untouched.
    s, _ = Size.objects.get_or_create(name="S", defaults={"sort_order": 0})

    home = StockLocation.objects.get(key="home")
    color_ids = list(
        StockBalance.objects.filter(brand=novani)
        .values_list("color_id", flat=True)
        .distinct()
    )
    if not color_ids:
        color_ids = list(Color.objects.filter(active=True).values_list("id", flat=True))

    for color_id in color_ids:
        StockBalance.objects.get_or_create(
            brand=novani,
            color_id=color_id,
            size=s,
            location=home,
            defaults={"qty": 0},
        )
        InventoryModelCost.objects.update_or_create(
            brand=novani,
            color_id=color_id,
            size=s,
            defaults={"unit_cost": NOVANI_UNIT_COST},
        )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_saleonly_anbaresh_novani_material_brand"),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, reverse_noop),
    ]
