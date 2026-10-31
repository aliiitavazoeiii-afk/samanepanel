from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .excel_views import _int
from .finance import digikala_fee_for_unit
from .models import BusinessPayment, ExcelManualRow, ExcelManualSetting

PAYEE_CHOICES = [
    ("pedram", "پدرام"),
    ("tailor", "خیاط"),
    ("fabric", "پارچه‌فروش"),
    ("elastic", "کش‌فروش"),
    ("takvin", "تکوین"),
]
PAYEE_LABELS = dict(PAYEE_CHOICES)


def _find_row(section, needle, create=False, title=None):
    qs = ExcelManualRow.objects.filter(section=section, active=True).order_by("sort_order", "id")
    for row in qs:
        normalized = (row.title or "").replace(" ", "").lower()
        if needle in normalized:
            return row
    if not create:
        return None
    order = qs.aggregate(v=Sum("sort_order"))["v"] or 0
    return ExcelManualRow.objects.create(section=section, title=title or needle, amount=0, sort_order=order + 1)


def _mellat_row(create=True):
    return _find_row(ExcelManualRow.ACCOUNTS, "ملت", create=create, title="ملت")


def _tailor_row(create=True):
    return _find_row(ExcelManualRow.PERSONS, "خیاط", create=create, title="خیاط")


def _takvin_setting():
    obj, _ = ExcelManualSetting.objects.get_or_create(key="takvin_debt", defaults={"label": "بدهی تکوین", "value": 0})
    return obj


def mellat_balance():
    row = _mellat_row(create=False)
    return int(row.amount or 0) if row else 0


def tailor_balance():
    row = _tailor_row(create=False)
    return int(row.amount or 0) if row else 0


@login_required
def payments(request):
    rows = list(BusinessPayment.objects.all()[:100])
    for row in rows:
        row.payee_label = PAYEE_LABELS.get(row.payee, row.payee)
    return render(request, "core/payments.html", {
        "rows": rows,
        "today_j": format_jalali(date.today()),
        "mellat_balance": mellat_balance(),
        "tailor_balance": tailor_balance(),
        "takvin_debt": int(_takvin_setting().value or 0),
        "payees": PAYEE_CHOICES,
    })


@login_required
@require_POST
def payment_add(request):
    try:
        payment_date = parse_jalali_date(request.POST.get("date") or format_jalali(date.today()))
        payee = request.POST.get("payee") or ""
        amount = _int(request.POST.get("amount"))
        note = (request.POST.get("note") or "").strip()
        if payee not in PAYEE_LABELS:
            raise ValueError("دریافت‌کننده پرداخت معتبر نیست.")
        if amount <= 0:
            raise ValueError("مبلغ پرداخت باید بیشتر از صفر باشد.")
        with transaction.atomic():
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) - amount
            mellat.save(update_fields=["amount", "updated_at"])
            payment = BusinessPayment.objects.create(date=payment_date, payee=payee, amount=amount, note=note)
            if payee == "tailor":
                tailor = _tailor_row(create=True)
                tailor.amount = int(tailor.amount or 0) + amount
                tailor.save(update_fields=["amount", "updated_at"])
            elif payee == "takvin":
                debt = _takvin_setting()
                debt.value = max(0, int(debt.value or 0) - amount)
                debt.save(update_fields=["value", "updated_at"])
        messages.success(request, f"پرداخت به {PAYEE_LABELS[payee]} ثبت شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("payments")


@login_required
@require_POST
def payment_delete(request, payment_id):
    payment = get_object_or_404(BusinessPayment, id=payment_id)
    try:
        with transaction.atomic():
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) + int(payment.amount or 0)
            mellat.save(update_fields=["amount", "updated_at"])
            if payment.payee == "tailor":
                tailor = _tailor_row(create=True)
                tailor.amount = int(tailor.amount or 0) - int(payment.amount or 0)
                tailor.save(update_fields=["amount", "updated_at"])
            elif payment.payee == "takvin":
                debt = _takvin_setting()
                debt.value = int(debt.value or 0) + int(payment.amount or 0)
                debt.save(update_fields=["value", "updated_at"])
            payment.delete()
        messages.success(request, "پرداخت حذف شد و اثر مالی آن برگشت.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("payments")


@login_required
@require_POST
def mellat_set(request):
    try:
        row = _mellat_row(create=True)
        row.amount = _int(request.POST.get("amount"))
        row.save(update_fields=["amount", "updated_at"])
        messages.success(request, "موجودی ملت اصلاح شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("payments")


@login_required
def financial_summary(request):
    return render(request, "core/_financial_summary_extra.html", {
        "mellat_balance": mellat_balance(),
        "tailor_balance": tailor_balance(),
    })


@login_required
def calculator(request):
    return render(request, "core/calculator.html")


@login_required
def calculator_quote(request):
    sale_price = _int(request.GET.get("sale_price"))
    cost = _int(request.GET.get("cost"))
    fee = digikala_fee_for_unit(sale_price) if sale_price > 0 else 0
    profit = sale_price - fee - cost
    return render(request, "core/_calculator_result.html", {
        "sale_price": sale_price, "cost": cost, "fee": fee, "profit": profit,
        "profit_on_sale": (profit * 100 / sale_price) if sale_price else 0,
        "profit_on_cost": (profit * 100 / cost) if cost else 0,
    })
