from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from .models import (
    Account, Brand, Color, ProductSize, SaleLine, Size, StockLocation,
)


class SaleSnapshot(models.Model):
    sale_line = models.OneToOneField(SaleLine, on_delete=models.CASCADE, related_name="snapshot")
    unit_cost = models.PositiveBigIntegerField(default=0)
    pack_qty = models.PositiveIntegerField(default=0)
    digikala_fee_unit = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class AccountEntry(models.Model):
    date = models.DateField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    delta = models.BigIntegerField()
    title = models.CharField(max_length=180)
    reference = models.CharField(max_length=140, blank=True, db_index=True)
    entry_type = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]
    def __str__(self): return f"{self.account}: {self.delta}"


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    active = models.BooleanField(default=True)
    def __str__(self): return self.name


class Expense(models.Model):
    date = models.DateField()
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    amount = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    title = models.CharField(max_length=160)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class BankTransfer(models.Model):
    date = models.DateField()
    amount = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    from_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="bank_transfers_out")
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="bank_transfers_in")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class DigikalaSettlement(models.Model):
    SOURCE_DIGIKALA = "digikala"
    SOURCE_DIA_GALLERY = "dia_gallery"
    SOURCE_CHOICES = [
        (SOURCE_DIGIKALA, "دیجی‌کالا"),
        (SOURCE_DIA_GALLERY, "Dia Gallery"),
    ]
    source = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
        default=SOURCE_DIGIKALA,
        db_index=True,
    )
    date = models.DateField()
    amount = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class PedramPayment(models.Model):
    date = models.DateField()
    amount = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class TakvinPurchase(models.Model):
    date = models.DateField()
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    list_unit_price = models.PositiveBigIntegerField()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10"))
    net_unit_price = models.PositiveBigIntegerField(default=0)
    total_cost = models.PositiveBigIntegerField(default=0)
    note = models.TextField(blank=True)
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class TakvinPayment(models.Model):
    date = models.DateField()
    amount = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class StockTransfer(models.Model):
    date = models.DateField()
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    from_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="manual_transfers_out")
    to_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="manual_transfers_in")
    note = models.TextField(blank=True)
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class InventoryAdjustment(models.Model):
    date = models.DateField()
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    delta = models.IntegerField()
    note = models.TextField(blank=True)
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class FabricRoll(models.Model):
    WAREHOUSE = "warehouse"; PEDRAM = "pedram"; CONSUMED = "consumed"
    LOCATIONS = [(WAREHOUSE, "انبار"), (PEDRAM, "نزد پدرام"), (CONSUMED, "مصرف‌شده")]
    code = models.CharField(max_length=40, unique=True)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    purchase_date = models.DateField()
    weight_kg = models.DecimalField(max_digits=9, decimal_places=3)
    price_per_kg = models.PositiveBigIntegerField(default=0)
    location = models.CharField(max_length=20, choices=LOCATIONS, default=WAREHOUSE)
    supplier_name = models.CharField(max_length=100, blank=True)
    paid_from_mellat = models.BooleanField(default=True)
    finance_applied = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    @property
    def total_value(self): return int(Decimal(self.weight_kg or 0) * Decimal(self.price_per_kg or 0))
    class Meta: ordering = ["code"]


class ElasticBalance(models.Model):
    name = models.CharField(max_length=40, unique=True)
    warehouse_kg = models.DecimalField(max_digits=9, decimal_places=3, default=Decimal("0"))
    pedram_kg = models.DecimalField(max_digits=9, decimal_places=3, default=Decimal("0"))
    unit_cost = models.PositiveBigIntegerField(default=0)
    def __str__(self): return self.name


class ElasticMovement(models.Model):
    PURCHASE = "purchase"; TRANSFER = "transfer"; CONSUME = "consume"; ADJUST = "adjust"
    KINDS = [(PURCHASE, "خرید"), (TRANSFER, "تحویل به پدرام"), (CONSUME, "مصرف"), (ADJUST, "اصلاح")]
    date = models.DateField()
    elastic = models.ForeignKey(ElasticBalance, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=20, choices=KINDS)
    qty_kg = models.DecimalField(max_digits=9, decimal_places=3)
    unit_cost = models.PositiveBigIntegerField(default=0)
    note = models.TextField(blank=True)
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class ProductionBatch(models.Model):
    code = models.CharField(max_length=50, unique=True)
    fabric_roll = models.ForeignKey(FabricRoll, on_delete=models.PROTECT, null=True, blank=True, related_name="batches")
    cut_date = models.DateField()
    expected_qty = models.PositiveIntegerField(default=0)
    elastic16_used_kg = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal("0"))
    elastic25_used_kg = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal("0"))
    elastic16_unit_cost = models.PositiveBigIntegerField(default=0)
    elastic25_unit_cost = models.PositiveBigIntegerField(default=0)
    closed = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-cut_date", "-id"]
    def __str__(self): return self.code


class ProductionReceipt(models.Model):
    batch = models.ForeignKey(ProductionBatch, on_delete=models.PROTECT, related_name="receipts")
    date = models.DateField()
    size = models.ForeignKey(Size, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    destination = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    labor_total = models.PositiveBigIntegerField(default=0)
    applied = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class SupplierAccount(models.Model):
    name = models.CharField(max_length=100, unique=True)
    opening_balance = models.BigIntegerField(default=0, help_text="مثبت یعنی بدهی ما به تامین‌کننده")
    active = models.BooleanField(default=True)
    def __str__(self): return self.name


class SupplierEntry(models.Model):
    date = models.DateField()
    supplier = models.ForeignKey(SupplierAccount, on_delete=models.PROTECT, related_name="entries")
    delta = models.BigIntegerField()
    title = models.CharField(max_length=160)
    reference = models.CharField(max_length=140, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class SideAsset(models.Model):
    name = models.CharField(max_length=120)
    value = models.PositiveBigIntegerField(default=0)
    note = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["name"]


class ReturnRecord(models.Model):
    date = models.DateField()
    product_size = models.ForeignKey(ProductSize, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    refund_amount = models.PositiveBigIntegerField(default=0)
    add_back_inventory = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-date", "-id"]


class SaleAllocation(models.Model):
    sale_line = models.ForeignKey(SaleLine, on_delete=models.CASCADE, related_name="allocations")
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField()
    is_replacement = models.BooleanField(default=False)


class SaleShortage(models.Model):
    sale_line = models.ForeignKey(SaleLine, on_delete=models.CASCADE, related_name="shortages")
    source_color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="sale_shortage_sources")
    qty = models.PositiveIntegerField()
    resolved = models.BooleanField(default=False)
    target_color = models.ForeignKey(Color, on_delete=models.PROTECT, null=True, blank=True, related_name="sale_shortage_targets")
    created_at = models.DateTimeField(auto_now_add=True)


class InventoryModelCost(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="inventory_costs")
    color = models.ForeignKey(Color, on_delete=models.CASCADE, related_name="inventory_costs")
    size = models.ForeignKey(Size, on_delete=models.CASCADE, related_name="inventory_costs")
    unit_cost = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["brand", "color", "size"], name="uniq_inventory_model_cost")
        ]
        ordering = ["brand_id", "color_id", "size_id"]

    def __str__(self):
        return f"{self.brand} / {self.color} / {self.size}: {self.unit_cost}"


class RawMaterialStock(models.Model):
    FABRIC = "fabric"
    ELASTIC = "elastic"
    WAREHOUSE = "warehouse"
    TAILOR = "tailor"
    KIND_CHOICES = [(FABRIC, "پارچه"), (ELASTIC, "کش")]
    LOCATION_CHOICES = [(WAREHOUSE, "انبار"), (TAILOR, "خیاط")]

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    location = models.CharField(max_length=20, choices=LOCATION_CHOICES, db_index=True)
    title = models.CharField(max_length=120)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    unit_price = models.PositiveBigIntegerField(default=0)
    unit = models.CharField(max_length=20, default="کیلو")
    note = models.CharField(max_length=250, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_value(self):
        return int(Decimal(self.quantity or 0) * Decimal(self.unit_price or 0))

    class Meta:
        ordering = ["kind", "location", "id"]

    def __str__(self):
        return f"{self.get_kind_display()} / {self.get_location_display()} / {self.title}"