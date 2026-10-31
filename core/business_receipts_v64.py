from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .business_tools_v14 import _digikala_account, _mellat_row
from .dateutils import format_jalali, parse_jalali_date
from .dia_gallery_v45 import _dia_account, dia_gallery_receivable_total
from .excel_views import _int
from .finance_excel_v9 import digikala_receivable_total
from .models import AccountEntry, DigikalaSettlement


SOURCE_DIGIKALA = DigikalaSettlement.SOURCE_DIGIKALA
SOURCE_DIA_GALLERY = DigikalaSettlement.SOURCE_DIA_GALLERY
SOURCE_CHOICES = tuple(DigikalaSettlement.SOURCE_CHOICES)
SOURCE_LABELS = dict(SOURCE_CHOICES)


def normalize_source(value):
    value = str(value or SOURCE_DIGIKALA).strip()
    if value not in SOURCE_LABELS:
        raise ValueError("منبع دریافتی معتبر نیست.")
    return value


def source_receivable(source):
    source = normalize_source(source)
    if source == SOURCE_DIGIKALA:
        return int(digikala_receivable_total())
    return int(dia_gallery_receivable_total())


def _source_account(source, *, create=False):
    source = normalize_source(source)
    if source == SOURCE_DIGIKALA:
        return _digikala_account()
    return _dia_account(create=create)


def _reference(receipt, source=None):
    source = normalize_source(source or receipt.source)
    suffix = "digikala" if source == SOURCE_DIGIKALA else "dia-gallery"
    return f"receipt:{receipt.id}:{suffix}"


def _sync_receipt_ledger(receipt):
    source = normalize_source(receipt.source)
    account = _source_account(source, create=True)
    reference = _reference(receipt, source)
    AccountEntry.objects.filter(
        account=account,
        reference=reference,
        entry_type="receipt",
    ).delete()
    AccountEntry.objects.create(
        date=receipt.date,
        account=account,
        delta=-int(receipt.amount or 0),
        title=f"دریافت از {SOURCE_LABELS[source]}",
        reference=reference,
        entry_type="receipt",
        note=receipt.note,
    )


def apply_receipt(receipt):
    source = normalize_source(receipt.source)
    amount = int(receipt.amount or 0)
    if amount <= 0:
        raise ValueError("مبلغ دریافتی باید بیشتر از صفر باشد.")
    available = source_receivable(source)
    if amount > available:
        raise ValueError(
            f"مبلغ دریافتی نمی‌تواند بیشتر از طلب فعلی {SOURCE_LABELS[source]} باشد."
        )

    mellat = _mellat_row(create=True)
    mellat.amount = int(mellat.amount or 0) + amount
    mellat.save(update_fields=["amount", "updated_at"])
    _sync_receipt_ledger(receipt)


def reverse_receipt(receipt):
    source = normalize_source(receipt.source)
    amount = int(receipt.amount or 0)

    mellat = _mellat_row(create=True)
    mellat.amount = int(mellat.amount or 0) - amount
    mellat.save(update_fields=["amount", "updated_at"])

    account = _source_account(source, create=False)
    if account is None:
        raise ValueError(
            f"حساب {SOURCE_LABELS[source]} برای Reverse این دریافتی پیدا نشد."
        )
    deleted, _ = AccountEntry.objects.filter(
        account=account,
        reference=_reference(receipt, source),
        entry_type="receipt",
    ).delete()
    if not deleted:
        raise ValueError(
            f"Ledger دریافتی {SOURCE_LABELS[source]} پیدا نشد؛ عملیات متوقف شد."
        )


def receipt_rows():
    rows = list(DigikalaSettlement.objects.all()[:100])
    for row in rows:
        row.source = normalize_source(getattr(row, "source", SOURCE_DIGIKALA))
        row.source_label = SOURCE_LABELS[row.source]
    return rows


def _parse_post(post, *, default_source=SOURCE_DIGIKALA, default_date=None):
    source = normalize_source(post.get("source") or default_source)
    receipt_date = parse_jalali_date(
        post.get("date")
        or format_jalali(default_date or date.today())
    )
    amount = _int(post.get("amount"))
    note = (post.get("note") or "").strip()[:250]
    if amount <= 0:
        raise ValueError("مبلغ دریافتی باید بیشتر از صفر باشد.")
    return {
        "source": source,
        "date": receipt_date,
        "amount": int(amount),
        "note": note,
    }


@login_required
@require_POST
def receipt_add(request):
    try:
        parsed = _parse_post(request.POST)
        with transaction.atomic():
            receipt = DigikalaSettlement.objects.create(
                source=parsed["source"],
                date=parsed["date"],
                amount=parsed["amount"],
                note=parsed["note"],
            )
            apply_receipt(receipt)
        messages.success(
            request,
            f"دریافت از {SOURCE_LABELS[parsed['source']]} ثبت شد؛ "
            "طلب همان منبع کم و موجودی ملت به همان مبلغ زیاد شد.",
        )
    except Exception as exc:
        messages.error(request, f"دریافتی ثبت نشد و کل عملیات برگشت: {exc}")
    return redirect("/payments/?section=receipts")


@login_required
@require_POST
def receipt_update(request, receipt_id):
    try:
        with transaction.atomic():
            receipt = get_object_or_404(
                DigikalaSettlement.objects.select_for_update(),
                id=receipt_id,
            )
            old_source = normalize_source(receipt.source)
            reverse_receipt(receipt)

            parsed = _parse_post(
                request.POST,
                default_source=old_source,
                default_date=receipt.date,
            )
            receipt.source = parsed["source"]
            receipt.date = parsed["date"]
            receipt.amount = parsed["amount"]
            receipt.note = parsed["note"]
            receipt.save(update_fields=["source", "date", "amount", "note"])
            apply_receipt(receipt)

        messages.success(
            request,
            "دریافتی ویرایش شد؛ ملت و طلب منبع انتخاب‌شده دوباره به‌صورت اتمیک همگام شدند.",
        )
    except Exception as exc:
        messages.error(request, f"ویرایش دریافتی انجام نشد و کل عملیات برگشت: {exc}")
    return redirect("/payments/?section=receipts")


@login_required
@require_POST
def receipt_delete(request, receipt_id):
    try:
        with transaction.atomic():
            receipt = get_object_or_404(
                DigikalaSettlement.objects.select_for_update(),
                id=receipt_id,
            )
            source_label = SOURCE_LABELS[normalize_source(receipt.source)]
            reverse_receipt(receipt)
            receipt.delete()
        messages.success(
            request,
            f"دریافت از {source_label} حذف شد؛ مبلغ از ملت کم و طلب همان منبع برگشت.",
        )
    except Exception as exc:
        messages.error(request, f"حذف دریافتی انجام نشد: {exc}")
    return redirect("/payments/?section=receipts")
