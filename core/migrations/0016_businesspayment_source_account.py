from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0015_dia_gallery_sale")]

    operations = [
        migrations.AddField(
            model_name="businesspayment",
            name="source_account",
            field=models.CharField(
                choices=[("melat", "ملت"), ("mofid", "مفید")],
                db_index=True,
                default="melat",
                max_length=20,
            ),
        ),
    ]
