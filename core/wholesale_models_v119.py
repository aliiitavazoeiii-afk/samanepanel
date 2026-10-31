"""Independent Novani wholesale invoices. Never write to daily SaleLine."""
import uuid

from django.db import models


class WholesaleCustomer(models.Model):
    name = models.CharField(max_length=140, unique=True)
    phone = models.CharField(max_length=40, blank=True)
    note = models.CharField(max_length=250, blank=True)
    is_pedram = models.BooleanField(default=False)
    account_row = models.ForeignKey(
        "core.ExcelManualRow", on_delete=models.PROTECT, null=True, blank=True,
        related_name="wholesale_customers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class WholesaleInvoice(models.Model):
    request_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateField(db_index=True)
    customer = models.ForeignKey(
        WholesaleCustomer, on_delete=models.PROTECT, related_name="invoices"
    )
    note = models.CharField(max_length=250, blank=True)
    total_amount = models.PositiveBigIntegerField()
    quantity_total = models.PositiveIntegerField()
    tailor_deducted_amount = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class WholesaleInvoiceLine(models.Model):
    invoice = models.ForeignKey(
        WholesaleInvoice, on_delete=models.PROTECT, related_name="lines"
    )
    color = models.ForeignKey("core.Color", on_delete=models.PROTECT)
    size = models.ForeignKey("core.Size", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.PositiveBigIntegerField()
    amount = models.PositiveBigIntegerField()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "color", "size"],
                name="uniq_wholesale_invoice_color_size",
            )
        ]


class WholesaleReceipt(models.Model):
    request_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateField(db_index=True)
    customer = models.ForeignKey(
        WholesaleCustomer, on_delete=models.PROTECT, related_name="receipts"
    )
    amount = models.PositiveBigIntegerField()
    note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
