from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import business_tools_v21 as v21
from . import business_tools_v22 as v22
from .dateutils import format_jalali, parse_jalali_date
from .excel_views import _int
from .finance_excel_v9 import digikala_receivable_total
from .material_flow import COLOR_LABELS, q
from .material_purchase_v14 import create_purchase_ledger, ledger_for_payment, purchase_data_for_payment
from .material_purchase_v60 import (
    MULTI_KIND,
    apply_purchase_stock,
    build_purchase_from_post,
    encode_purchase_note,
    has_multi_elastic_details,
    has_multi_elastic_fields,
    invoice_value as multi_invoice_value,
    purchase_summary,
    reverse_purchase_stock,
)
from .models import BusinessPayment, DigikalaSettlement


MATERIAL_PAYEES = v22.MATERIAL_PAYEES
PAYEE_CHOICES = v22.PAYEE_CHOICES
PAYEE_LABELS = v22.PAYEE_LABELS


def _invoice_value(data):
    if data and data.get("k") == MULTI_KIND:
        return int(multi_invoice_value(data) or 0)
    return int(v22._invoice_value(data) or 0)


def _elastic_signature_rows(data):
    if not data:
        return None
    if data.get("k") == MULTI_KIND:
        rows = [
            (
                str(item.get("m") or ""),
                q(item.get("q16")),
                int(item.get("p16") or 0),
                q(item.get("q25")),
                int(item.get("p25") or 0),
            )
            for item in (data.get("items") or [])
        ]
        return tuple(sorted(rows))
    if data.get("k") == "elastic":
        return (
            (
                str(data.get("m") or ""),
                q(data.get("q16")),
                int(data.get("p16") or 0),
                q(data.get("q25")),
                int(data.get("p25") or 0),
            ),
        )
    return None


def _purchase_signature(data):
    """Physical signature normalized across legacy one-color and V60 multi elastic.

    This preserves V22's finance-only edit behavior: opening an old one-color elastic
    payment in the new all-color matrix and changing only date/note/actual-paid must
    not unnecessarily reverse raw stock merely because the payload format upgraded.
    """
    elastic_rows = _elastic_signature_rows(data)
    if elastic_rows is not None:
        return ("elastic", elastic_rows)
    return v22._purchase_signature(data)


def _has_material_details(payee, post):
    if payee == "elastic" and has_multi_elastic_fields(post):
        return has_multi_elastic_details(post)
    return v22._has_material_details(payee, post)


def _parse_payment_post(post):
    payment_date = parse_jalali_date(post.get("date") or format_jalali(date.today()))
    payee = (post.get("payee") or "").strip()
    note = (post.get("note") or "").strip()[:250]
    if payee not in PAYEE_LABELS:
        raise ValueError("دریافت‌کننده پرداخت معتبر نیست.")

    purchase_data = None
    invoice_value = 0
    prepayment_title = None
    if payee in MATERIAL_PAYEES and _has_material_details(payee, post):
        invoice_value, purchase_data = build_purchase_from_post(payee, post)
        entered_paid = _int(post.get("amount"))
        paid_amount = entered_paid if entered_paid > 0 else int(invoice_value)
        if paid_amount <= 0:
            raise ValueError("مبلغ نهایی پرداخت باید بیشتر از صفر باشد.")
    else:
        paid_amount = _int(post.get("amount"))
        if paid_amount <= 0:
            raise ValueError("مبلغ پرداخت باید بیشتر از صفر باشد.")
        if payee in MATERIAL_PAYEES:
            prepayment_title = v22._supplier_title(payee, note)

    return {
        "date": payment_date,
        "payee": payee,
        "paid": int(paid_amount),
        "note": note,
        "purchase": purchase_data,
        "invoice": int(invoice_value),
        "prepayment_title": prepayment_title,
    }


def _save_payment_fields(payment, parsed):
    payment.date = parsed["date"]
    payment.payee = parsed["payee"]
    payment.amount = parsed["paid"]
    payment.note = encode_purchase_note(parsed["purchase"]) if parsed["purchase"] else parsed["note"]
    payment.save(update_fields=["date", "payee", "amount", "note"])


def _apply_full(payment, parsed):
    purchase_data = parsed["purchase"]
    if payment.payee in MATERIAL_PAYEES:
        v22._adjust_mellat(-int(payment.amount or 0))
        if purchase_data:
            apply_purchase_stock(payment, purchase_data)
            create_purchase_ledger(payment, purchase_data)
        else:
            v22._create_prepayment_effect(payment, parsed["prepayment_title"])
        return
    v21._apply_payment_effects(payment, None, None)


def _reverse_full(payment):
    if payment.payee in MATERIAL_PAYEES:
        purchase_data = purchase_data_for_payment(payment)
        if purchase_data:
            if v22._settlement_ledger(payment) or v21._prepayment_ledger(payment):
                raise ValueError("خرید مواد نباید همزمان Ledger پیش‌پرداخت داشته باشد.")
            reverse_purchase_stock(payment, purchase_data)
            purchase_ledger = ledger_for_payment(payment)
            if purchase_ledger:
                purchase_ledger.delete()
        else:
            v22._reverse_prepayment_effect(payment)
        v22._adjust_mellat(int(payment.amount or 0))
        return
    v21._reverse_payment_effects(payment)


def _payment_rows(queryset=None):
    # The legacy page keeps its last-100 behavior. V126 can pass a paginated,
    # date-filtered queryset without modifying how payment details are decoded.
    rows = list(BusinessPayment.objects.all()[:100] if queryset is None else queryset)
    for row in rows:
        purchase = purchase_data_for_payment(row) if row.payee in MATERIAL_PAYEES else None
        prep = v22._prepayment_data_for(row) if row.payee in MATERIAL_PAYEES and not purchase else {}
        invoice = _invoice_value(purchase)
        paid = int(row.amount or 0)
        diff = invoice - paid if purchase else 0
        row.payee_label = PAYEE_LABELS.get(row.payee, row.payee)
        row.is_material_purchase = bool(purchase)
        row.is_material_prepayment = bool(row.payee in MATERIAL_PAYEES and not purchase and prep)
        row.material_summary = purchase_summary(purchase).replace(",", "٬") if purchase else ""
        row.display_note = (purchase or {}).get("n", "") if purchase else row.note
        row.purchase_data = purchase or {}
        row.invoice_value = invoice
        row.actual_paid = paid
        row.purchase_difference = diff
        row.purchase_difference_abs = abs(diff)
        row.paid_less_than_value = diff > 0
        row.paid_more_than_value = diff < 0
        row.prepayment_account = prep.get("title", "")
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
    payment_rows = _payment_rows() if section == "payments" else []
    elastic_multi_payloads = {
        str(row.id): row.purchase_data
        for row in payment_rows
        if (row.purchase_data or {}).get("k") == MULTI_KIND
    }
    return render(
        request,
        "core/payments_v60.html",
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
                note=encode_purchase_note(parsed["purchase"]) if parsed["purchase"] else parsed["note"],
            )
            _apply_full(payment, parsed)
        if parsed["purchase"]:
            messages.success(
                request,
                f"پرداخت ثبت شد؛ ارزش خرید {_invoice_value(parsed['purchase']):,} تومان و پرداخت واقعی {parsed['paid']:,} تومان بود. موجودی مواد هم اعمال شد.",
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
                and _purchase_signature(old_purchase) == _purchase_signature(parsed["purchase"])
            )

            if same_purchase:
                v22._reverse_material_purchase_finance_only(payment)
                _save_payment_fields(payment, parsed)
                create_purchase_ledger(payment, parsed["purchase"])
                v22._apply_material_purchase_finance_only(payment)
            else:
                _reverse_full(payment)
                _save_payment_fields(payment, parsed)
                _apply_full(payment, parsed)
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
            _reverse_full(payment)
            payment.delete()
        messages.success(request, "پرداخت حذف شد و اثر مالی/موجودی خودش دقیقاً برگشت.")
    except Exception as exc:
        messages.error(request, f"پرداخت حذف نشد: {exc}")
    return redirect("/payments/?section=payments")
