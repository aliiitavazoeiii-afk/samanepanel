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
from .models import BusinessPayment, ExcelManualRow


def _norm(value):
    return (value or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").replace(" ", "").strip().lower()


def _mellat_row(create=True):
    qs = ExcelManualRow.objects.filter(section=ExcelManualRow.ACCOUNTS, active=True)
    for row in qs.order_by("sort_order", "id"):
        title = _norm(row.title)
        if "ملت" in title or "mellat" in title:
            return row
    if not create:
        return None
    order = qs.aggregate(v=Sum("sort_order"))["v"] or 0
    return ExcelManualRow.objects.create(section=ExcelManualRow.ACCOUNTS, title="ملت", amount=0, sort_order=order + 1)


def _tailor_base_row():
    qs = ExcelManualRow.objects.filter(section=ExcelManualRow.PERSONS, active=True).order_by("sort_order", "id")
    for row in qs:
        if "خیاط" in _norm(row.title):
            return row
    return None


def mellat_balance():
    row = _mellat_row(create=False)
    return int(row.amount or 0) if row else 0


def tailor_base_balance():
    row = _tailor_base_row()
    return int(row.amount or 0) if row else 0


def tailor_payment_total():
    return int(BusinessPayment.objects.filter(payee=BusinessPayment.TAILOR).aggregate(v=Sum("amount"))["v"] or 0)


def tailor_balance():
    # Positive = our receivable from tailor, negative = our payable to tailor.
    return tailor_base_balance() + tailor_payment_total()


@login_required
def payments(request):
    rows = BusinessPayment.objects.all()[:100]
    totals = {key: 0 for key, _ in BusinessPayment.PAYEE_CHOICES}
    for row in BusinessPayment.objects.values("payee").annotate(v=Sum("amount")):
        totals[row["payee"]] = int(row["v"] or 0)
    return render(request, "core/payments.html", {
        "rows": rows,
        "today_j": format_jalali(date.today()),
        "mellat_balance": mellat_balance(),
        "tailor_base_balance": tailor_base_balance(),
        "tailor_payment_total": tailor_payment_total(),
        "tailor_balance": tailor_balance(),
        "payees": BusinessPayment.PAYEE_CHOICES,
        "payee_totals": totals,
    })


@login_required
@require_POST
def payment_add(request):
    try:
        payment_date = parse_jalali_date(request.POST.get("date") or format_jalali(date.today()))
        payee = request.POST.get("payee") or ""
        amount = _int(request.POST.get("amount"))
        note = (request.POST.get("note") or "").strip()
        if payee not in {key for key, _ in BusinessPayment.PAYEE_CHOICES}:
            raise ValueError("دریافت‌کننده پرداخت معتبر نیست.")
        if amount <= 0:
            raise ValueError("مبلغ پرداخت باید بیشتر از صفر باشد.")
        with transaction.atomic():
            row = _mellat_row(create=True)
            row.amount = int(row.amount or 0) - amount
            row.save(update_fields=["amount", "updated_at"])
            BusinessPayment.objects.create(date=payment_date, payee=payee, amount=amount, note=note)
        messages.success(request, "پرداخت ثبت شد و از موجودی ملت کم شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("payments")


@login_required
@require_POST
def payment_delete(request, payment_id):
    payment = get_object_or_404(BusinessPayment, id=payment_id)
    try:
        with transaction.atomic():
            row = _mellat_row(create=True)
            row.amount = int(row.amount or 0) + int(payment.amount or 0)
            row.save(update_fields=["amount", "updated_at"])
            payment.delete()
        messages.success(request, "پرداخت حذف شد و مبلغ به موجودی ملت برگشت.")
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
    profit_on_sale = (profit * 100 / sale_price) if sale_price else 0
    profit_on_cost = (profit * 100 / cost) if cost else 0
    return render(request, "core/_calculator_result.html", {
        "sale_price": sale_price,
        "cost": cost,
        "fee": fee,
        "profit": profit,
        "profit_on_sale": profit_on_sale,
        "profit_on_cost": profit_on_cost,
    })
