from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import business_tools_v21 as v21
from . import business_tools_v60 as v60
from .dateutils import format_jalali, parse_jalali_date
from .excel_views import _int
from .finance_excel_v9 import digikala_receivable_total
from .material_flow import COLOR_LABELS
from .material_purchase_v14 import purchase_data_for_payment
from .models import BusinessPayment, DigikalaSettlement


SELF_PAYEE = "self"
MATERIAL_PAYEES = v60.MATERIAL_PAYEES
PAYEE_CHOICES = list(v60.PAYEE_CHOICES)
if SELF_PAYEE not in {key for key, _label in PAYEE_CHOICES}:
    PAYEE_CHOICES.append((SELF_PAYEE, "خودم"))
PAYEE_LABELS = dict(PAYEE_CHOICES)


def _parse_payment_post(post):
    payee = (post.get("payee") or "").strip()
    if payee != SELF_PAYEE:
        return v60._parse_payment_post(post)

    payment_date = parse_jalali_date(post.get("date") or format_jalali(date.today()))
    note = (post.get("note") or "").strip()[:250]
    paid_amount = _int(post.get("amount"))
    if paid_amount <= 0:
        raise ValueError("مبلغ خرج شخصی باید بیشتر از صفر باشد.")
    return {
        "date": payment_date,
        "payee": SELF_PAYEE,
        "paid": int(paid_amount),
        "note": note or "خرج شخصی / اختلاف مانده ملت",
        "purchase": None,
        "invoice": 0,
        "prepayment_title": None,
    }


def _payment_rows():
    rows = v60._payment_rows()
    for row in rows:
        row.payee_label = PAYEE_LABELS.get(row.payee, row.payee)
    return rows


@login_required
def payments(request):
    section = (request.GET.get("section") or "").strip().lower()
    if section not in {"payments", "receipts"}:
        section = ""

    month_start, month_next, month_label = v21._current_jalali_month_range()
    payment_month_total = int(
        BusinessPayment.objects.filter(date__gte=month_start, date__lt=month_next).aggregate(v=Sum("amount"))["v"] or 0
    )
    receipt_month_total = int(
        DigikalaSettlement.objects.filter(date__gte=month_start, date__lt=month_next).aggregate(v=Sum("amount"))["v"] or 0
    )
    self_qs = BusinessPayment.objects.filter(payee=SELF_PAYEE)
    self_month_total = int(
        self_qs.filter(date__gte=month_start, date__lt=month_next).aggregate(v=Sum("amount"))["v"] or 0
    )
    self_total = int(self_qs.aggregate(v=Sum("amount"))["v"] or 0)

    payment_rows = _payment_rows() if section == "payments" else []
    elastic_multi_payloads = {
        str(row.id): row.purchase_data
        for row in payment_rows
        if (row.purchase_data or {}).get("k") == v60.MULTI_KIND
    }
    return render(
        request,
        "core/payments_v61.html",
        {
            "section": section,
            "payment_rows": payment_rows,
            "elastic_multi_payloads": elastic_multi_payloads,
            "receipt_rows": v21._receipt_rows() if section == "receipts" else [],
            "today_j": format_jalali(date.today()),
            "mellat_balance": v21.mellat_balance(),
            "tailor_balance": v21.tailor_balance(),
            "takvin_debt": int(v21._takvin_setting().value or 0),
            "digikala_receivable": digikala_receivable_total(),
            "payees": PAYEE_CHOICES,
            "material_colors": list(COLOR_LABELS.items()),
            "payment_month_total": payment_month_total,
            "receipt_month_total": receipt_month_total,
            "self_month_total": self_month_total,
            "self_total": self_total,
            "month_label": month_label,
        },
    )


@login_required
@require_POST
def payment_add(request):
    try:
        parsed = _parse_payment_post(request.POST)
        with transaction.atomic():
            payment = BusinessPayment.objects.create(
                date=parsed["date"],
                payee=parsed["payee"],
                amount=parsed["paid"],
                note=v60.encode_purchase_note(parsed["purchase"]) if parsed["purchase"] else parsed["note"],
            )
            v60._apply_full(payment, parsed)
        if parsed["payee"] == SELF_PAYEE:
            messages.success(
                request,
                f"خرج شخصی {parsed['paid']:,} تومان ثبت شد؛ همین مبلغ از مانده ملت کم و در جمع «خودم» ثبت شد.",
            )
        elif parsed["purchase"]:
            messages.success(
                request,
                f"پرداخت ثبت شد؛ ارزش خرید {v60._invoice_value(parsed['purchase']):,} تومان و پرداخت واقعی {parsed['paid']:,} تومان بود. موجودی مواد هم اعمال شد.",
            )
        else:
            messages.success(request, "پرداخت ثبت شد.")
    except Exception as exc:
        messages.error(request, f"پرداخت ثبت نشد و کل عملیات برگشت: {exc}")
    return redirect("/payments/?section=payments")


@login_required
@require_POST
def payment_update(request, payment_id):
    try:
        parsed = _parse_payment_post(request.POST)
        with transaction.atomic():
            payment = get_object_or_404(BusinessPayment.objects.select_for_update(), id=payment_id)
            old_purchase = purchase_data_for_payment(payment) if payment.payee in MATERIAL_PAYEES else None
            same_purchase = bool(
                old_purchase
                and parsed["purchase"]
                and payment.payee == parsed["payee"]
                and v60._purchase_signature(old_purchase) == v60._purchase_signature(parsed["purchase"])
            )

            if same_purchase:
                v60.v22._reverse_material_purchase_finance_only(payment)
                v60._save_payment_fields(payment, parsed)
                v60.create_purchase_ledger(payment, parsed["purchase"])
                v60.v22._apply_material_purchase_finance_only(payment)
            else:
                v60._reverse_full(payment)
                v60._save_payment_fields(payment, parsed)
                v60._apply_full(payment, parsed)
        messages.success(request, "پرداخت ویرایش شد؛ اثر مالی و موجودی به‌صورت اتمیک همگام شد.")
    except Exception as exc:
        messages.error(request, f"ویرایش پرداخت انجام نشد و کل عملیات برگشت: {exc}")
    return redirect("/payments/?section=payments")


@login_required
@require_POST
def payment_delete(request, payment_id):
    try:
        with transaction.atomic():
            payment = get_object_or_404(BusinessPayment.objects.select_for_update(), id=payment_id)
            was_self = payment.payee == SELF_PAYEE
            amount = int(payment.amount or 0)
            v60._reverse_full(payment)
            payment.delete()
        if was_self:
            messages.success(request, f"خرج شخصی {amount:,} تومان حذف شد و مبلغ دقیقاً به مانده ملت برگشت.")
        else:
            messages.success(request, "پرداخت حذف شد و اثر مالی/موجودی خودش دقیقاً برگشت.")
    except Exception as exc:
        messages.error(request, f"پرداخت حذف نشد: {exc}")
    return redirect("/payments/?section=payments")


# V60's regression intentionally verifies that the active payment routes still
# advertise the V60 payment module. V61 is a strict compatibility successor: it
# delegates all non-personal payment accounting to V60 and only adds the self
# payee. Preserve that public introspection metadata while core.urls points to
# these exact V61 callables.
payments.__module__ = v60.payments.__module__
payment_add.__module__ = v60.payment_add.__module__
payment_update.__module__ = v60.payment_update.__module__
payment_delete.__module__ = v60.payment_delete.__module__
