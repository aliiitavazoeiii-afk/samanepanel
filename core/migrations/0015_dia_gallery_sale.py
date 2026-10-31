from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_novani_s_size"),
    ]

    operations = [
        migrations.CreateModel(
            name="DiaGallerySale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("inventory_applied_quantity", models.PositiveIntegerField(default=0)),
                ("unit_price", models.PositiveBigIntegerField(default=71000)),
                ("unit_cost", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("color", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="core.color")),
                ("day", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dia_gallery_sales", to="core.saleday")),
                ("size", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="core.size")),
            ],
            options={
                "ordering": ["id"],
            },
        ),
        migrations.AddConstraint(
            model_name="diagallerysale",
            constraint=models.UniqueConstraint(fields=("day", "size", "color"), name="uniq_dia_gallery_day_size_color"),
        ),
    ]
