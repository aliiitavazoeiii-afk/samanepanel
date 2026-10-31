import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import business_tools_v21 as v21
from .dateutils import format_jalali, parse_jalali_date
from .excel_views import _int
from .finance_excel_v9 import digikala_receivable_total
from .material_flow import COLOR_LABELS, q
from .material_purchase_v13 import build_purchase_from_post, encode_purchase_note, purchase_summary
from .material_purchase_v14 import (
    apply_purchase_stock,
    create_purchase_ledger,
    ledger_for_payment,
    purchase_data_for_payment,
    reverse_purchase_stock,
)
from .models import BusinessPayment, DigikalaSettlement, ExcelManualRow, MoneyMovement


MATERIAL_PAYEES = v21.MATERIAL_PAYEES
PAYEE_CHOICES = v21.PAYEE_CHOICES
PAYEE_LABELS = v21.PAYEE_LABELS
SETTLEMENT_PREFIX = "material-settlement:"


def _round_money(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _invoice_value(data):
    if not data:
        return 0
    if data.get("k") == "fabric":
        return _round_money(q(data.get("q")) * Decimal(int(data.get("p") or 0)))
    if data.get("k") == "elastic":
        total = (
            q(data.get("q16")) * Decimal(int(data.get("p16") or 0))
            + q(data.get("q25")) * Decimal(int(data.get("p25") or 0))
        )
        return _round_money(total)
    return 0


def _purchase_signature(data):
    """Physical/value detail signature. Date, note and actual cash paid are intentionally excluded."""
    if not data:
        return None
    if data.get("k") == "fabric":
        return (
            "fabric",
            str(data.get("m") or ""),
            str(data.get("t") or "").strip(),
            q(data.get("q")),
            int(data.get("p") or 0),
        )
    if data.get("k") == "elastic":
        return (
            "elastic",
            str(data.get("m") or ""),
            str(data.get("t") or "").strip(),
            q(data.get("q16")),
            int(data.get("p16") or 0),
            q(data.get("q25")),
            int(data.get("p25") or 0),
        )
    return (str(data.get("k") or ""),)


def _settlement_title(payment_id):
    return f"{SETTLEMENT_PREFIX}{int(payment_id)}"


def _settlement_ledger(payment):
    return MoneyMovement.objects.filter(
        kind=MoneyMovement.TRANSFER,
        title=_settlement_title(payment.id),
    ).order_by("-id").first()


def _decode_json_ledger(ledger):
    if not ledger:
        return None
    try:
        value = json.loads(ledger.note or "{}")
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _supplier_title(payee, note):
    note = str(note or "").strip()
    if not note:
        example = "پارچه فروش حسینی" if payee == "fabric" else "کش فروش نام فروشنده"
        raise ValueError(f"برای پیش‌پرداخت اسم فروشنده را در توضیح بنویس؛ مثلاً «{example}».")
    return note[:160]


def _supplier_row(title, create=True):
    return v21._supplier_account_row(title, create=create)


def _create_prepayment_effect(payment, supplier_title):
    """No goods received: cash becomes a positive supplier prepayment asset in ریزحساب‌ها."""
    amount = int(payment.amount or 0)
    if amount <= 0:
        raise ValueError("مبلغ پیش‌پرداخت باید بیشتر از صفر باشد.")
    MoneyMovement.objects.filter(
        kind=MoneyMovement.TRANSFER,
        title=_settlement_title(payment.id),
    ).delete()
    row = _supplier_row(supplier_title, create=True)
    if row is None:
        raise ValueError("ریزحساب فروشنده ساخته نشد.")
    row = ExcelManualRow.objects.select_for_update().get(pk=row.pk)
    row.amount = int(row.amount or 0) + amount
    row.save(update_fields=["amount", "updated_at"])
    payload = {
        "v": 22,
        "row_id": row.id,
        "title": row.title,
        "payee": payment.payee,
        "delta": amount,
        "paid": amount,
        "invoice": 0,
    }
    return MoneyMovement.objects.create(
        date=payment.date,
        kind=MoneyMovement.TRANSFER,
        amount=amount,
        title=_settlement_title(payment.id),
        affects_capital=False,
        note=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def _reverse_prepayment_effect(payment):
    current = _settlement_ledger(payment)
    legacy = v21._prepayment_ledger(payment)
    if current and legacy:
        raise ValueError("برای این پیش‌پرداخت دو Ledger پیدا شد؛ عملیات متوقف شد.")

    if current:
        data = _decode_json_ledger(current)
        if not data or "delta" not in data:
            raise ValueError("Ledger پیش‌پرداخت قابل خواندن نیست.")
        row = ExcelManualRow.objects.select_for_update().filter(
            id=data.get("row_id"), section=ExcelManualRow.ACCOUNTS
        ).first()
        if row is None:
            row = _supplier_row(data.get("title"), create=False)
            if row:
                row = ExcelManualRow.objects.select_for_update().get(pk=row.pk)
        if row is None:
            raise ValueError("ریزحساب فروشنده مربوط به پیش‌پرداخت پیدا نشد.")
        row.amount = int(row.amount or 0) - int(data.get("delta") or 0)
        row.save(update_fields=["amount", "updated_at"])
        current.delete()
        return

    if legacy:
        data = v21._decode_prepayment(legacy)
        if not data:
            raise ValueError("Ledger قدیمی پیش‌پرداخت قابل خواندن نیست.")
        row = ExcelManualRow.objects.select_for_update().filter(
            id=data.get("row_id"), section=ExcelManualRow.ACCOUNTS
        ).first()
        if row is None:
            row = _supplier_row(data.get("title"), create=False)
            if row:
                row = ExcelManualRow.objects.select_for_update().get(pk=row.pk)
        if row is None:
            raise ValueError("ریزحساب پیش‌پرداخت قدیمی پیدا نشد.")
        row.amount = int(row.amount or 0) - int(payment.amount or 0)
        row.save(update_fields=["amount", "updated_at"])
        legacy.delete()
        return

    raise ValueError("Ledger پیش‌پرداخت پیدا نشد؛ عملیات برای حفظ سرمایه متوقف شد.")


def _has_material_details(payee, post):
    return v21._has_material_details(payee, post)


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
            prepayment_title = _supplier_title(payee, note)

    return {
        "date": payment_date,
        "payee": payee,
        "paid": int(paid_amount),
        "note": note,
        "purchase": purchase_data,
        "invoice": int(invoice_value),
        "prepayment_title": prepayment_title,
    }


def _adjust_mellat(delta):
    row = v21._mellat_row(create=True)
    row = ExcelManualRow.objects.select_for_update().get(pk=row.pk)
    row.amount = int(row.amount or 0) + int(delta)
    row.save(update_fields=["amount", "updated_at"])


def _apply_material_purchase_finance_only(payment):
    _adjust_mellat(-int(payment.amount or 0))


def _reverse_material_purchase_finance_only(payment):
    # Received goods have no supplier prepayment ledger. Only actual cash changes here.
    if _settlement_ledger(payment) or v21._prepayment_ledger(payment):
        raise ValueError("خرید تحویل‌گرفته‌شده نباید Ledger پیش‌پرداخت داشته باشد؛ عملیات متوقف شد.")
    _adjust_mellat(int(payment.amount or 0))


def _apply_full(payment, parsed):
    purchase_data = parsed["purchase"]
    if payment.payee in MATERIAL_PAYEES:
        _adjust_mellat(-int(payment.amount or 0))
        if purchase_data:
            apply_purchase_stock(payment, purchase_data)
            create_purchase_ledger(payment, purchase_data)
        else:
            _create_prepayment_effect(payment, parsed["prepayment_title"])
        return
    v21._apply_payment_effects(payment, None, None)


def _reverse_full(payment):
    if payment.payee in MATERIAL_PAYEES:
        purchase_data = purchase_data_for_payment(payment)
        if purchase_data:
            if _settlement_ledger(payment) or v21._prepayment_ledger(payment):
                raise ValueError("خرید مواد نباید همزمان Ledger پیش‌پرداخت داشته باشد.")
            reverse_purchase_stock(payment, purchase_data)
            purchase_ledger = ledger_for_payment(payment)
            if purchase_ledger:
                purchase_ledger.delete()
        else:
            _reverse_prepayment_effect(payment)
        _adjust_mellat(int(payment.amount or 0))
        return
    v21._reverse_payment_effects(payment)


def _save_payment_fields(payment, parsed):
    payment.date = parsed["date"]
    payment.payee = parsed["payee"]
    payment.amount = parsed["paid"]
    payment.note = encode_purchase_note(parsed["purchase"]) if parsed["purchase"] else parsed["note"]
    payment.save(update_fields=["date", "payee", "amount", "note"])


def _prepayment_data_for(payment):
    ledger = _settlement_ledger(payment)
    if ledger:
        return _decode_json_ledger(ledger) or {}
    legacy = v21._prepayment_ledger(payment)
    if legacy:
        data = v21._decode_prepayment(legacy) or {}
        return {
            "v": 21,
            "row_id": data.get("row_id"),
            "title": data.get("title", ""),
            "payee": payment.payee,
            "delta": int(payment.amount or 0),
            "paid": int(payment.amount or 0),
            "invoice": 0,
        }
    return {}


def _payment_rows():
    rows = list(BusinessPayment.objects.all()[:100])
    for row in rows:
        purchase = purchase_data_for_payment(row) if row.payee in MATERIAL_PAYEES else None
        prep = _prepayment_data_for(row) if row.payee in MATERIAL_PAYEES and not purchase else {}
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
    return render(
        request,
        "core/payments_v22.html",
        {
            "section": section,
            "payment_rows": _payment_rows() if section == "payments" else [],
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
            invoice = parsed["invoice"]
            paid = parsed["paid"]
            if paid == invoice:
                messages.success(request, "خرید مواد ثبت شد؛ مبلغ نهایی با ارزش محاسبه‌شده خرید برابر است.")
            else:
                messages.success(
                    request,
                    f"خرید ثبت شد؛ ارزش محاسبه‌شده {invoice:,} و مبلغ نهایی پرداخت {paid:,} تومان است. ریزحساب فروشنده تغییر نکرد چون کالا تحویل شده است.",
                )
        elif parsed["payee"] in MATERIAL_PAYEES:
            messages.success(request, f"پیش‌پرداخت در ریزحساب «{parsed['prepayment_title']}» ثبت شد.")
        else:
            messages.success(request, f"پرداخت به {PAYEE_LABELS[parsed['payee']]} ثبت شد.")
    except Exception as exc:
        messages.error(request, str(exc))
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
                # Date/note/final-cash edit only. Never reverse or move raw-material stock.
                _reverse_material_purchase_finance_only(payment)
                _save_payment_fields(payment, parsed)
                create_purchase_ledger(payment, parsed["purchase"])
                _apply_material_purchase_finance_only(payment)
                mode = "metadata"
            else:
                # Physical/value details changed (weight/color/name/unit price/payee): full safe reverse required.
                _reverse_full(payment)
                _save_payment_fields(payment, parsed)
                _apply_full(payment, parsed)
                mode = "full"

        if mode == "metadata":
            messages.success(
                request,
                "تاریخ/توضیح/مبلغ نهایی اصلاح شد؛ موجودی مواد اولیه دست نخورد. فقط مبلغ واقعی خروجی ملت و Ledger پرداخت به‌روز شد.",
            )
        else:
            messages.success(request, "پرداخت و جزئیات خرید ویرایش شد و اثرهای مالی/موجودی به‌صورت اتمیک بازسازی شدند.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=payments")


@login_required
@require_POST
def payment_delete(request, payment_id):
    try:
        with transaction.atomic():
            payment = get_object_or_404(BusinessPayment.objects.select_for_update(), id=payment_id)
            _reverse_full(payment)
            payment.delete()
        messages.success(request, "پرداخت حذف شد و تمام اثر مالی/موجودی آن برگشت.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=payments")
