import re

from django.db import transaction

from .models import BusinessPayment, ExcelManualRow


SOURCE_MELAT = BusinessPayment.SOURCE_MELAT
SOURCE_MOFID = BusinessPayment.SOURCE_MOFID
SOURCE_CHOICES = tuple(BusinessPayment.SOURCE_CHOICES)
SOURCE_LABELS = dict(SOURCE_CHOICES)


def normalize_source(value):
    value = str(value or SOURCE_MELAT).strip().lower()
    if value not in SOURCE_LABELS:
        raise ValueError("حساب مبدا پرداخت معتبر نیست.")
    return value


def _norm(text):
    text = str(text or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _source_title(source):
    source = normalize_source(source)
    return "ملت" if source == SOURCE_MELAT else "مفید"


def source_row(source, create=True, for_update=False):
    source = normalize_source(source)
    wanted = _norm(_source_title(source))
    qs = ExcelManualRow.objects.filter(
        section=ExcelManualRow.ACCOUNTS,
        active=True,
    ).order_by("sort_order", "id")
    if for_update:
        qs = qs.select_for_update()

    exact = None
    partial = None
    for row in qs:
        normalized = _norm(row.title)
        if normalized == wanted:
            exact = row
            break
        if wanted in normalized and partial is None:
            partial = row
    row = exact or partial
    if row or not create:
        return row

    order = (
        ExcelManualRow.objects.filter(section=ExcelManualRow.ACCOUNTS)
        .order_by()
        .values_list("sort_order", flat=True)
    )
    max_order = max([int(x or 0) for x in order], default=0)
    row = ExcelManualRow.objects.create(
        section=ExcelManualRow.ACCOUNTS,
        title=_source_title(source),
        amount=0,
        sort_order=max_order + 1,
        note="حساب مبدا پرداخت",
        active=True,
    )
    if for_update:
        row = ExcelManualRow.objects.select_for_update().get(pk=row.pk)
    return row


def source_balance(source):
    row = source_row(source, create=False)
    return int(row.amount or 0) if row else 0


@transaction.atomic
def adjust_source_account(source, delta):
    source = normalize_source(source)
    row = source_row(source, create=True, for_update=True)
    row.amount = int(row.amount or 0) + int(delta or 0)
    row.save(update_fields=["amount", "updated_at"])
    return row
