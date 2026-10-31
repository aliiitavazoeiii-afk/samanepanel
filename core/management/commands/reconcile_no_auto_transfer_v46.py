from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.models import (
    AccountEntry,
    Brand,
    InventoryMovement,
    SaleAllocation,
    SaleLine,
    StockBalance,
    StockLocation,
)


BASELINE_REFERENCE = "day3-physical-files-v32"
REVERSAL_PREFIX = "v46-reverse-auto:"


def _sum(qs, field="qty"):
    return int(qs.aggregate(v=Sum(field))["v"] or 0)


def _business_fingerprint():
    return {
        "sale_lines": SaleLine.objects.count(),
        "sale_qty": _sum(SaleLine.objects.all(), "quantity"),
        "allocations": SaleAllocation.objects.count(),
        "allocation_qty": _sum(SaleAllocation.objects.all(), "qty"),
        "account_entries": AccountEntry.objects.count(),
        "account_delta": _sum(AccountEntry.objects.all(), "delta"),
    }


def _location_totals(brand, home, kh):
    return {
        "home": _sum(StockBalance.objects.filter(brand=brand, location=home)),
        "kh": _sum(StockBalance.objects.filter(brand=brand, location=kh)),
        "combined": _sum(StockBalance.objects.filter(brand=brand)),
    }


def _automatic_transfer_groups(brand, home, kh, baseline_id):
    rows = list(
        InventoryMovement.objects.filter(
            id__gt=baseline_id,
            brand=brand,
            movement_type=InventoryMovement.TRANSFER,
        )
        .filter(reference__contains="transfer")
        .select_related("color", "size", "location")
        .order_by("id")
    )

    groups = {}
    for row in rows:
        ref = str(row.reference or "")
        if "auto-transfer" not in ref and "replacement-transfer" not in ref:
            continue
        if row.location_id not in (home.id, kh.id):
            raise CommandError(
                f"Automatic transfer movement {row.id} uses unexpected location {row.location_id}."
            )
        key = (ref, row.color_id, row.size_id)
        item = groups.setdefault(
            key,
            {
                "reference": ref,
                "color": row.color,
                "size": row.size,
                "home_delta": 0,
                "kh_delta": 0,
                "ids": [],
            },
        )
        item["ids"].append(row.id)
        if row.location_id == home.id:
            item["home_delta"] += int(row.delta or 0)
        else:
            item["kh_delta"] += int(row.delta or 0)

    result = []
    for item in groups.values():
        home_delta = int(item["home_delta"])
        kh_delta = int(item["kh_delta"])
        if home_delta <= 0 or kh_delta >= 0 or home_delta != -kh_delta:
            raise CommandError(
                "Automatic-transfer ledger pair is inconsistent: "
                f"ref={item['reference']} color={item['color'].name} size={item['size'].name} "
                f"HOME={home_delta:+d} KH={kh_delta:+d} ids={item['ids']}"
            )
        item["amount"] = home_delta
        item["source_id"] = min(item["ids"])
        item["reversal_reference"] = f"{REVERSAL_PREFIX}{item['source_id']}"
        result.append(item)

    return sorted(result, key=lambda x: x["source_id"])


class Command(BaseCommand):
    help = (
        "V46: reverse only phantom automatic Darma KHORSHID->HOME sale transfers "
        "created after the authoritative end-of-day 3 Shahrivar physical baseline. "
        "Default is dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        darma = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        kh = StockLocation.objects.get(key=StockLocation.KHORSHID)

        baseline_id = (
            InventoryMovement.objects.filter(reference=BASELINE_REFERENCE)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        )
        if not baseline_id:
            raise CommandError(
                f"Authoritative baseline movement {BASELINE_REFERENCE!r} was not found. Nothing changed."
            )

        groups = _automatic_transfer_groups(darma, home, kh, baseline_id)
        pending = []
        already = []
        for item in groups:
            existing = list(
                InventoryMovement.objects.filter(reference=item["reversal_reference"])
                .select_related("location")
                .order_by("id")
            )
            if not existing:
                pending.append(item)
                continue
            home_rev = sum(int(x.delta or 0) for x in existing if x.location_id == home.id)
            kh_rev = sum(int(x.delta or 0) for x in existing if x.location_id == kh.id)
            if home_rev != -item["amount"] or kh_rev != item["amount"]:
                raise CommandError(
                    f"Existing V46 reversal marker is inconsistent: {item['reversal_reference']} "
                    f"HOME={home_rev:+d} KH={kh_rev:+d} expected={item['amount']}"
                )
            already.append(item)

        before = _location_totals(darma, home, kh)
        fingerprint = _business_fingerprint()
        pending_total = sum(int(x["amount"]) for x in pending)
        historical_total = sum(int(x["amount"]) for x in groups)

        self.stdout.write("=== DARMA NO AUTO-TRANSFER V46 ===")
        self.stdout.write(f"Baseline movement id = {baseline_id}")
        self.stdout.write(f"Automatic transfer groups found = {len(groups)}")
        self.stdout.write(f"Historical phantom transfer qty = {historical_total}")
        self.stdout.write(f"Already reversed qty = {historical_total - pending_total}")
        self.stdout.write(f"Pending reversal qty = {pending_total}")
        self.stdout.write(
            f"Before HOME={before['home']} KHORSHID={before['kh']} COMBINED={before['combined']}"
        )

        by_cell = defaultdict(int)
        for item in pending:
            by_cell[(item["color"].name, item["size"].name)] += int(item["amount"])
        if by_cell:
            self.stdout.write("Pending cells (HOME decreases / KHORSHID restores):")
            for (color, size), qty in sorted(by_cell.items(), key=lambda x: (x[0][1], x[0][0])):
                self.stdout.write(f"  {color} / {size}: {qty}")
        else:
            self.stdout.write("No pending phantom automatic transfers.")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — no data changed."))
            return

        with transaction.atomic():
            # Re-read under transaction so the apply cannot race with stock writes.
            for item in pending:
                if InventoryMovement.objects.filter(reference=item["reversal_reference"]).exists():
                    raise CommandError(
                        f"Concurrent/already-applied reversal detected: {item['reversal_reference']}"
                    )

                home_row, _ = StockBalance.objects.get_or_create(
                    brand=darma,
                    color=item["color"],
                    size=item["size"],
                    location=home,
                    defaults={"qty": 0},
                )
                kh_row, _ = StockBalance.objects.get_or_create(
                    brand=darma,
                    color=item["color"],
                    size=item["size"],
                    location=kh,
                    defaults={"qty": 0},
                )
                home_row = StockBalance.objects.select_for_update().get(pk=home_row.pk)
                kh_row = StockBalance.objects.select_for_update().get(pk=kh_row.pk)

                amount = int(item["amount"])
                home_row.qty = int(home_row.qty or 0) - amount
                kh_row.qty = int(kh_row.qty or 0) + amount
                home_row.save(update_fields=["qty"])
                kh_row.save(update_fields=["qty"])

                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.TRANSFER,
                    brand=darma,
                    color=item["color"],
                    size=item["size"],
                    location=home,
                    delta=-amount,
                    reference=item["reversal_reference"],
                )
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.TRANSFER,
                    brand=darma,
                    color=item["color"],
                    size=item["size"],
                    location=kh,
                    delta=amount,
                    reference=item["reversal_reference"],
                )

            after = _location_totals(darma, home, kh)
            if after["combined"] != before["combined"]:
                raise CommandError(
                    f"Combined Darma stock changed: {before['combined']} -> {after['combined']}; rollback."
                )
            if after["home"] != before["home"] - pending_total:
                raise CommandError(
                    f"HOME delta mismatch: expected {-pending_total:+d}, "
                    f"actual {after['home'] - before['home']:+d}; rollback."
                )
            if after["kh"] != before["kh"] + pending_total:
                raise CommandError(
                    f"KHORSHID delta mismatch: expected {pending_total:+d}, "
                    f"actual {after['kh'] - before['kh']:+d}; rollback."
                )
            if _business_fingerprint() != fingerprint:
                raise CommandError("Sale/allocation/accounting fingerprint changed; rollback.")

        self.stdout.write(
            f"After  HOME={after['home']} KHORSHID={after['kh']} COMBINED={after['combined']}"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"SUCCESS: V46 REVERSED {pending_total} PHANTOM AUTO-TRANSFER UNITS"
            )
        )