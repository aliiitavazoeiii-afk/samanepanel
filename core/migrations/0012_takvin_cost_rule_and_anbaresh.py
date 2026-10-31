from datetime import date

from django.db import migrations, models
import django.db.models.deletion


DEFAULT_COSTS = {
    "M": 108000,
    "L": 126000,
    "XL": 139500,
    "XXL": 153000,
}


def seed_rules_and_anbaresh(apps, schema_editor):
    Brand = apps.get_model("core", "Brand")
    Size = apps.get_model("core", "Size")
    TakvinCostRule = apps.get_model("core", "TakvinCostRule")

    Brand.objects.get_or_create(name="انبارش", defaults={"active": True})

    effective = date(2021, 3, 21)  # 1400/01/01; historical SaleSnapshots stay frozen.
    for size_name, value in DEFAULT_COSTS.items():
        size = Size.objects.filter(name=size_name).first()
        if size:
            TakvinCostRule.objects.get_or_create(
                size=size,
                effective_from=effective,
                defaults={"unit_cost": value},
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_material_report_output_applied"),
    ]

    operations = [
        migrations.CreateModel(
            name="TakvinCostRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("effective_from", models.DateField(db_index=True)),
                ("unit_cost", models.PositiveBigIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("size", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="takvin_cost_rules", to="core.size")),
            ],
            options={"ordering": ["-effective_from", "size__sort_order", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="takvincostrule",
            constraint=models.UniqueConstraint(fields=("size", "effective_from"), name="uniq_takvin_cost_rule_date"),
        ),
        migrations.RunPython(migrations.RunPython.noop, noop),
    ]
