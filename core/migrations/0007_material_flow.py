from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


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


def map_existing_rows(apps, schema_editor):
    RawMaterialStock = apps.get_model("core", "RawMaterialStock")
    for row in RawMaterialStock.objects.all():
        title = (row.title or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").replace(" ", "")
        key = ""
        for candidate, label in COLOR_LABELS.items():
            if label.replace("‌", "").replace(" ", "") in title:
                key = candidate
                break
        variant = ""
        if row.kind == "elastic":
            if "16" in title or "۱۶" in title:
                variant = "16"
            elif "25" in title or "۲۵" in title:
                variant = "25"
        row.material_key = key
        row.variant = variant
        row.save(update_fields=["material_key", "variant"])


class Migration(migrations.Migration):
    dependencies = [("core", "0006_raw_material_stock")]

    operations = [
        migrations.AddField(
            model_name="rawmaterialstock",
            name="material_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="rawmaterialstock",
            name="variant",
            field=models.CharField(blank=True, db_index=True, default="", max_length=20),
        ),
        migrations.RunPython(map_existing_rows, migrations.RunPython.noop),
        migrations.CreateModel(
            name="MaterialReportConsumption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("fabric", "پارچه"), ("elastic", "کش")], max_length=20)),
                ("material_key", models.CharField(max_length=40)),
                ("variant", models.CharField(blank=True, default="", max_length=20)),
                ("quantity", models.DecimalField(decimal_places=3, default=Decimal("0"), max_digits=14)),
                ("block", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stock_consumptions", to="core.materialreportblock")),
            ],
            options={"ordering": ["block_id", "kind", "material_key", "variant"]},
        ),
        migrations.AddConstraint(
            model_name="materialreportconsumption",
            constraint=models.UniqueConstraint(fields=("block", "kind", "material_key", "variant"), name="uniq_material_report_consumption"),
        ),
    ]
