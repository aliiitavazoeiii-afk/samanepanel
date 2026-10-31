from datetime import date

from django.db import transaction

from .models import AppSetting, SaleSnapshot


DEFAULT_NOVANI_UNIT_COST = 61_000
BASELINE_EFFECTIVE_FROM = date(2021, 3, 21)  # 1400/01/01
RULE_PREFIX = "novani_cost_rule_"
NOVANI_BRAND = "Novani"


def _clean_int(value, default=0):
    try:
        return max(
            0,
            int(
                str(value if value not in (None, "") else default)
                .replace("٬", "")
                .replace(",", "")
                .replace(" ", "")
            ),
        )
    except (TypeError, ValueError):
        return int(default or 0)


def _rule_key(effective_from):
    return f"{RULE_PREFIX}{effective_from.isoformat()}"


def _parse_rule_date(key):
    if not str(key).startswith(RULE_PREFIX):
        return None
    try:
        return date.fromisoformat(str(key)[len(RULE_PREFIX):])
    except (TypeError, ValueError):
        return None


def list_novani_cost_rules():
    rows = []
    for obj in AppSetting.objects.filter(key__startswith=RULE_PREFIX).order_by("key"):
        effective_from = _parse_rule_date(obj.key)
        unit_cost = _clean_int(obj.value)
        if effective_from and unit_cost > 0:
            rows.append(
                {
                    "id": obj.id,
                    "key": obj.key,
                    "effective_from": effective_from,
                    "unit_cost": unit_cost,
                    "is_baseline": False,
                }
            )

    # The confirmed legacy Novani basis is 61,000. Keep it as an immutable
    # synthetic baseline so no migration/write is required merely to activate V59.
    rows.append(
        {
            "id": 0,
            "key": None,
            "effective_from": BASELINE_EFFECTIVE_FROM,
            "unit_cost": DEFAULT_NOVANI_UNIT_COST,
            "is_baseline": True,
        }
    )
    rows.sort(key=lambda row: (row["effective_from"], row["id"]), reverse=True)
    return rows


def novani_cost_for(on_date=None):
    """Canonical accounting cost for one Novani short on a given date."""
    on_date = on_date or date.today()
    best = None
    for row in list_novani_cost_rules():
        if row["effective_from"] <= on_date:
            if best is None or row["effective_from"] > best["effective_from"]:
                best = row
    return int(best["unit_cost"] if best else DEFAULT_NOVANI_UNIT_COST)


def set_novani_cost_rule(effective_from, unit_cost):
    if not isinstance(effective_from, date):
        raise ValueError("تاریخ شروع بهای تمام‌شده Novani معتبر نیست.")
    if effective_from <= BASELINE_EFFECTIVE_FROM:
        raise ValueError(
            "نرخ پایه Novani از 1400/01/01 برابر 61,000 تومان و قفل است؛ "
            "برای تغییر هزینه، تاریخ جدیدتری ثبت کن."
        )
    unit_cost = _clean_int(unit_cost)
    if unit_cost <= 0:
        raise ValueError("بهای تمام‌شده هر شورت Novani باید بیشتر از صفر باشد.")
    obj, _ = AppSetting.objects.update_or_create(
        key=_rule_key(effective_from),
        defaults={
            "value": str(unit_cost),
            "label": f"بهای تمام‌شده Novani از {effective_from.isoformat()}",
        },
    )
    return obj


def reprice_novani_rows_from(effective_from):
    """Refresh only Novani sale COGS snapshots from one effective date onward."""
    updates = 0
    snapshots = (
        SaleSnapshot.objects.filter(
            sale_line__day__date__gte=effective_from,
            sale_line__quantity__gt=0,
            sale_line__product_size__product__brand__name=NOVANI_BRAND,
        )
        .select_related("sale_line__day")
        .order_by("sale_line__day__date", "id")
    )
    for snap in snapshots:
        target = int(novani_cost_for(snap.sale_line.day.date))
        if int(snap.unit_cost or 0) != target:
            snap.unit_cost = target
            snap.save(update_fields=["unit_cost", "updated_at"])
            updates += 1
    return {"sale_snapshots": updates}


@transaction.atomic
def apply_novani_cost_rule(effective_from, unit_cost):
    obj = set_novani_cost_rule(effective_from, unit_cost)
    updated = reprice_novani_rows_from(effective_from)
    return obj, updated


@transaction.atomic
def delete_novani_cost_rule(effective_from):
    if effective_from <= BASELINE_EFFECTIVE_FROM:
        raise ValueError(
            "نرخ پایه 61,000 تومان Novani قابل حذف نیست؛ "
            "برای تغییر هزینه یک نرخ جدید با تاریخ شروع ثبت کن."
        )
    deleted = AppSetting.objects.filter(key=_rule_key(effective_from)).delete()[0]
    updated = {"sale_snapshots": 0}
    if deleted:
        updated = reprice_novani_rows_from(effective_from)
    return deleted, updated
