import uuid

from django.db import migrations, models
import django.db.models.deletion


def register_pedram(apps, schema_editor):
    Customer = apps.get_model("core", "WholesaleCustomer")
    Customer.objects.using(schema_editor.connection.alias).get_or_create(
        name="پدرام",
        defaults={"is_pedram": True, "note": "متصل به حساب خیاط؛ فقط فروش عمده نوانی"},
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0019_material_output_location")]
    operations = [
        migrations.CreateModel(
            name="WholesaleCustomer",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("name", models.CharField(max_length=140, unique=True)),
                ("phone", models.CharField(max_length=40, blank=True)),
                ("note", models.CharField(max_length=250, blank=True)),
                ("is_pedram", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("account_row", models.ForeignKey(to="core.excelmanualrow", on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, related_name="wholesale_customers")),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="WholesaleInvoice",
            fields=[
                ("request_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                ("note", models.CharField(max_length=250, blank=True)),
                ("total_amount", models.PositiveBigIntegerField()),
                ("quantity_total", models.PositiveIntegerField()),
                ("tailor_deducted_amount", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("customer", models.ForeignKey(to="core.wholesalecustomer", on_delete=django.db.models.deletion.PROTECT, related_name="invoices")),
            ],
            options={"ordering": ["-date", "-id"]},
        ),
        migrations.CreateModel(
            name="WholesaleInvoiceLine",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("unit_price", models.PositiveBigIntegerField()),
                ("amount", models.PositiveBigIntegerField()),
                ("color", models.ForeignKey(to="core.color", on_delete=django.db.models.deletion.PROTECT)),
                ("size", models.ForeignKey(to="core.size", on_delete=django.db.models.deletion.PROTECT)),
                ("invoice", models.ForeignKey(to="core.wholesaleinvoice", on_delete=django.db.models.deletion.PROTECT, related_name="lines")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="wholesaleinvoiceline",
            constraint=models.UniqueConstraint(fields=("invoice", "color", "size"), name="uniq_wholesale_invoice_color_size"),
        ),
        migrations.CreateModel(
            name="WholesaleReceipt",
            fields=[
                ("request_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                ("amount", models.PositiveBigIntegerField()),
                ("note", models.CharField(max_length=250, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("customer", models.ForeignKey(to="core.wholesalecustomer", on_delete=django.db.models.deletion.PROTECT, related_name="receipts")),
            ],
            options={"ordering": ["-date", "-id"]},
        ),
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
