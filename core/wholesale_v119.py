"""Novani wholesale pages; UI and reports are separate from daily sales."""
import uuid
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .brand_colors import colors_for_brand
from .business_tools_v14 import tailor_balance
from .dateutils import format_jalali
from .inventory_v20 import _sizes_for_brand
from .models import (
    Brand, ExcelManualRow, StockBalance, StockLocation, WholesaleCustomer,
    WholesaleInvoice, WholesaleInvoiceLine,
)
from .wholesale_logic_v119 import ALLOWED_SIZES, account, add_receipt, post_invoice


@login_required
def wholesale_home(request):
    all_customers = list(WholesaleCustomer.objects.select_related("account_row").all())
    for customer in all_customers:
        customer.ledger = account(customer)
    selected_raw = request.GET.get("customer", "")
    selected = next((x for x in all_customers if str(x.pk) == selected_raw), None)
    brand = Brand.objects.filter(name="Novani", active=True).first()
    colors = list(colors_for_brand(brand)) if brand else []
    sizes = [s for s in _sizes_for_brand(brand) if s.name in ALLOWED_SIZES] if brand else []
    stocks = {}
    if brand:
        for row in StockBalance.objects.filter(brand=brand, location__key=StockLocation.HOME):
            stocks[f"{row.color_id}:{row.size_id}"] = int(row.qty or 0)
    prices = {}
    if selected:
        for line in WholesaleInvoiceLine.objects.filter(
            invoice__customer=selected
        ).order_by("-invoice__date", "-invoice_id", "-id"):
            prices.setdefault(f"{line.color_id}:{line.size_id}", int(line.unit_price))
    invoices = list(
        WholesaleInvoice.objects.select_related("customer")
        .prefetch_related("lines__color", "lines__size")[:200]
    )
    for invoice in invoices:
        invoice.jalali_date = format_jalali(invoice.date)
    receipts = list(selected.receipts.all()[:80]) if selected else []
    for row in receipts:
        row.jalali_date = format_jalali(row.date)
    return render(request, "core/wholesale_v119.html", {
        "wholesale_customers": all_customers,
        "selected_customer": selected,
        "wholesale_colors": colors,
        "wholesale_sizes": sizes,
        "wholesale_stock": stocks,
        "wholesale_prices": prices,
        "wholesale_invoices": invoices,
        "wholesale_receipts": receipts,
        "wholesale_tailor_balance": tailor_balance(),
        "today_j": format_jalali(date.today()),
        "invoice_token": str(uuid.uuid4()),
        "receipt_token": str(uuid.uuid4()),
    })


@login_required
@require_POST
def wholesale_customer_add(request):
    name = (request.POST.get("name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()[:40]
    note = (request.POST.get("note") or "").strip()[:250]
    if not name or len(name) > 140:
        messages.error(request, "نام خریدار معتبر نیست.")
        return redirect("wholesale_home")
    normalized = name.replace("ي", "ی").replace("ك", "ک").replace(" ", "")
    if normalized in {"پدرام", "خیاط"}:
        messages.error(request, "پدرام و حساب خیاط ویژه هستند؛ خریدار پدرام را از فهرست انتخاب کن.")
        return redirect("wholesale_home")
    try:
        with transaction.atomic():
            if WholesaleCustomer.objects.filter(name=name).exists():
                raise ValueError("این خریدار قبلاً تعریف شده است.")
            manual = ExcelManualRow.objects.select_for_update().filter(
                section=ExcelManualRow.PERSONS, title=name
            ).order_by("id").first()
            if manual and WholesaleCustomer.objects.filter(account_row=manual).exists():
                raise ValueError("حساب شخص قبلاً به خریدار دیگری متصل شده است.")
            if manual is None:
                manual = ExcelManualRow.objects.create(
                    section=ExcelManualRow.PERSONS, title=name, amount=0,
                    note="حساب فروش عمده نوانی", sort_order=999,
                )
            elif not manual.active:
                raise ValueError("حساب شخص غیرفعال است.")
            customer = WholesaleCustomer.objects.create(
                name=name, phone=phone, note=note, account_row=manual
            )
        messages.success(request, f"خریدار «{name}» و حساب شخصش ثبت شد.")
        return redirect(f"/wholesale/?customer={customer.pk}")
    except Exception as exc:
        messages.error(request, str(exc))
        return redirect("wholesale_home")


@login_required
@require_POST
def wholesale_invoice_add(request):
    try:
        invoice = post_invoice(request.POST)
        messages.success(
            request,
            f"فاکتور {invoice.pk} ثبت شد: {invoice.quantity_total} عدد از موجودی نوانی کم شد؛ "
            f"مبلغ {invoice.total_amount:,} تومان به حساب اعمال شد."
        )
        return redirect(f"/wholesale/?customer={invoice.customer_id}#invoice-{invoice.pk}")
    except Exception as exc:
        messages.error(request, f"هیچ اثری از این فاکتور اعمال نشد: {exc}")
        return redirect("wholesale_home")


@login_required
@require_POST
def wholesale_receipt_add(request):
    try:
        receipt = add_receipt(request.POST)
        messages.success(request, f"دریافت {receipt.amount:,} تومان به حساب ملت ثبت شد.")
        return redirect(f"/wholesale/?customer={receipt.customer_id}")
    except Exception as exc:
        messages.error(request, str(exc))
        return redirect("wholesale_home")
