from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="saleline",
            name="inventory_applied_quantity",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
