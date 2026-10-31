from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_digikalasettlement_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcode",
            name="title",
            field=models.CharField(max_length=160, blank=True, default=""),
        ),
    ]
