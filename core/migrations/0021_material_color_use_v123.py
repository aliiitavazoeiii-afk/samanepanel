from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0020_novani_wholesale")]

    operations = [
        migrations.CreateModel(
            name="MaterialReportColorUse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("model_key", models.CharField(max_length=40)),
                ("kind", models.CharField(max_length=20)),
                ("material_key", models.CharField(max_length=40)),
                ("variant", models.CharField(blank=True, default="", max_length=20)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("block", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="color_consumptions", to="core.materialreportblock"
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="materialreportcoloruse",
            constraint=models.UniqueConstraint(
                fields=("block", "model_key", "kind", "material_key", "variant"),
                name="uniq_mat_color_use_v123"
            )
        ),
    ]
