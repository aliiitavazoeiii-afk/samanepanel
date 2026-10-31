from decimal import Decimal

from django.db import migrations, models


def migrate_manual_materials(apps, schema_editor):
    ExcelManualRow = apps.get_model("core", "ExcelManualRow")
    RawMaterialStock = apps.get_model("core", "RawMaterialStock")

    for row in ExcelManualRow.objects.filter(section="materials", active=True).iterator():
        quantity = row.quantity or Decimal("0")
        unit_price = int(row.unit_price or 0)
        amount = int(row.amount or 0)

        # Preserve old manual value even if the old row had only a total amount.
        if (quantity <= 0 or unit_price <= 0) and amount > 0:
            quantity = Decimal("1")
            unit_price = amount

        RawMaterialStock.objects.create(
            kind="fabric",
            location="warehouse",
            title=row.title or "مواد اولیه قدیمی",
            quantity=quantity,
            unit_price=max(0, unit_price),
            unit="کیلو" if quantity != Decimal("1") else "واحد",
            note=row.note or "انتقال خودکار از ساختار قبلی گزارش جامع",
            active=True,
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0005_inventory_model_cost")]

    operations = [
        migrations.CreateModel(
            name="RawMaterialStock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("fabric", "پارچه"), ("elastic", "کش")], db_index=True, max_length=20)),
                ("location", models.CharField(choices=[("warehouse", "انبار"), ("tailor", "خیاط")], db_index=True, max_length=20)),
                ("title", models.CharField(max_length=120)),
                ("quantity", models.DecimalField(decimal_places=3, default=Decimal("0"), max_digits=14)),
                ("unit_price", models.PositiveBigIntegerField(default=0)),
                ("unit", models.CharField(default="کیلو", max_length=20)),
                ("note", models.CharField(blank=True, max_length=250)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["kind", "location", "id"]},
        ),
        migrations.RunPython(migrate_manual_materials, migrations.RunPython.noop),
    ]
