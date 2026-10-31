from django.db import migrations, models


def attach_orphan_colors_to_darma(apps, schema_editor):
    Brand = apps.get_model("core", "Brand")
    Color = apps.get_model("core", "Color")
    Size = apps.get_model("core", "Size")
    StockLocation = apps.get_model("core", "StockLocation")
    StockBalance = apps.get_model("core", "StockBalance")
    ProductComposition = apps.get_model("core", "ProductComposition")
    InventoryModelCost = apps.get_model("core", "InventoryModelCost")

    darma = Brand.objects.filter(name="دارما").first()
    home = StockLocation.objects.filter(key="home").first()
    khorshid = StockLocation.objects.filter(key="khorshid").first()
    if not darma or not home:
        return

    connected = set(StockBalance.objects.values_list("color_id", flat=True))
    connected.update(ProductComposition.objects.values_list("color_id", flat=True))
    orphan_colors = Color.objects.filter(active=True).exclude(id__in=connected)
    sizes = list(Size.objects.all().order_by("sort_order", "id"))

    for color in orphan_colors:
        for size in sizes:
            StockBalance.objects.get_or_create(
                brand=darma, size=size, color=color, location=home,
                defaults={"qty": 0},
            )
            if khorshid:
                StockBalance.objects.get_or_create(
                    brand=darma, size=size, color=color, location=khorshid,
                    defaults={"qty": 0},
                )
            InventoryModelCost.objects.get_or_create(
                brand=darma, color=color, size=size,
                defaults={"unit_cost": 0},
            )


def repair_legacy_tailor_person_row(apps, schema_editor):
    ExcelManualRow = apps.get_model("core", "ExcelManualRow")
    TailorBalanceEntry = apps.get_model("core", "TailorBalanceEntry")

    candidates = ExcelManualRow.objects.filter(section="persons", active=True)
    row = None
    for candidate in candidates.order_by("sort_order", "id"):
        title = (candidate.title or "").replace(" ", "").replace("‌", "")
        if "خیاط" in title:
            row = candidate
            break
    if not row:
        return

    # Older code overwrote this manual person row with the internal tailor ledger.
    # Only repair rows explicitly marked by that old sync, never arbitrary user rows.
    if (row.note or "").strip() != "همگام با بخش پرداختی‌ها":
        return

    opening = TailorBalanceEntry.objects.filter(reference="opening-from-person-row").order_by("id").first()
    row.amount = int(opening.delta or 0) if opening else 0
    row.note = "مانده پایه خیاط؛ پرداخت‌های جدید جداگانه روی آن محاسبه می‌شوند"
    row.save(update_fields=["amount", "note", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("core", "0008_payments")]

    operations = [
        migrations.AlterField(
            model_name="rawmaterialstock",
            name="location",
            field=models.CharField(
                choices=[("warehouse", "انبار"), ("tailor", "خیاط"), ("depot", "دپو")],
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.RunPython(attach_orphan_colors_to_darma, migrations.RunPython.noop),
        migrations.RunPython(repair_legacy_tailor_person_row, migrations.RunPython.noop),
    ]
