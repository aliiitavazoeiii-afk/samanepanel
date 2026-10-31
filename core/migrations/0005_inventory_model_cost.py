from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0004_excel_web")]

    operations = [
        migrations.CreateModel(
            name="InventoryModelCost",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("unit_cost", models.PositiveBigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("brand", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_costs", to="core.brand")),
                ("color", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_costs", to="core.color")),
                ("size", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_costs", to="core.size")),
            ],
            options={"ordering": ["brand_id", "color_id", "size_id"]},
        ),
        migrations.AddConstraint(
            model_name="inventorymodelcost",
            constraint=models.UniqueConstraint(fields=("brand", "color", "size"), name="uniq_inventory_model_cost"),
        ),
    ]
