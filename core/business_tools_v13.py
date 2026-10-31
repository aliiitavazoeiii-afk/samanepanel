from datetime import date

import jdatetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .excel_views import _int
from .finance import digikala_fee_for_unit
from .finance_excel_v9 import digikala_receivable_total
from .material_flow import COLOR_LABELS
from .material_purchase_v13 import (
    apply_purchase_stock,
    build_purchase_from_post,
    encode_purchase_note,
    parse_purchase_note,
    purchase_summary,
)
from .models import (
    Account,
    AccountEntry,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    ExcelManualSetting,
)


PAYEE_CHOICES = [
    ("pedram", "پدرام"),
    ("tailor", "خیاط"),
    ("fabric", "پارچه‌فروش"),
    ("elastic", "کش‌فروش"),
    ("takvin", "تکوین"),
]
PAYEE_LABELS = dict(PAYEE_CHOICES)
MATERIAL_PAYEES = {"fabric", "elastic"}


def _find_row(section, needle, create=False, title=None):
    qs = ExcelManualRow.objects.filter(section=section, active=True).order_by("sort_order", "id")
    for row in qs:
        normalized = (row.title or "").replace(" ", "").lower()
        if needle in normalized:
            return row
    if not create:
        return None
    order = qs.aggregate(v=Sum("sort_order"))["v"] or 0
    return ExcelManualRow.objects.create(
        section=section,
        title=title or needle,
        amount=0,
        sort_order=order + 1,
    )


def _mellat_row(create=True):
    return _find_row(ExcelManualRow.ACCOUNTS, "ملت", create=create, title="ملت")


def _tailor_row(create=True):
    return _find_row(ExcelManualRow.PERSONS, "خیاط", create=create, title="خیاط")


def _takvin_setting():
    obj, _ = ExcelManualSetting.objects.get_or_create(
        key="takvin_debt",
        defaults={"label": "بدهی تکوین", "value": 0},
    )
    return obj


def _digikala_account():
    obj, _ = Account.objects.get_or_create(
        key=Account.DIGIKALA,
        defaults={"title": "دیجی‌کالا", "opening_balance": 0},
    )
    return obj


def mellat_balance():
    row = _mellat_row(create=False)
    return int(row.amount or 0) if row else 0


def tailor_balance():
    row = _tailor_row(create=False)
    return int(row.amount or 0) if row else 0


def _current_jalali_month_range():
    today_j = jdatetime.date.fromgregorian(date=date.today())
    start_j = jdatetime.date(today_j.year, today_j.month, 1)
    if today_j.month == 12:
        next_j = jdatetime.date(today_j.year + 1, 1, 1)
    else:
        next_j = jdatetime.date(today_j.year, today_j.month + 1, 1)
    return start_j.togregorian(), next_j.togregorian(), f"{today_j.year}/{today_j.month:02d}"


def _payment_rows():
    rows = list(BusinessPayment.objects.all()[:100])
    for row in rows:
        row.payee_label = PAYEE_LABELS.get(row.payee, row.payee)
        purchase = parse_purchase_note(row.note)
        row.is_material_purchase = bool(purchase)
        row.material_summary = purchase_summary(purchase).replace(",", "٬") if purchase else ""
        row.display_note = (purchase or {}).get("n", "") if purchase else row.note
    return rows


def _receipt_rows():
    return list(DigikalaSettlement.objects.all()[:100])


@login_required
def payments(request):
    section = (request.GET.get("section") or "").strip().lower()
    if section not in {"payments", "receipts"}:
        section = ""
    month_start, month_next, month_label = _current_jalali_month_range()
    payment_month_total = int(
        BusinessPayment.objects.filter(date__gte=month_start, date__lt=month_next).aggregate(v=Sum("amount"))["v"] or 0
    )
    receipt_month_total = int(
        DigikalaSettlement.objects.filter(date__gte=month_start, date__lt=month_next).aggregate(v=Sum("amount"))["v"] or 0
    )
    return render(
        request,
        "core/payments_v13.html",
        {
            "section": section,
            "payment_rows": _payment_rows() if section == "payments" else [],
            "receipt_rows": _receipt_rows() if section == "receipts" else [],
            "today_j": format_jalali(date.today()),
            "mellat_balance": mellat_balance(),
            "tailor_balance": tailor_balance(),
            "takvin_debt": int(_takvin_setting().value or 0),
            "digikala_receivable": digikala_receivable_total(),
            "payees": PAYEE_CHOICES,
            "material_colors": list(COLOR_LABELS.items()),
            "payment_month_total": payment_month_total,
            "receipt_month_total": receipt_month_total,
            "month_label": month_label,
        },
    )


@login_required
@require_POST
def payment_add(request):
    try:
        payment_date = parse_jalali_date(request.POST.get("date") or format_jalali(date.today()))
        payee = request.POST.get("payee") or ""
        note = (request.POST.get("note") or "").strip()
        if payee not in PAYEE_LABELS:
            raise ValueError("دریافت‌کننده پرداخت معتبر نیست.")

        purchase_data = None
        if payee in MATERIAL_PAYEES:
            amount, purchase_data = build_purchase_from_post(payee, request.POST)
        else:
            amount = _int(request.POST.get("amount"))
            if amount <= 0:
                raise ValueError("مبلغ پرداخت باید بیشتر از صفر باشد.")

        with transaction.atomic():
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) - amount
            mellat.save(update_fields=["amount", "updated_at"])

            payment = BusinessPayment.objects.create(
                date=payment_date,
                payee=payee,
                amount=amount,
                note=encode_purchase_note(purchase_data) if purchase_data else note,
            )

            if purchase_data:
                apply_purchase_stock(payment, purchase_data)
            elif payee == "tailor":
                tailor = _tailor_row(create=True)
                tailor.amount = int(tailor.amount or 0) + amount
                tailor.save(update_fields=["amount", "updated_at"])
            elif payee == "takvin":
                debt = _takvin_setting()
                debt.value = max(0, int(debt.value or 0) - amount)
                debt.save(update_fields=["value", "updated_at"])

        if purchase_data:
            messages.success(
                request,
                f"خرید از {PAYEE_LABELS[payee]} ثبت شد؛ مبلغ از ملت کم و مواد اولیه به انبار اضافه شد.",
            )
        else:
            messages.success(request, f"پرداخت به {PAYEE_LABELS[payee]} ثبت شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=payments")


@login_required
@require_POST
def payment_delete(request, payment_id):
    payment = get_object_or_404(BusinessPayment, id=payment_id)
    try:
        if parse_purchase_note(payment.note):
            raise ValueError(
                "حذف مستقیم خرید پارچه/کش غیرفعال است چون ممکن است بخشی از آن به خیاط منتقل شده باشد؛ برای اصلاح موجودی از بخش مواد اولیه استفاده کن."
            )
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
    return redirect("/payments/?section=payments")


@login_required
@require_POST
def receipt_add(request):
    try:
        receipt_date = parse_jalali_date(request.POST.get("date") or format_jalali(date.today()))
        amount = _int(request.POST.get("amount"))
        note = (request.POST.get("note") or "").strip()
        if amount <= 0:
            raise ValueError("مبلغ دریافتی باید بیشتر از صفر باشد.")
        current_receivable = digikala_receivable_total()
        if amount > current_receivable:
            raise ValueError("مبلغ دریافتی نمی‌تواند بیشتر از طلب فعلی دیجی‌کالا باشد.")
        with transaction.atomic():
            receipt = DigikalaSettlement.objects.create(date=receipt_date, amount=amount, note=note)
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) + amount
            mellat.save(update_fields=["amount", "updated_at"])
            account = _digikala_account()
            AccountEntry.objects.filter(account=account, reference=f"receipt:{receipt.id}:digikala").delete()
            AccountEntry.objects.create(
                date=receipt.date,
                account=account,
                delta=-amount,
                title="دریافت از دیجی‌کالا",
                reference=f"receipt:{receipt.id}:digikala",
                entry_type="receipt",
                note=note,
            )
        messages.success(request, "دریافتی دیجی‌کالا ثبت شد؛ طلب کم و موجودی ملت زیاد شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=receipts")


@login_required
@require_POST
def receipt_delete(request, receipt_id):
    receipt = get_object_or_404(DigikalaSettlement, id=receipt_id)
    try:
        with transaction.atomic():
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) - int(receipt.amount or 0)
            mellat.save(update_fields=["amount", "updated_at"])
            account = _digikala_account()
            AccountEntry.objects.filter(account=account, reference=f"receipt:{receipt.id}:digikala").delete()
            receipt.delete()
        messages.success(request, "دریافتی حذف شد و اثر آن روی ملت و طلب دیجی‌کالا برگشت.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=receipts")


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
    section = (request.POST.get("section") or "payments").strip()
    return redirect(f"/payments/?section={section}")


@login_required
def financial_summary(request):
    return render(
        request,
        "core/_financial_summary_extra.html",
        {"mellat_balance": mellat_balance(), "tailor_balance": tailor_balance()},
    )


@login_required
def calculator(request):
    return render(request, "core/calculator.html")


@login_required
def calculator_quote(request):
    sale_price = _int(request.GET.get("sale_price"))
    cost = _int(request.GET.get("cost"))
    fee = digikala_fee_for_unit(sale_price) if sale_price > 0 else 0
    profit = sale_price - fee - cost
    return render(
        request,
        "core/_calculator_result.html",
        {
            "sale_price": sale_price,
            "cost": cost,
            "fee": fee,
            "profit": profit,
            "profit_on_sale": (profit * 100 / sale_price) if sale_price else 0,
            "profit_on_cost": (profit * 100 / cost) if cost else 0,
        },
    )
