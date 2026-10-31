from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0007_material_flow")]

    operations = [
        migrations.CreateModel(
            name="BusinessPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("payee", models.CharField(choices=[("pedram", "پدرام"), ("tailor", "خیاط"), ("fabric", "پارچه‌فروش"), ("elastic", "کش‌فروش")], db_index=True, max_length=20)),
                ("amount", models.PositiveBigIntegerField()),
                ("note", models.CharField(blank=True, max_length=250)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-date", "-id"]},
        ),
        migrations.CreateModel(
            name="TailorBalanceEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("delta", models.BigIntegerField()),
                ("title", models.CharField(max_length=160)),
                ("reference", models.CharField(blank=True, db_index=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-date", "-id"]},
        ),
    ]
