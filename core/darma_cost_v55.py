from datetime import date

from django.db import transaction

from .models import AppSetting, DiaGallerySale, SaleSnapshot


DEFAULT_DARMA_UNIT_COST = 61_000
BASELINE_EFFECTIVE_FROM = date(2021, 3, 21)  # 1400/01/01
RULE_PREFIX = "darma_cost_rule_"
LEGACY_FALLBACK_KEY = "darma_accounting_unit_cost"
DARMA_BACKED_BRANDS = ("دارما", "انبارش")


def _clean_int(value, default=0):
    try:
        return max(0, int(str(value if value not in (None, "") else default).replace("٬", "").replace(",", "").replace(" ", "")))
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


def list_darma_cost_rules():
    rows = []
    for obj in AppSetting.objects.filter(key__startswith=RULE_PREFIX).order_by("key"):
        effective_from = _parse_rule_date(obj.key)
        unit_cost = _clean_int(obj.value)
        if effective_from and unit_cost > 0:
            rows.append({
                "id": obj.id,
                "key": obj.key,
                "effective_from": effective_from,
                "unit_cost": unit_cost,
                "is_baseline": effective_from == BASELINE_EFFECTIVE_FROM,
            })
    rows.sort(key=lambda row: (row["effective_from"], row["id"]), reverse=True)
    return rows


def darma_cost_for(on_date=None):
    """Canonical accounting cost for one Darma short on a given date."""
    on_date = on_date or date.today()
    best = None
    for row in list_darma_cost_rules():
        if row["effective_from"] <= on_date:
            if best is None or row["effective_from"] > best["effective_from"]:
                best = row
    if best:
        return int(best["unit_cost"])

    legacy = AppSetting.objects.filter(key=LEGACY_FALLBACK_KEY).values_list("value", flat=True).first()
    return _clean_int(legacy, DEFAULT_DARMA_UNIT_COST) or DEFAULT_DARMA_UNIT_COST


def set_darma_cost_rule(effective_from, unit_cost):
    """Write one rule only; used by baseline seed and transactional regressions."""
    if not isinstance(effective_from, date):
        raise ValueError("تاریخ شروع بهای تمام‌شده دارما معتبر نیست.")
    unit_cost = _clean_int(unit_cost)
    if unit_cost <= 0:
        raise ValueError("بهای تمام‌شده هر شورت دارما باید بیشتر از صفر باشد.")
    obj, _ = AppSetting.objects.update_or_create(
        key=_rule_key(effective_from),
        defaults={
            "value": str(unit_cost),
            "label": f"بهای تمام‌شده دارما از {effective_from.isoformat()}",
        },
    )
    return obj


def reprice_darma_backed_rows_from(effective_from):
    """Re-evaluate existing sale-date cost snapshots from one effective date.

    This changes COGS only. It never changes quantity, sale price, Digikala fee,
    receivables, inventory movements or account entries. Missing SaleSnapshots are
    intentionally left missing because `sale_line_metrics()` has the same canonical
    Darma fallback; creating one here could unnecessarily freeze unrelated fields.
    """
    snapshot_updates = 0
    snapshots = (
        SaleSnapshot.objects.filter(
            sale_line__day__date__gte=effective_from,
            sale_line__quantity__gt=0,
            sale_line__product_size__product__brand__name__in=DARMA_BACKED_BRANDS,
        )
        .select_related("sale_line__day")
        .order_by("sale_line__day__date", "id")
    )
    for snap in snapshots:
        target = int(darma_cost_for(snap.sale_line.day.date))
        if int(snap.unit_cost or 0) != target:
            snap.unit_cost = target
            snap.save(update_fields=["unit_cost", "updated_at"])
            snapshot_updates += 1

    dia_updates = 0
    dia_rows = (
        DiaGallerySale.objects.filter(day__date__gte=effective_from, quantity__gt=0)
        .select_related("day")
        .order_by("day__date", "id")
    )
    for row in dia_rows:
        target = int(darma_cost_for(row.day.date))
        if int(row.unit_cost or 0) != target:
            row.unit_cost = target
            row.save(update_fields=["unit_cost", "updated_at"])
            dia_updates += 1

    return {
        "sale_snapshots": snapshot_updates,
        "dia_rows": dia_updates,
    }


@transaction.atomic
def apply_darma_cost_rule(effective_from, unit_cost):
    """Save a user rule and make existing reports from that date onward obey it."""
    if effective_from <= BASELINE_EFFECTIVE_FROM:
        raise ValueError(
            "نرخ پایه دارما از 1400/01/01 برابر 61,000 تومان و قفل است؛ "
            "برای تغییر بهای تمام‌شده یک تاریخ بعد از 1400/01/01 ثبت کن."
        )
    obj = set_darma_cost_rule(effective_from, unit_cost)
    updated = reprice_darma_backed_rows_from(effective_from)
    return obj, updated


@transaction.atomic
def delete_darma_cost_rule(effective_from):
    """Delete a non-baseline rule and recalculate later snapshots from remaining rules."""
    if effective_from == BASELINE_EFFECTIVE_FROM:
        raise ValueError("نرخ پایه 61,000 تومان دارما قابل حذف نیست؛ برای تغییر هزینه، یک نرخ جدید با تاریخ شروع ثبت کن.")
    deleted = AppSetting.objects.filter(key=_rule_key(effective_from)).delete()[0]
    updated = {"sale_snapshots": 0, "dia_rows": 0}
    if deleted:
        updated = reprice_darma_backed_rows_from(effective_from)
    return deleted, updated


def ensure_darma_cost_baseline():
    """Seed the user's confirmed 61,000 baseline without rewriting history."""
    key = _rule_key(BASELINE_EFFECTIVE_FROM)
    obj = AppSetting.objects.filter(key=key).first()
    if obj is None:
        return set_darma_cost_rule(BASELINE_EFFECTIVE_FROM, DEFAULT_DARMA_UNIT_COST)
    return obj
