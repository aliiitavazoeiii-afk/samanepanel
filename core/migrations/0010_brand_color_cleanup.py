from django.db import migrations


TAKVIN = [
    "طوسی راه راه", "زرد", "بنفش", "طوسی", "سرمه ای", "سفید", "چرک روشن",
    "مشکی", "راه راه بنفش", "راه راه سفید مشکی", "راه راه زرد", "متفرقه",
    "راه راه طوسی", "راه راه سفید", "راه راه مشکی",
]
DARMA = [
    "مشکی", "سفید", "سرمه ای", "صورتی", "کرم", "قرمز", "زرد", "طوسی",
    "راه راه", "راه راه طوسی", "برعکس مشکی", "برعکس سفید", "برعکس سرمه ای",
]


def norm(value):
    return (value or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").replace(" ", "").strip().lower()


def _merge_duplicate_color_rows(colors, StockBalance, InventoryModelCost, StockThreshold):
    groups = {}
    for color in colors:
        groups.setdefault(norm(color.name), []).append(color)

    canonical = {}
    for key, group in groups.items():
        primary = sorted(group, key=lambda c: c.id)[0]
        canonical[key] = primary
        for duplicate in sorted(group, key=lambda c: c.id)[1:]:
            for row in list(StockBalance.objects.filter(color=duplicate)):
                target, _ = StockBalance.objects.get_or_create(
                    brand_id=row.brand_id, size_id=row.size_id, color=primary, location_id=row.location_id,
                    defaults={"qty": 0},
                )
                target.qty = int(target.qty or 0) + int(row.qty or 0)
                target.save(update_fields=["qty"])
                row.delete()

            for row in list(InventoryModelCost.objects.filter(color=duplicate)):
                target, _ = InventoryModelCost.objects.get_or_create(
                    brand_id=row.brand_id, size_id=row.size_id, color=primary,
                    defaults={"unit_cost": int(row.unit_cost or 0)},
                )
                if not int(target.unit_cost or 0) and int(row.unit_cost or 0):
                    target.unit_cost = int(row.unit_cost or 0)
                    target.save(update_fields=["unit_cost"])
                row.delete()

            for row in list(StockThreshold.objects.filter(color=duplicate)):
                target, _ = StockThreshold.objects.get_or_create(
                    brand_id=row.brand_id, size_id=row.size_id, color=primary,
                    defaults={"home_min": int(row.home_min or 0), "total_min": int(row.total_min or 0)},
                )
                target.home_min = max(int(target.home_min or 0), int(row.home_min or 0))
                target.total_min = max(int(target.total_min or 0), int(row.total_min or 0))
                target.save(update_fields=["home_min", "total_min"])
                row.delete()
    return canonical


def separate_colors(apps, schema_editor):
    Brand = apps.get_model("core", "Brand")
    Color = apps.get_model("core", "Color")
    Size = apps.get_model("core", "Size")
    StockLocation = apps.get_model("core", "StockLocation")
    StockBalance = apps.get_model("core", "StockBalance")
    StockThreshold = apps.get_model("core", "StockThreshold")
    InventoryModelCost = apps.get_model("core", "InventoryModelCost")

    darma = Brand.objects.filter(name="دارما").first()
    takvin = Brand.objects.filter(name="تکوین").first()
    home = StockLocation.objects.filter(key="home").first()
    khorshid = StockLocation.objects.filter(key="khorshid").first()
    if not darma or not takvin or not home:
        return

    colors = list(Color.objects.filter(active=True).order_by("id"))
    canonical = _merge_duplicate_color_rows(colors, StockBalance, InventoryModelCost, StockThreshold)
    colors = list(canonical.values())

    takvin_norm = {norm(x) for x in TAKVIN}
    darma_norm = {norm(x) for x in DARMA}
    shared = takvin_norm & darma_norm

    # Takvin is intentionally limited to the exact workbook catalog.
    allowed_takvin_ids = {color.id for color in colors if norm(color.name) in takvin_norm}
    StockBalance.objects.filter(brand=takvin).exclude(color_id__in=allowed_takvin_ids).delete()
    InventoryModelCost.objects.filter(brand=takvin).exclude(color_id__in=allowed_takvin_ids).delete()
    StockThreshold.objects.filter(brand=takvin).exclude(color_id__in=allowed_takvin_ids).delete()

    takvin_sizes = list(Size.objects.filter(name__in=["M", "L", "XL", "XXL"]))
    for color in colors:
        if norm(color.name) not in takvin_norm:
            continue
        for size in takvin_sizes:
            StockBalance.objects.get_or_create(brand=takvin, color=color, size=size, location=home, defaults={"qty": 0})
    StockBalance.objects.filter(brand=takvin, location__key="khorshid").delete()

    # Darma keeps canonical Darma colors plus user-added colors, but not
    # Takvin-exclusive colors. Shared colors are intentionally available to both.
    darma_allowed = []
    for color in colors:
        n = norm(color.name)
        if n in takvin_norm and n not in shared and n not in darma_norm:
            continue
        darma_allowed.append(color)
    allowed_darma_ids = {color.id for color in darma_allowed}
    StockBalance.objects.filter(brand=darma).exclude(color_id__in=allowed_darma_ids).delete()
    InventoryModelCost.objects.filter(brand=darma).exclude(color_id__in=allowed_darma_ids).delete()
    StockThreshold.objects.filter(brand=darma).exclude(color_id__in=allowed_darma_ids).delete()

    darma_sizes = list(Size.objects.all().order_by("sort_order", "id"))
    for color in darma_allowed:
        for size in darma_sizes:
            StockBalance.objects.get_or_create(brand=darma, color=color, size=size, location=home, defaults={"qty": 0})
            if khorshid:
                StockBalance.objects.get_or_create(brand=darma, color=color, size=size, location=khorshid, defaults={"qty": 0})


class Migration(migrations.Migration):
    dependencies = [("core", "0009_material_depot_and_default_darma_colors")]
    operations = [migrations.RunPython(separate_colors, migrations.RunPython.noop)]
