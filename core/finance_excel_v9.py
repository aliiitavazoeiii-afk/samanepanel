from django.db import transaction
from django.db.models import Sum

from .finance import sale_line_metrics
from .models import Account, AccountEntry, ExcelManualSetting, SaleLine


def _digikala_account():
    account, _ = Account.objects.get_or_create(
        key=Account.DIGIKALA,
        defaults={"title": "دیجی‌کالا", "opening_balance": 0},
    )
    return account


def digikala_base_receivable():
    obj, _ = ExcelManualSetting.objects.get_or_create(
        key="digikala_receivable",
        defaults={"label": "طلب پایه دیجی‌کالا", "value": 0},
    )
    return int(obj.value or 0)


def digikala_ledger_total():
    account = _digikala_account()
    value = account.entries.filter(entry_type__in=["sale", "receipt"]).aggregate(v=Sum("delta"))["v"] or 0
    return int(value)


def digikala_receivable_total():
    return digikala_base_receivable() + digikala_ledger_total()


def sale_receivable_value(line: SaleLine):
    if int(line.quantity or 0) <= 0:
        return 0
    metrics = sale_line_metrics(line)
    return int(metrics["gross"] or 0) - int(metrics["digikala_fee"] or 0)


@transaction.atomic
def sync_sale_receivable(line: SaleLine):
    line = SaleLine.objects.select_related("day", "product_size__product", "product_size__size").get(pk=line.pk)
    account = _digikala_account()
    reference = f"sale:{line.id}:digikala"
    value = sale_receivable_value(line)
    AccountEntry.objects.filter(account=account, reference=reference).delete()
    if value:
        AccountEntry.objects.create(
            date=line.day.date,
            account=account,
            delta=value,
            title=f"طلب فروش {line.product_size.product.code} / {line.product_size.size.name}",
            reference=reference,
            entry_type="sale",
            note="ثبت خودکار فروش روزانه",
        )
    return value
