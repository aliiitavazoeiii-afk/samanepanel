from decimal import Decimal

from django.db import migrations, models


def seed_excel_web(apps, schema_editor):
    Setting = apps.get_model("core", "ExcelManualSetting")
    Row = apps.get_model("core", "ExcelManualRow")

    for key, label in [
        ("takvin_debt", "بدهی تکوین"),
        ("digikala_receivable", "طلب دیجی‌کالا"),
    ]:
        Setting.objects.get_or_create(key=key, defaults={"label": label, "value": 0})

    seeds = {
        "accounts": ["مانده مفید", "دلار و یورو", "حساب ملت", "VPN", "پارچه", "بابا"],
        "persons": ["پول پیش انبار", "پدرام", "پول پیش انبار 2"],
        "inventory": ["تکوین", "دارما", "سایر موجودی کالا"],
        "materials": [
            "پارچه جودون", "کش 30 کیلو", "قاسمی", "3 طاق بنفش فرمی ماتیکی",
            "پارچه تیپ تهران بافت سفید", "کش 10 کیلو مهرشهر", "محمدی مزد",
            "تگ زیرپوش", "بدهی دیا پارچه",
        ],
        "assets": ["گیتار الکتریک", "ویدئو پرژکتور", "سرفیس", "گوشی", "DJ"],
    }
    for section, titles in seeds.items():
        if Row.objects.filter(section=section).exists():
            continue
        for index, title in enumerate(titles, 1):
            Row.objects.create(section=section, title=title, sort_order=index, amount=0)


class Migration(migrations.Migration):
    dependencies = [("core", "0003_final_erp")]

    operations = [
        migrations.CreateModel(
            name="ExcelManualSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=80, unique=True)),
                ("label", models.CharField(max_length=120)),
                ("value", models.BigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="ExcelManualRow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("section", models.CharField(choices=[("accounts", "ریز حساب‌ها"), ("persons", "حساب اشخاص"), ("inventory", "موجودی کالا"), ("materials", "مواد اولیه"), ("assets", "کالای سرمایه‌ای")], db_index=True, max_length=30)),
                ("title", models.CharField(max_length=160)),
                ("amount", models.BigIntegerField(default=0)),
                ("unit_price", models.BigIntegerField(default=0)),
                ("quantity", models.DecimalField(decimal_places=3, default=Decimal("0"), max_digits=14)),
                ("note", models.CharField(blank=True, max_length=250)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["section", "sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="MaterialReportBlock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("title", models.CharField(blank=True, max_length=120)),
                ("input_data", models.JSONField(blank=True, default=dict)),
                ("output_data", models.JSONField(blank=True, default=dict)),
                ("delivery_wage", models.BigIntegerField(default=0)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-date", "-id"]},
        ),
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
