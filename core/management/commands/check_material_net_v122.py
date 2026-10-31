"""Read-only: verify current Jalali month + prior open carryover and NET deliveries."""
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand

from core import material_report_v92 as report
from core.models import MaterialReportBlock


class QueryValues(list):
    def distinct(self):
        return list(dict.fromkeys(self))


class FakeRelated:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)

    def filter(self, **conditions):
        items = self.rows
        for condition, value in conditions.items():
            if condition.endswith("__gt"):
                field = condition[:-4]
                items = [row for row in items if getattr(row, field) > value]
            else:
                items = [row for row in items if getattr(row, condition) == value]
        return FakeRelated(items)

    def values_list(self, field, flat=False):
        assert flat
        return QueryValues(getattr(row, field) for row in self.rows)


def sheet(pk, when, *, cut=0, delivered=0, applied=0, raw_applied=True,
          brand="دارما", color="pink", code=None):
    size_key = report.v23.DARMA_OUTPUT_SIZES[0][0]
    consumed = []
    if raw_applied:
        consumed.append(SimpleNamespace(
            kind=report.v23.FABRIC, material_key=color, quantity=Decimal("1")
        ))
    output = ([SimpleNamespace(model_key=color, size_key=size_key, quantity=applied)]
              if applied else [])
    return SimpleNamespace(
        pk=pk, date=when, brand=SimpleNamespace(name=brand),
        input_data={color: {
            "fabric_code": code or f"ROLL-{pk}",
            "cut": str(cut), "weight": "4.5",
        }},
        output_data={color: {size_key: str(delivered)}},
        output_applications=FakeRelated(output),
        stock_consumptions=FakeRelated(consumed),
    )


def synthetic_check():
    month = report._jalali_month_context(date(2026, 10, 18))
    current = date(2026, 10, 18)
    prev = date(2026, 9, 10)
    first = sheet(1, current, cut=750, delivered=998, applied=900)
    second = sheet(2, current, cut=750, delivered=540, applied=333)
    other_month_open = sheet(3, prev, cut=100, delivered=0, applied=0)
    other_month_fabric_open = sheet(4, prev, cut=40, delivered=40, applied=40,
                                    raw_applied=False)
    other_month_closed = sheet(5, prev, cut=80, delivered=80, applied=80)
    future = sheet(6, date(2026, 12, 1), cut=9, delivered=0, applied=0)
    blocks = [first, second, other_month_open, other_month_fabric_open,
              other_month_closed, future]
    initial = report._operational_month_blocks([first, second], month)
    progress = report._net_color_progress(initial)["pink"]
    if (
        progress["expected"], progress["delivered"], progress["applied"],
        progress["pending"], progress["surplus"],
    ) != (1500, 1538, 1233, 0, 38):
        raise RuntimeError(f"Pink two-roll net reconciliation failed: {progress}")

    # Monthly total must not let surplus pink cancel a shortage in white.
    white_short = sheet(8, current, cut=100, delivered=80, applied=80,
                        brand="دارما", color="white")
    independent = report._summarize_month_blocks(initial + [white_short])
    if (independent["minimum_delivery"], independent["delivered"],
            independent["pending"], independent["surplus"]) != (1600, 1618, 20, 38):
        raise RuntimeError(f"Different color deficit incorrectly netted: {independent}")

    month_summary = report._summarize_month_blocks(initial)
    if (month_summary["minimum_delivery"], month_summary["delivered"],
            month_summary["applied"], month_summary["pending"],
            month_summary["surplus"]) != (1500, 1538, 1233, 0, 38):
        raise RuntimeError(f"Monthly net reconciliation failed: {month_summary}")

    scoped = report._operational_month_blocks(blocks, month)
    if [row.pk for row in scoped] != [1, 2, 3, 4]:
        raise RuntimeError(f"Old open sheets not correctly carried: {[x.pk for x in scoped]}")
    scoped_summary = report._summarize_month_blocks(scoped)
    if (scoped_summary["minimum_delivery"], scoped_summary["delivered"],
            scoped_summary["pending"], scoped_summary["surplus"]) != (1640, 1578, 62, 0):
        raise RuntimeError(f"Carryover net mismatch: {scoped_summary}")
    # One complete roll with *unapplied fabric* must remain visible;
    # a completed and fully applied historical roll must be archived.
    assert report._block_operational_status(other_month_fabric_open)
    assert not report._block_operational_status(other_month_closed)
    assert not report._fabric_not_applied(other_month_closed, "pink")
    # Same total delivered/applied can still have wrong per-size allocations.
    size_s, size_m = [name for name, _ in report.v23.DARMA_OUTPUT_SIZES[:2]]
    swapped = sheet(7, prev, cut=5, delivered=5, applied=5)
    swapped.output_data["pink"] = {size_s: "5", size_m: "0"}
    swapped.output_applications = FakeRelated([
        SimpleNamespace(model_key="pink", size_key=size_m, quantity=5)
    ])
    assert report._color_delivery_unsynced(swapped, "pink")
    assert report._block_operational_status(swapped)



class Command(BaseCommand):
    help = "Audit net 2-roll delivery and Jalali carryover logic, read-only (also reports live pink rows)."

    def handle(self, *args, **kwargs):
        synthetic_check()
        source = (Path(settings.BASE_DIR) / "templates/core/material_report_v92.html").read_text(encoding="utf-8")
        for marker in (
            'data-current-month=', 'material-month-archive',
            'مازاد خالص', 'اعمال‌شده به موجودی',
            'تحویل ثبت‌شده', 'مانده خالص',
        ):
            if marker not in source:
                raise RuntimeError(f"V122 page regression: missing {marker}")
        blocks = list(
            MaterialReportBlock.objects.select_related("brand").prefetch_related(
                "output_applications", "stock_consumptions"
            ).all()
        )
        month = report._jalali_month_context()
        active = report._operational_month_blocks(blocks, month)
        values = report._net_color_progress(active)["pink"]
        summary = report._summarize_month_blocks(active)
        if values["pending"] * values["surplus"]:
            raise RuntimeError("Surplus and shortfall cannot both be positive")
        if (values["delivered"] - values["expected"] !=
                values["surplus"] - values["pending"]):
            raise RuntimeError("Live pink signed delivery mismatch")
        if summary["delivered"] - summary["minimum_delivery"] != (
                summary["surplus"] - summary["pending"]
        ):
            raise RuntimeError("Live month-level signed delivery mismatch")
        self.stdout.write(
            f"PERIOD={month['label']} "
            f"CARRYOVER={sum(x.date < month['start'] for x in active)} "
            f"ACTIVE_SHEETS={len(active)}"
        )
        self.stdout.write(
            f"PINK_NET expected_cut={values['expected']} "
            f"registered_delivery={values['delivered']} "
            f"stock_applied={values['applied']} "
            f"net_pending={values['pending']} "
            f"net_surplus={values['surplus']}"
        )
        pink = [x for x in active if x.brand.name == "دارما"
                and ((x.input_data or {}).get("pink") or
                     (x.output_data or {}).get("pink"))]
        for block in pink[:35]:
            values = (block.input_data or {}).get("pink") or {}
            received = report._registered_output_by_key(block).get("pink", 0)
            applied = sum(int(z.quantity or 0) for z in block.output_applications.all()
                          if z.model_key == "pink")
            self.stdout.write(
                f" PINK_SHEET id={block.pk} date={block.date} "
                f"code={str(values.get('fabric_code') or '').strip()} "
                f"cut={report.v23.v20._int(values.get('cut'))} "
                f"registered={received} applied={applied} "
                f"fabric_unapplied={report._fabric_not_applied(block, 'pink')}"
            )
        self.stdout.write("DATA WRITES = ZERO / INVENTORY AND ACCOUNTING UNCHANGED")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: V122 MATERIAL NET MONTH + OPEN CARRYOVER CHECK PASSED"
        ))
