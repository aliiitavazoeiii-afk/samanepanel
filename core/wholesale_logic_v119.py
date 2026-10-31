"""Atomic Novani wholesale ledger. Amounts in tomans; independent of SaleLine."""
import uuid
from django.db import transaction
from .brand_colors import colors_for_brand
from .business_tools_v14 import _tailor_row, _mellat_row
from .inventory_v20 import _sizes_for_brand
from .dateutils import normalize_digits, parse_jalali_date
from .models import (
    Brand, ExcelManualRow, InventoryMovement, StockBalance, StockLocation,
    WholesaleCustomer, WholesaleInvoice, WholesaleInvoiceLine, WholesaleReceipt,
)

ALLOWED_SIZES = {"S", "M", "L", "XL", "XXL", "3XL"}


def positive(value, title):
    value = normalize_digits(str(value or "")).replace("٬", "").replace(",", "").replace(" ", "")
    if not value.isdecimal() or int(value) <= 0:
        raise ValueError(f"{title}: عدد صحیح مثبت وارد کن.")
    return int(value)


def account(customer):
    invoices = list(customer.invoices.all())
    receipts = list(customer.receipts.all())
    gross = sum(int(row.total_amount) for row in invoices)
    offset = sum(int(row.tailor_deducted_amount) for row in invoices)
    received = sum(int(row.amount) for row in receipts)
    # Pedram shares the existing tailor person account. Its actual signed
    # balance also includes older tailor debt/advances and later sewing wages;
    # it must NOT be replaced by just the sums of wholesale invoices.
    if customer.is_pedram:
        tailor = _tailor_row(create=False)
        balance = int(tailor.amount or 0) if tailor else 0
    else:
        balance = gross - offset - received
    return {
        "gross": gross, "offset": offset, "received": received,
        "balance": balance,
        "invoice_outstanding": gross - offset - received,
        "count": len(invoices),
    }


def parse_items(post, brand):
    fields = [post.getlist(k) for k in ("color_id", "size_id", "quantity", "unit_price")]
    length = len(fields[0])
    if not (1 <= length <= 150) or any(len(f) != length for f in fields):
        raise ValueError("ردیف‌های فاکتور باید کامل باشند.")
    colors = {c.pk: c for c in colors_for_brand(brand)}
    sizes = {s.pk: s for s in _sizes_for_brand(brand) if s.name in ALLOWED_SIZES}
    rows, seen = [], set()
    for n, (c, s, q, p) in enumerate(zip(*fields), start=1):
        ci, si = positive(c, "رنگ"), positive(s, "سایز")
        count, price = positive(q, "تعداد"), positive(p, "فی واحد")
        if ci not in colors or si not in sizes:
            raise ValueError(f"مدل یا سایز ردیف {n} در نوانی تعریف نشده است.")
        if (ci, si) in seen:
            raise ValueError(f"رنگ/سایز تکراری در ردیف {n}؛ هر ترکیب یک‌بار.")
        seen.add((ci, si))
        rows.append((colors[ci], sizes[si], count, price))
    return rows


@transaction.atomic
def post_invoice(post):
    token = uuid.UUID(str(post.get("request_token") or ""))
    if WholesaleInvoice.objects.filter(request_token=token).exists():
        raise ValueError("این فاکتور قبلاً ثبت شده است.")
    customer = WholesaleCustomer.objects.select_for_update().get(
        pk=positive(post.get("customer_id"), "خریدار")
    )
    when = parse_jalali_date(post.get("date"))
    brand = Brand.objects.get(name="Novani", active=True)
    home = StockLocation.objects.get(key=StockLocation.HOME)
    items = parse_items(post, brand)
    stocks = {}
    for color, size, qty, price in sorted(items, key=lambda x: (x[0].pk, x[1].pk)):
        row = StockBalance.objects.select_for_update().filter(
            brand=brand, color=color, size=size, location=home
        ).first()
        if not row or int(row.qty or 0) < qty:
            available = int(row.qty or 0) if row else 0
            raise ValueError(f"موجودی {color.name} سایز {size.name} کافی نیست: {available} عدد.")
        stocks[(color.pk, size.pk)] = row

    gross = sum(qty * price for _, _, qty, price in items)
    count = sum(qty for _, _, qty, _ in items)
    invoice = WholesaleInvoice.objects.create(
        request_token=token, date=when, customer=customer, quantity_total=count, total_amount=gross,
        tailor_deducted_amount=0,  # V121: Pedram sale creates receivable, not settlement
        note=(post.get("note") or "").strip()[:250],
    )
    for color, size, qty, price in items:
        row = stocks[(color.pk, size.pk)]
        row.qty -= qty
        row.save(update_fields=["qty"])
        line = WholesaleInvoiceLine.objects.create(
            invoice=invoice, color=color, size=size,
            quantity=qty, unit_price=price, amount=qty*price,
        )
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.SALE, brand=brand,
            size=size, color=color, location=home, delta=-qty,
            reference=f"novani-wholesale:{invoice.pk}:{line.pk}",
        )

    if customer.is_pedram:
        # Shared tailor account is signed: negative means we owe Pedram;
        # positive means Pedram owes us. New wholesale sales are CREDIT to
        # our receivable, hence increase the signed balance.
        target = _tailor_row(create=True)
        target = ExcelManualRow.objects.select_for_update().get(pk=target.pk)
        target.amount = int(target.amount or 0) + gross
    else:
        if not customer.account_row_id:
            raise ValueError("حساب شخص متصل نیست.")
        target = ExcelManualRow.objects.select_for_update().get(
            pk=customer.account_row_id, section=ExcelManualRow.PERSONS,
            active=True,
        )
        target.amount = int(target.amount or 0) + gross
    target.save(update_fields=["amount", "updated_at"])
    return invoice


@transaction.atomic
def add_receipt(post):
    token = uuid.UUID(str(post.get("request_token") or ""))
    if WholesaleReceipt.objects.filter(request_token=token).exists():
        raise ValueError("این دریافت قبلاً ثبت شده است.")
    customer = WholesaleCustomer.objects.select_for_update().get(
        pk=positive(post.get("customer_id"), "خریدار")
    )
    if customer.is_pedram:
        raise ValueError("مبلغ پدرام با خیاط تهاتر شده؛ دوباره دریافت بانکی ثبت نمی‌شود.")
    amount = positive(post.get("amount"), "مبلغ دریافت")
    when = parse_jalali_date(post.get("date"))
    if amount > account(customer)["balance"]:
        raise ValueError("مبلغ دریافت بیشتر از مانده طلب این خریدار است.")
    if not customer.account_row_id:
        raise ValueError("حساب خریدار متصل نیست.")
    person = ExcelManualRow.objects.select_for_update().get(
        pk=customer.account_row_id, section=ExcelManualRow.PERSONS, active=True,
    )
    bank = _mellat_row(create=True)
    bank = ExcelManualRow.objects.select_for_update().get(pk=bank.pk)
    if int(person.amount or 0) < amount:
        raise ValueError("مانده حساب شخص برای تسویه کافی نیست.")
    receipt = WholesaleReceipt.objects.create(
        request_token=token, customer=customer, date=when, amount=amount,
        note=(post.get("note") or "").strip()[:250],
    )
    person.amount = int(person.amount or 0) - amount
    bank.amount = int(bank.amount or 0) + amount
    person.save(update_fields=["amount", "updated_at"])
    bank.save(update_fields=["amount", "updated_at"])
    return receipt
