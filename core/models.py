from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Brand(models.Model):
    name = models.CharField(max_length=50, unique=True)
    active = models.BooleanField(default=True)
    def __str__(self): return self.name


class Size(models.Model):
    name = models.CharField(max_length=20, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    def __str__(self): return self.name
    class Meta:
        ordering = ["sort_order", "id"]


class Color(models.Model):
    name = models.CharField(max_length=50, unique=True)
    code = models.CharField(max_length=10, blank=True)
    active = models.BooleanField(default=True)
    def __str__(self): return self.name


class ProductCode(models.Model):
    code = models.CharField(max_length=50)
    title = models.CharField(max_length=160, blank=True, default="")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products")
    pack_qty = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["brand", "code"], name="uniq_brand_code")]
    def __str__(self): return f"{self.brand} - {self.code}"


class ProductComposition(models.Model):
    product = models.ForeignKey(ProductCode, on_delete=models.CASCADE, related_name="composition")
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField(default=1)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "color"], name="uniq_product_color")]


class ProductSize(models.Model):
    product = models.ForeignKey(ProductCode, on_delete=models.CASCADE, related_name="sizes")
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    default_sale_price = models.PositiveBigIntegerField(default=0)
    unit_cost = models.PositiveBigIntegerField(default=0)
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "size"], name="uniq_product_size")]


class StockLocation(models.Model):
    HOME = "home"
    KHORSHID = "khorshid"
    key = models.CharField(max_length=20, choices=[(HOME, "خانه"), (KHORSHID, "خورشید")], unique=True)
    title = models.CharField(max_length=50)
    def __str__(self): return self.title


class StockBalance(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    qty = models.IntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["brand", "size", "color", "location"], name="uniq_stock_balance")]


class StockThreshold(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    home_min = models.PositiveIntegerField(default=0)
    total_min = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["brand", "size", "color"], name="uniq_stock_threshold")]


class SaleDay(models.Model):
    date = models.DateField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return str(self.date)


class SaleLine(models.Model):
    day = models.ForeignKey(SaleDay, on_delete=models.CASCADE, related_name="lines")
    product_size = models.ForeignKey(ProductSize, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=0)
    inventory_applied_quantity = models.PositiveIntegerField(default=0)
    sale_price = models.PositiveBigIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["day", "product_size"], name="uniq_day_product_size")]
    @property
    def gross_sales(self): return self.quantity * self.sale_price
    @property
    def shorts_count(self): return self.quantity * self.product_size.product.pack_qty


class DiaGallerySale(models.Model):
    day = models.ForeignKey(SaleDay, on_delete=models.CASCADE, related_name="dia_gallery_sales")
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=0)
    inventory_applied_quantity = models.PositiveIntegerField(default=0)
    unit_price = models.PositiveBigIntegerField(default=71000)
    unit_cost = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["day", "size", "color"], name="uniq_dia_gallery_day_size_color")
        ]
        ordering = ["id"]

    @property
    def gross_sales(self):
        return int(self.quantity or 0) * int(self.unit_price or 0)


class Replacement(models.Model):
    sale_line = models.ForeignKey(SaleLine, on_delete=models.CASCADE, related_name="replacements")
    source_color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="replacement_sources")
    target_color = models.ForeignKey(Color, on_delete=models.PROTECT, null=True, blank=True, related_name="replacement_targets")
    qty = models.PositiveIntegerField()


class InventoryMovement(models.Model):
    PURCHASE = "purchase"
    SALE = "sale"
    TRANSFER = "transfer"
    PRODUCTION = "production"
    ADJUST = "adjust"
    movement_type = models.CharField(max_length=20, choices=[(PURCHASE, "خرید"), (SALE, "فروش"), (TRANSFER, "انتقال"), (PRODUCTION, "تولید"), (ADJUST, "اصلاح")])
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    delta = models.IntegerField()
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AppSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.CharField(max_length=200)
    label = models.CharField(max_length=120)
    updated_at = models.DateTimeField(auto_now=True)


class Account(models.Model):
    MELAT = "melat"
    MOFID = "mofid"
    DIGIKALA = "digikala"
    PEDRAM = "pedram"
    TAKVIN = "takvin"
    DIA_GALLERY = "dia_gallery"
    key = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=100)
    opening_balance = models.BigIntegerField(default=0)
    def __str__(self): return self.title


class MoneyMovement(models.Model):
    TRANSFER = "transfer"
    EXPENSE = "expense"
    SETTLEMENT = "settlement"
    PURCHASE = "purchase"
    RECEIPT = "receipt"
    date = models.DateField()
    kind = models.CharField(max_length=30, choices=[(TRANSFER, "انتقال"), (EXPENSE, "خرج"), (SETTLEMENT, "تسویه"), (PURCHASE, "خرید"), (RECEIPT, "دریافت")])
    amount = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    from_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name="out_movements")
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name="in_movements")
    title = models.CharField(max_length=150)
    affects_capital = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


from .models_final import *  # noqa: F401,F403,E402


class ExcelManualSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    value = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.label


class ExcelManualRow(models.Model):
    ACCOUNTS = "accounts"
    PERSONS = "persons"
    INVENTORY = "inventory"
    MATERIALS = "materials"
    ASSETS = "assets"
    SECTION_CHOICES = [
        (ACCOUNTS, "ریز حساب‌ها"),
        (PERSONS, "حساب اشخاص"),
        (INVENTORY, "موجودی کالا"),
        (MATERIALS, "مواد اولیه"),
        (ASSETS, "کالای سرمایه‌ای"),
    ]
    section = models.CharField(max_length=30, choices=SECTION_CHOICES, db_index=True)
    title = models.CharField(max_length=160)
    amount = models.BigIntegerField(default=0)
    unit_price = models.BigIntegerField(default=0)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    note = models.CharField(max_length=250, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "sort_order", "id"]

    def __str__(self):
        return f"{self.get_section_display()} - {self.title}"


class MaterialReportBlock(models.Model):
    date = models.DateField()
    title = models.CharField(max_length=120, blank=True)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="material_reports")
    input_data = models.JSONField(default=dict, blank=True)
    output_data = models.JSONField(default=dict, blank=True)
    delivery_wage = models.BigIntegerField(default=0)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.title or str(self.date)


RawMaterialStock.add_to_class("material_key", models.CharField(max_length=40, blank=True, default="", db_index=True))
RawMaterialStock.add_to_class("variant", models.CharField(max_length=20, blank=True, default="", db_index=True))
RawMaterialStock.DEPOT = "depot"
RawMaterialStock.LOCATION_CHOICES = [
    (RawMaterialStock.WAREHOUSE, "انبار"),
    (RawMaterialStock.TAILOR, "خیاط"),
    (RawMaterialStock.DEPOT, "دپو"),
]
RawMaterialStock._meta.get_field("location").choices = RawMaterialStock.LOCATION_CHOICES


class MaterialReportConsumption(models.Model):
    block = models.ForeignKey(MaterialReportBlock, on_delete=models.CASCADE, related_name="stock_consumptions")
    kind = models.CharField(max_length=20, choices=RawMaterialStock.KIND_CHOICES)
    material_key = models.CharField(max_length=40)
    variant = models.CharField(max_length=20, blank=True, default="")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["block", "kind", "material_key", "variant"], name="uniq_material_report_consumption")
        ]
        ordering = ["block_id", "kind", "material_key", "variant"]


class MaterialReportOutputApplied(models.Model):
    block = models.ForeignKey(MaterialReportBlock, on_delete=models.CASCADE, related_name="output_applications")
    model_key = models.CharField(max_length=40)
    size_key = models.CharField(max_length=20)
    quantity = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["block", "model_key", "size_key"], name="uniq_material_report_output_applied")
        ]
        ordering = ["block_id", "model_key", "size_key"]


class MaterialReportOutputLocation(models.Model):
    """Applied pieces of one model/size by destination; legacy totals remain authoritative."""
    applied = models.ForeignKey(
        MaterialReportOutputApplied,
        on_delete=models.CASCADE,
        related_name="location_allocations",
    )
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["applied", "location"],
                name="uniq_material_output_location",
            )
        ]


class TakvinCostRule(models.Model):
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="takvin_cost_rules")
    effective_from = models.DateField(db_index=True)
    unit_cost = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["size", "effective_from"], name="uniq_takvin_cost_rule_date")
        ]
        ordering = ["-effective_from", "size__sort_order", "-id"]

    def __str__(self):
        return f"تکوین {self.size.name} از {self.effective_from}: {self.unit_cost}"


class BusinessPayment(models.Model):
    PEDRAM = "pedram"
    TAILOR = "tailor"
    FABRIC = "fabric"
    ELASTIC = "elastic"
    SOURCE_MELAT = "melat"
    SOURCE_MOFID = "mofid"
    SOURCE_CHOICES = [
        (SOURCE_MELAT, "ملت"),
        (SOURCE_MOFID, "مفید"),
    ]
    PAYEE_CHOICES = [
        (PEDRAM, "پدرام"),
        (TAILOR, "خیاط"),
        (FABRIC, "پارچه‌فروش"),
        (ELASTIC, "کش‌فروش"),
    ]
    date = models.DateField()
    payee = models.CharField(max_length=20, choices=PAYEE_CHOICES, db_index=True)
    source_account = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MELAT, db_index=True)
    amount = models.PositiveBigIntegerField()
    note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class TailorBalanceEntry(models.Model):
    date = models.DateField()
    delta = models.BigIntegerField()
    title = models.CharField(max_length=160)
    reference = models.CharField(max_length=120, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


# Registered after existing core financial models: wholesale uses distinct ledgers.
from .wholesale_models_v119 import WholesaleCustomer, WholesaleInvoice, WholesaleInvoiceLine, WholesaleReceipt  # noqa: E402,F401


# Color-scoped material stock use, independent of finished-goods deliveries.
from .material_color_models_v123 import MaterialReportColorUse  # noqa: E402,F401
