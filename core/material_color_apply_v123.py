"""Atomic per-color raw-material application with shared elastic attribution.

Existing MaterialReportConsumption remains the authoritative summed consumption.
Color allocations only identify each model's contribution to that summed row.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from . import material_report_v23 as v23
from .material_flow import _consume_rows, q
from .models import MaterialReportColorUse, MaterialReportConsumption


def _contributions(block, model_key):
    if model_key not in v23._active_model_keys(block):
        raise ValueError("این رنگ در صورت مواد اولیه وجود ندارد.")
    return {
        key: q(amount)
        for key, amount in v23.desired_consumption(block, keys=[model_key]).items()
        if q(amount) > 0
    }


def _summed_contributions(block):
    output = defaultdict(lambda: Decimal("0"))
    allocations = []
    for model_key in v23._active_model_keys(block):
        for (kind, material_key, variant), amount in _contributions(block, model_key).items():
            output[(kind, material_key, variant)] += amount
            allocations.append((model_key, kind, material_key, variant, amount))
    return dict(output), allocations


def _map_existing(block):
    return {
        (row.kind, row.material_key, row.variant): q(row.quantity)
        for row in MaterialReportConsumption.objects.select_for_update().filter(block=block)
    }


def _allocation_totals(rows):
    totals = defaultdict(lambda: Decimal("0"))
    for row in rows:
        totals[(row.kind, row.material_key, row.variant)] += q(row.quantity)
    return dict(totals)


def _assert_same(actual, expected):
    if {
        key: q(value) for key, value in actual.items() if q(value)
    } != {
        key: q(value) for key, value in expected.items() if q(value)
    }:
        raise ValueError(
            "ریز مصرف رنگ‌ها با مصرف قدیمی این صورت یکسان نیست؛ "
            "برای جلوگیری از کم‌شدن دوباره پارچه یا کش، اعمال تک‌رنگ متوقف شد. "
            "ابتدا مقادیر ذخیره‌شده و سوابق اعمال را بررسی کن."
        )


def _initialize_attributions(block):
    existing = _map_existing(block)
    allocations = list(
        MaterialReportColorUse.objects.select_for_update().filter(block=block)
    )
    if allocations:
        _assert_same(_allocation_totals(allocations), existing)
        return allocations
    if not existing:
        return []
    # Existing V122/V121 fully-applied sheets have only global consumption.
    # Recover attribution without touching physical stock, IF saved inputs
    # still exactly reconcile. Otherwise refuse rather than guess.
    summed, derived = _summed_contributions(block)
    _assert_same(summed, existing)
    MaterialReportColorUse.objects.bulk_create([
        MaterialReportColorUse(
            block=block, model_key=model_key, kind=kind,
            material_key=material_key, variant=variant, quantity=amount,
        )
        for model_key, kind, material_key, variant, amount in derived
    ])
    return list(MaterialReportColorUse.objects.select_for_update().filter(block=block))


@transaction.atomic
def sync_one_color(block, model_key):
    """Sync ONLY this color's fabric + 16/25 elastic, preserving other colors."""
    allocations = _initialize_attributions(block)
    old_global = _map_existing(block)
    old_color = {
        (row.kind, row.material_key, row.variant): q(row.quantity)
        for row in allocations if row.model_key == model_key
    }
    new_color = _contributions(block, model_key)
    affected = sorted(set(old_color) | set(new_color))
    for key in affected:
        old = old_global.get(key, Decimal("0"))
        updated = old - old_color.get(key, Decimal("0")) + new_color.get(key, Decimal("0"))
        if updated < 0:
            raise ValueError("موجودی مصرف مواد رنگ قابل تفکیک نیست.")
        delta = updated - old
        if delta:
            _consume_rows(key[0], key[1], key[2], delta)
        row = MaterialReportConsumption.objects.select_for_update().filter(
            block=block, kind=key[0], material_key=key[1], variant=key[2],
        ).first()
        if updated == 0:
            if row:
                row.delete()
        elif row:
            row.quantity = updated
            row.save(update_fields=["quantity"])
        else:
            MaterialReportConsumption.objects.create(
                block=block, kind=key[0], material_key=key[1],
                variant=key[2], quantity=updated,
            )
    MaterialReportColorUse.objects.filter(block=block, model_key=model_key).delete()
    MaterialReportColorUse.objects.bulk_create([
        MaterialReportColorUse(
            block=block, model_key=model_key, kind=kind,
            material_key=source, variant=variant, quantity=amount,
        )
        for (kind, source, variant), amount in sorted(new_color.items())
    ])
    return {"model_key": model_key, "affected": len(affected)}


@transaction.atomic
def sync_all_colors(block):
    """Old all-colors action preserved, with attribution updated atomically."""
    v23.sync_report_consumption(block)
    _, data = _summed_contributions(block)
    # Exact attribution of the same global target after the legacy sync.
    MaterialReportColorUse.objects.filter(block=block).delete()
    MaterialReportColorUse.objects.bulk_create([
        MaterialReportColorUse(
            block=block, model_key=model_key, kind=kind,
            material_key=source, variant=variant, quantity=amount,
        )
        for model_key, kind, source, variant, amount in data
    ])
    _assert_same(
        _allocation_totals(MaterialReportColorUse.objects.filter(block=block)),
        _map_existing(block),
    )
