from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_businesspayment_source_account"),
    ]

    operations = [
        migrations.AddField(
            model_name="digikalasettlement",
            name="source",
            field=models.CharField(
                choices=[
                    ("digikala", "دیجی‌کالا"),
                    ("dia_gallery", "Dia Gallery"),
                ],
                db_index=True,
                default="digikala",
                max_length=30,
            ),
        ),
    ]
