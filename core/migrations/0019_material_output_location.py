from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_productcode_title"),
    ]

    operations = [
        migrations.CreateModel(
            name="MaterialReportOutputLocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("applied", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="location_allocations", to="core.materialreportoutputapplied")),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="core.stocklocation")),
            ],
        ),
        migrations.AddConstraint(
            model_name="materialreportoutputlocation",
            constraint=models.UniqueConstraint(fields=("applied", "location"), name="uniq_material_output_location"),
        ),
    ]
