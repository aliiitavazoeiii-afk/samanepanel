from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_brand_color_cleanup"),
    ]

    operations = [
        migrations.CreateModel(
            name="MaterialReportOutputApplied",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("model_key", models.CharField(max_length=40)),
                ("size_key", models.CharField(max_length=20)),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "block",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="output_applications",
                        to="core.materialreportblock",
                    ),
                ),
            ],
            options={"ordering": ["block_id", "model_key", "size_key"]},
        ),
        migrations.AddConstraint(
            model_name="materialreportoutputapplied",
            constraint=models.UniqueConstraint(
                fields=("block", "model_key", "size_key"),
                name="uniq_material_report_output_applied",
            ),
        ),
    ]
