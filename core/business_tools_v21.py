import json
import re
from datetime import date

import jdatetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .business_tools_v14 import (
    MATERIAL_PAYEES,
    PAYEE_CHOICES,
    PAYEE_LABELS,
    _digikala_account,
    _mellat_row,
    _tailor_row,
    _takvin_setting,
    calculator,
    calculator_quote,
    financial_summary,
    mellat_balance,
    tailor_balance,
)
from .dateutils import format_jalali, parse_jalali_date
from .excel_views import _int
from .finance_excel_v9 import digikala_receivable_total
from .material_flow import COLOR_LABELS
from .material_purchase_v13 import build_purchase_from_post, encode_purchase_note, purchase_summary
from .material_purchase_v14 import (
    apply_purchase_stock,
    create_purchase_ledger,
    ledger_for_payment,
    purchase_data_for_payment,
    reverse_purchase_stock,
)
from .models import (
    AccountEntry,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    MoneyMovement,
)

PREPAYMENT_PREFIX = "material-prepayment:"


def _current_jalali_month_range():
    today_j = jdatetime.date.fromgregorian(date=date.today())
    start_j = jdatetime.date(today_j.year, today_j.month, 1)
    if today_j.month == 12:
        next_j = jdatetime.date(today_j.year + 1, 1, 1)
    else:
        next_j = jdatetime.date(today_j.year, today_j.month + 1, 1)
    return start_j.togregorian(), next_j.togregorian(), f"{today_j.year}/{today_j.month:02d}"


def _norm(text):
    text = str(text or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _prepayment_title(payment_id):
    return f"{PREPAYMENT_PREFIX}{int(payment_id)}"


def _prepayment_ledger(payment):
    return MoneyMovement.objects.filter(
        kind=MoneyMovement.TRANSFER,
        title=_prepayment_title(payment.id),
    ).order_by("-id").first()


def _decode_prepayment(ledger):
    if not ledger:
        return None
    try:
        data = json.loads(ledger.note or "{}")
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _supplier_account_row(title, create=True):
    title = str(title or "").strip()[:160]
    if not title:
        return None
    wanted = _norm(title)
    rows = ExcelManualRow.objects.filter(section=ExcelManualRow.ACCOUNTS, active=True).order_by("sort_order", "id")
    for row in rows:
        if _norm(row.title) == wanted:
            return row
    if not create:
        return None
    max_order = rows.aggregate(v=Sum("sort_order"))["v"] or 0
    return ExcelManualRow.objects.create(
        section=ExcelManualRow.ACCOUNTS,
        title=title,
        amount=0,
        sort_order=int(max_order) + 1,
        note="ساخته‌شده خودکار از پیش‌پرداخت مواد اولیه",
    )


def _supplier_title(payee, note):
    note = str(note or "").strip()
    if not note:
        label = "پارچه فروش حسینی" if payee == "fabric" else "کش فروش"
        raise ValueError(f"برای پیش‌پرداخت اسم فروشنده را در توضیح بنویس؛ مثلاً «{label}».")
    return note[:160]


def _create_prepayment_ledger(payment, supplier_title):
    row = _supplier_account_row(supplier_title, create=True)
    if row is None:
        raise ValueError("حساب فروشنده ساخته نشد.")
    row.amount = int(row.amount or 0) + int(payment.amount or 0)
    row.save(update_fields=["amount", "updated_at"])
    data = {"v": 21, "row_id": row.id, "title": row.title, "payee": payment.payee}
    MoneyMovement.objects.filter(kind=MoneyMovement.TRANSFER, title=_prepayment_title(payment.id)).delete()
    MoneyMovement.objects.create(
        date=payment.date,
        kind=MoneyMovement.TRANSFER,
        amount=int(payment.amount or 0),
        title=_prepayment_title(payment.id),
        affects_capital=False,
        note=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
    )
    return row


def _reverse_prepayment(payment):
    ledger = _prepayment_ledger(payment)
    data = _decode_prepayment(ledger)
    if not ledger or not data:
        raise ValueError("Ledger پیش‌پرداخت این پرداخت پیدا نشد؛ حذف/ویرایش برای حفظ سرمایه متوقف شد.")
    row = None
    row_id = data.get("row_id")
    if row_id:
        row = ExcelManualRow.objects.select_for_update().filter(id=row_id, section=ExcelManualRow.ACCOUNTS).first()
    if row is None:
        row = _supplier_account_row(data.get("title"), create=False)
        if row:
            row = ExcelManualRow.objects.select_for_update().get(pk=row.pk)
    if row is None:
        raise ValueError("ردیف ریزحساب فروشنده برای Reverse پیش‌پرداخت پیدا نشد.")
    amount = int(payment.amount or 0)
    if int(row.amount or 0) < amount:
        raise ValueError(
            f"مانده ریزحساب «{row.title}» از مبلغ این پیش‌پرداخت کمتر است؛ عملیات متوقف شد تا سرمایه خراب نشود."
        )
    row.amount = int(row.amount or 0) - amount
    row.save(update_fields=["amount", "updated_at"])
    ledger.delete()


def _has_material_details(payee, post):
    if payee == "fabric":
        return any(str(post.get(k) or "").strip() for k in ("fabric_qty", "fabric_price", "fabric_name"))
    if payee == "elastic":
        return any(
            str(post.get(k) or "").strip()
            for k in ("elastic16_qty", "elastic16_price", "elastic25_qty", "elastic25_price")
        )
    return False


def _parse_payment_post(post):
    payment_date = parse_jalali_date(post.get("date") or format_jalali(date.today()))
    payee = (post.get("payee") or "").strip()
    note = (post.get("note") or "").strip()[:250]
    if payee not in PAYEE_LABELS:
        raise ValueError("دریافت‌کننده پرداخت معتبر نیست.")

    purchase_data = None
    prepayment_title = None
    if payee in MATERIAL_PAYEES and _has_material_details(payee, post):
        amount, purchase_data = build_purchase_from_post(payee, post)
    else:
        amount = _int(post.get("amount"))
        if amount <= 0:
            raise ValueError("مبلغ پرداخت باید بیشتر از صفر باشد.")
        if payee in MATERIAL_PAYEES:
            prepayment_title = _supplier_title(payee, note)
    return payment_date, payee, int(amount), note, purchase_data, prepayment_title


def _apply_payment_effects(payment, purchase_data=None, prepayment_title=None):
    mellat = _mellat_row(create=True)
    mellat.amount = int(mellat.amount or 0) - int(payment.amount or 0)
    mellat.save(update_fields=["amount", "updated_at"])

    if purchase_data:
        apply_purchase_stock(payment, purchase_data)
        create_purchase_ledger(payment, purchase_data)
    elif prepayment_title:
        _create_prepayment_ledger(payment, prepayment_title)
    elif payment.payee == "tailor":
        tailor = _tailor_row(create=True)
        tailor.amount = int(tailor.amount or 0) + int(payment.amount or 0)
        tailor.save(update_fields=["amount", "updated_at"])
    elif payment.payee == "takvin":
        debt = _takvin_setting()
        debt.value = max(0, int(debt.value or 0) - int(payment.amount or 0))
        debt.save(update_fields=["value", "updated_at"])


def _reverse_payment_effects(payment):
    purchase_data = purchase_data_for_payment(payment) if payment.payee in MATERIAL_PAYEES else None
    prep = _prepayment_ledger(payment)

    if purchase_data:
        reverse_purchase_stock(payment, purchase_data)
        ledger = ledger_for_payment(payment)
        if ledger:
            ledger.delete()
    elif prep:
        _reverse_prepayment(payment)
    elif payment.payee in MATERIAL_PAYEES:
        raise ValueError(
            "این پرداخت مواد اولیه است ولی نه Ledger خرید دارد نه Ledger پیش‌پرداخت؛ عملیات برای جلوگیری از خرابی سرمایه متوقف شد."
        )
    elif payment.payee == "tailor":
        tailor = _tailor_row(create=True)
        tailor.amount = int(tailor.amount or 0) - int(payment.amount or 0)
        tailor.save(update_fields=["amount", "updated_at"])
    elif payment.payee == "takvin":
        debt = _takvin_setting()
        debt.value = int(debt.value or 0) + int(payment.amount or 0)
        debt.save(update_fields=["value", "updated_at"])

    mellat = _mellat_row(create=True)
    mellat.amount = int(mellat.amount or 0) + int(payment.amount or 0)
    mellat.save(update_fields=["amount", "updated_at"])


def _payment_rows():
    rows = list(BusinessPayment.objects.all()[:100])
    for row in rows:
        row.payee_label = PAYEE_LABELS.get(row.payee, row.payee)
        purchase = purchase_data_for_payment(row) if row.payee in MATERIAL_PAYEES else None
        prep_data = _decode_prepayment(_prepayment_ledger(row))
        row.is_material_purchase = bool(purchase)
        row.is_material_prepayment = bool(prep_data)
        row.material_summary = purchase_summary(purchase).replace(",", "٬") if purchase else ""
        row.display_note = (purchase or {}).get("n", "") if purchase else row.note
        row.prepayment_account = (prep_data or {}).get("title", "")
        row.purchase_data = purchase or {}
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
        "core/payments_v21.html",
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
        payment_date, payee, amount, note, purchase_data, prep_title = _parse_payment_post(request.POST)
        with transaction.atomic():
            payment = BusinessPayment.objects.create(
                date=payment_date,
                payee=payee,
                amount=amount,
                note=encode_purchase_note(purchase_data) if purchase_data else note,
            )
            _apply_payment_effects(payment, purchase_data, prep_title)
        if purchase_data:
            messages.success(request, "خرید مواد ثبت شد؛ پول ملت به موجودی مواد اولیه تبدیل شد.")
        elif prep_title:
            messages.success(request, f"پیش‌پرداخت ثبت شد و {amount:,} تومان به ریزحساب «{prep_title}» اضافه شد.")
        else:
            messages.success(request, f"پرداخت به {PAYEE_LABELS[payee]} ثبت شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=payments")


@login_required
@require_POST
def payment_update(request, payment_id):
    try:
        with transaction.atomic():
            payment = get_object_or_404(BusinessPayment.objects.select_for_update(), id=payment_id)
            _reverse_payment_effects(payment)
            payment_date, payee, amount, note, purchase_data, prep_title = _parse_payment_post(request.POST)
            payment.date = payment_date
            payment.payee = payee
            payment.amount = amount
            payment.note = encode_purchase_note(purchase_data) if purchase_data else note
            payment.save(update_fields=["date", "payee", "amount", "note"])
            _apply_payment_effects(payment, purchase_data, prep_title)
        messages.success(request, "پرداخت ویرایش شد و تمام اثرهای مالی/موجودی آن دوباره به‌صورت اتمیک اعمال شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=payments")


@login_required
@require_POST
def payment_delete(request, payment_id):
    try:
        with transaction.atomic():
            payment = get_object_or_404(BusinessPayment.objects.select_for_update(), id=payment_id)
            _reverse_payment_effects(payment)
            payment.delete()
        messages.success(request, "پرداخت حذف شد و تمام اثر مالی/موجودی آن برگشت.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=payments")


def _sync_receipt_ledger(receipt):
    account = _digikala_account()
    AccountEntry.objects.filter(account=account, reference=f"receipt:{receipt.id}:digikala").delete()
    AccountEntry.objects.create(
        date=receipt.date,
        account=account,
        delta=-int(receipt.amount or 0),
        title="دریافت از دیجی‌کالا",
        reference=f"receipt:{receipt.id}:digikala",
        entry_type="receipt",
        note=receipt.note,
    )


@login_required
@require_POST
def receipt_add(request):
    try:
        receipt_date = parse_jalali_date(request.POST.get("date") or format_jalali(date.today()))
        amount = _int(request.POST.get("amount"))
        note = (request.POST.get("note") or "").strip()[:250]
        if amount <= 0:
            raise ValueError("مبلغ دریافتی باید بیشتر از صفر باشد.")
        if amount > digikala_receivable_total():
            raise ValueError("مبلغ دریافتی نمی‌تواند بیشتر از طلب فعلی دیجی‌کالا باشد.")
        with transaction.atomic():
            receipt = DigikalaSettlement.objects.create(date=receipt_date, amount=amount, note=note)
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) + amount
            mellat.save(update_fields=["amount", "updated_at"])
            _sync_receipt_ledger(receipt)
        messages.success(request, "دریافتی ثبت شد؛ طلب دیجی کم و ملت زیاد شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=receipts")


@login_required
@require_POST
def receipt_update(request, receipt_id):
    try:
        with transaction.atomic():
            receipt = get_object_or_404(DigikalaSettlement.objects.select_for_update(), id=receipt_id)
            old_amount = int(receipt.amount or 0)
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) - old_amount
            mellat.save(update_fields=["amount", "updated_at"])
            account = _digikala_account()
            deleted, _ = AccountEntry.objects.filter(
                account=account,
                reference=f"receipt:{receipt.id}:digikala",
                entry_type="receipt",
            ).delete()
            if not deleted:
                raise ValueError("Ledger دریافتی قدیمی پیدا نشد؛ ویرایش متوقف شد.")

            new_date = parse_jalali_date(request.POST.get("date") or format_jalali(receipt.date))
            new_amount = _int(request.POST.get("amount"))
            new_note = (request.POST.get("note") or "").strip()[:250]
            if new_amount <= 0:
                raise ValueError("مبلغ دریافتی باید بیشتر از صفر باشد.")
            if new_amount > digikala_receivable_total():
                raise ValueError("مبلغ جدید از طلب دیجی‌کالای قابل دریافت بیشتر است.")

            receipt.date = new_date
            receipt.amount = new_amount
            receipt.note = new_note
            receipt.save(update_fields=["date", "amount", "note"])
            mellat.amount = int(mellat.amount or 0) + new_amount
            mellat.save(update_fields=["amount", "updated_at"])
            _sync_receipt_ledger(receipt)
        messages.success(request, "دریافتی ویرایش شد و دو طرف ملت/طلب دیجی دوباره بالانس شدند.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("/payments/?section=receipts")


@login_required
@require_POST
def receipt_delete(request, receipt_id):
    try:
        with transaction.atomic():
            receipt = get_object_or_404(DigikalaSettlement.objects.select_for_update(), id=receipt_id)
            mellat = _mellat_row(create=True)
            mellat.amount = int(mellat.amount or 0) - int(receipt.amount or 0)
            mellat.save(update_fields=["amount", "updated_at"])
            account = _digikala_account()
            deleted, _ = AccountEntry.objects.filter(
                account=account,
                reference=f"receipt:{receipt.id}:digikala",
                entry_type="receipt",
            ).delete()
            if not deleted:
                raise ValueError("Ledger طلب دیجی برای این دریافتی پیدا نشد؛ حذف متوقف شد.")
            receipt.delete()
        messages.success(request, "دریافتی حذف شد؛ ملت کم و طلب دیجی به همان مبلغ برگشت.")
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
