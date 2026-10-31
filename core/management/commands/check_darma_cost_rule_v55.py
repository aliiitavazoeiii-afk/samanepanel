from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template

from core.cost_accounting_v14 import snapshot_sale_line
from core.darma_cost_v55 import (
    BASELINE_EFFECTIVE_FROM,
    apply_darma_cost_rule,
    darma_cost_for,
    set_darma_cost_rule,
)
from core.dia_gallery_v45 import sync_dia_gallery_sale
from core.final_services import sync_inventory_adjustment
from core.finance import sale_line_metrics
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry,
    AppSetting,
    Brand,
    DiaGallerySale,
    InventoryAdjustment,
    InventoryMovement,
    ProductSize,
    SaleDay,
    SaleLine,
    SaleSnapshot,
    StockBalance,
    StockLocation,
)


class Command(BaseCommand):
    help = "Transactional regression for the centralized date-effective Darma cost source V55."

    def _darma_qty(self):
        darma = Brand.objects.get(name="دارما")
        return int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)

    def _state(self):
        return {
            "finished": int(finished_inventory_value_v17()),
            "darma_qty": self._darma_qty(),
            "sales": SaleLine.objects.count(),
            "snapshots": SaleSnapshot.objects.count(),
            "dia": DiaGallerySale.objects.count(),
            "entries": AccountEntry.objects.count(),
            "adjustments": InventoryAdjustment.objects.count(),
            "movements": InventoryMovement.objects.count(),
            "settings": AppSetting.objects.count(),
        }

    def _free_day(self, start):
        candidate = start
        for _ in range(30):
            if not SaleDay.objects.filter(date=candidate).exists():
                return candidate
            candidate += timedelta(days=1)
        raise CommandError("could not find free V55 regression SaleDay")

    def handle(self, *args, **options):
        for template_name in ("core/settings_rules_v17.html", "core/settings_product_form.html"):
            try:
                get_template(template_name)
            except Exception as exc:
                raise CommandError(f"V55 template failed to compile: {template_name}: {exc}") from exc

        rules_source = (Path(settings.BASE_DIR) / "templates" / "core" / "settings_rules_v17.html").read_text(encoding="utf-8")
        for marker in ("darma_cost_rule", "بهای تمام‌شده هر شورت دارما", "darma_delete_rule", "نرخ پایه"):
            if marker not in rules_source:
                raise CommandError(f"V55 settings marker missing: {marker}")

        product_form_source = (Path(settings.BASE_DIR) / "templates" / "core" / "settings_product_form.html").read_text(encoding="utf-8")
        for marker in ("darmaCostReference", "قوانین محاسبات", "cost-col"):
            if marker not in product_form_source:
                raise CommandError(f"V55 product-form central-cost marker missing: {marker}")
        for forbidden in ("fillDarmaCost", "بهای دارما 61 000"):
            if forbidden in product_form_source:
                raise CommandError(f"V55 stale per-product Darma cost control survived: {forbidden}")

        pricing_source = (Path(settings.BASE_DIR) / "core" / "darma_pricing.py").read_text(encoding="utf-8")
        if "darma_cost_for" not in pricing_source or '"unit_cost": 61000' in pricing_source:
            raise CommandError("V55 Darma pricing compatibility path still has an independent hardcoded cost")

        before = self._state()

        with transaction.atomic():
            try:
                # 1) Date-effective rule resolution.
                first_date = date(2098, 1, 1)
                second_date = date(2098, 2, 1)
                set_darma_cost_rule(first_date, 61_000)
                set_darma_cost_rule(second_date, 67_000)
                if darma_cost_for(date(2098, 1, 15)) != 61_000:
                    raise CommandError("V55 first date-effective Darma rule did not resolve")
                if darma_cost_for(date(2098, 2, 15)) != 67_000:
                    raise CommandError("V55 second date-effective Darma rule did not resolve")

                # User-facing path must not overwrite the confirmed 1400/01/01 baseline.
                try:
                    apply_darma_cost_rule(BASELINE_EFFECTIVE_FROM, 67_000)
                except ValueError:
                    pass
                else:
                    raise CommandError("V55 baseline rule was not protected from user overwrite")

                darma = Brand.objects.get(name="دارما")
                darma_ps = (
                    ProductSize.objects.filter(
                        product__brand=darma,
                        product__active=True,
                        active=True,
                    )
                    .select_related("product", "size")
                    .order_by("id")
                    .first()
                )
                if darma_ps is None:
                    raise CommandError("V55 regression needs one active Darma ProductSize")

                # A pre-effective-date snapshot must remain historical.
                old_day = SaleDay.objects.create(date=self._free_day(date(2098, 1, 15)))
                old_line = SaleLine.objects.create(
                    day=old_day,
                    product_size=darma_ps,
                    quantity=1,
                    sale_price=max(1, int(darma_ps.default_sale_price or 100_000)),
                )
                old_snap = snapshot_sale_line(old_line, darma_ps, old_line.sale_price)
                if int(old_snap.unit_cost or 0) != 61_000:
                    raise CommandError(f"V55 pre-rule historical snapshot mismatch: {old_snap.unit_cost}")

                test_date = self._free_day(date(2098, 2, 15))
                day = SaleDay.objects.create(date=test_date)
                line = SaleLine.objects.create(
                    day=day,
                    product_size=darma_ps,
                    quantity=1,
                    sale_price=max(1, int(darma_ps.default_sale_price or 100_000)),
                )
                snap = snapshot_sale_line(line, darma_ps, line.sale_price)
                if int(snap.unit_cost or 0) != 67_000:
                    raise CommandError(f"V55 Darma SaleSnapshot cost mismatch: {snap.unit_cost}")

                # 2) Anbaresh is Darma-backed and must freeze the same rule.
                anbaresh_ps = (
                    ProductSize.objects.filter(
                        product__brand__name="انبارش",
                        product__active=True,
                        active=True,
                    )
                    .select_related("product", "size")
                    .order_by("id")
                    .first()
                )
                if anbaresh_ps is None:
                    raise CommandError("V55 regression needs one active Anbaresh ProductSize")
                anbaresh_line = SaleLine.objects.create(
                    day=day,
                    product_size=anbaresh_ps,
                    quantity=1,
                    sale_price=max(1, int(anbaresh_ps.default_sale_price or 100_000)),
                )
                anbaresh_snap = snapshot_sale_line(anbaresh_line, anbaresh_ps, anbaresh_line.sale_price)
                if int(anbaresh_snap.unit_cost or 0) != 67_000:
                    raise CommandError(f"V55 Anbaresh SaleSnapshot cost mismatch: {anbaresh_snap.unit_cost}")

                # 3) Missing-Snapshot reports must still use the canonical rule.
                fallback_day = SaleDay.objects.create(date=self._free_day(test_date + timedelta(days=1)))
                fallback_line = SaleLine.objects.create(
                    day=fallback_day,
                    product_size=darma_ps,
                    quantity=1,
                    sale_price=max(1, int(darma_ps.default_sale_price or 100_000)),
                )
                fallback_metrics = sale_line_metrics(fallback_line)
                expected_fallback_cogs = int(darma_ps.product.pack_qty or 0) * 67_000
                if int(fallback_metrics["cogs"]) != expected_fallback_cogs:
                    raise CommandError(
                        f"V55 missing-Snapshot Darma fallback mismatch: {fallback_metrics['cogs']} != {expected_fallback_cogs}"
                    )

                # 4) Dia Gallery freezes the rule effective on its SaleDay.
                home = StockLocation.objects.get(key=StockLocation.HOME)
                stock = (
                    StockBalance.objects.filter(brand=darma, location=home)
                    .select_related("size", "color")
                    .order_by("id")
                    .first()
                )
                if stock is None:
                    raise CommandError("V55 regression needs one Darma HOME StockBalance")
                dia = DiaGallerySale.objects.create(
                    day=day,
                    size=stock.size,
                    color=stock.color,
                    quantity=1,
                    unit_price=71_000,
                )
                sync_dia_gallery_sale(dia)
                dia.refresh_from_db()
                if int(dia.unit_cost or 0) != 67_000:
                    raise CommandError(f"V55 Dia frozen Darma cost mismatch: {dia.unit_cost}")

                # 5) User-facing rule application must immediately update already
                # recorded reports on/after its effective date, but never earlier.
                _, updated = apply_darma_cost_rule(test_date, 68_000)
                snap.refresh_from_db()
                anbaresh_snap.refresh_from_db()
                old_snap.refresh_from_db()
                dia.refresh_from_db()
                if int(snap.unit_cost or 0) != 68_000 or int(anbaresh_snap.unit_cost or 0) != 68_000:
                    raise CommandError("V55 effective-date rule did not reprice existing Darma/Anbaresh snapshots")
                if int(dia.unit_cost or 0) != 68_000:
                    raise CommandError("V55 effective-date rule did not reprice existing Dia row")
                if int(old_snap.unit_cost or 0) != 61_000:
                    raise CommandError("V55 effective-date rule rewrote a pre-effective historical snapshot")
                fallback_metrics = sale_line_metrics(fallback_line)
                expected_fallback_cogs = int(darma_ps.product.pack_qty or 0) * 68_000
                if int(fallback_metrics["cogs"]) != expected_fallback_cogs:
                    raise CommandError("V55 missing-Snapshot fallback did not follow newly effective rule")
                if updated["sale_snapshots"] < 2 or updated["dia_rows"] < 1:
                    raise CommandError(f"V55 rule-application update counts unexpected: {updated}")

                # 6) Current finished inventory must be a single Darma rate, not
                # InventoryModelCost. Revalue at today's rule and verify exact delta.
                current_before = int(finished_inventory_value_v17())
                old_rate = int(darma_cost_for(date.today()))
                darma_qty = self._darma_qty()
                new_rate = old_rate + 1_234
                set_darma_cost_rule(date.today(), new_rate)
                current_after = int(finished_inventory_value_v17())
                expected_after = current_before + darma_qty * (new_rate - old_rate)
                if current_after != expected_after:
                    raise CommandError(
                        f"V55 current inventory revaluation mismatch: {current_after} != {expected_after}"
                    )

                # 7) A standalone physical Darma return/adjustment must increase
                # finished value by exactly qty * central current rate.
                stock = StockBalance.objects.select_for_update().get(pk=stock.pk)
                value_before_return = int(finished_inventory_value_v17())
                adjustment = InventoryAdjustment.objects.create(
                    date=date.today(),
                    brand=darma,
                    size=stock.size,
                    color=stock.color,
                    location=home,
                    delta=2,
                    note="[standalone-return-v37] v55-regression",
                )
                sync_inventory_adjustment(adjustment)
                value_after_return = int(finished_inventory_value_v17())
                if value_after_return - value_before_return != 2 * new_rate:
                    raise CommandError(
                        "V55 Darma return valuation did not equal returned shorts * central Darma rate"
                    )
            finally:
                transaction.set_rollback(True)

        after = self._state()
        if before != after:
            raise CommandError(f"V55 regression left persistent business data changed: {before} != {after}")

        self.stdout.write("DARMA COST RULE V55 CHECK OK")
        self.stdout.write("DATE RULES: resolve by effective sale date; baseline is protected")
        self.stdout.write("DARMA + ANBARESH + s3: canonical SaleSnapshot cost")
        self.stdout.write("MISSING SNAPSHOT: canonical date-effective fallback")
        self.stdout.write("PRODUCT UI + BULK PRICING: no independent Darma accounting-cost control/hardcode")
        self.stdout.write("EXISTING REPORTS: rows on/after a new effective date reprice; earlier snapshots stay frozen")
        self.stdout.write("DIA: canonical cost frozen/repriced by effective date")
        self.stdout.write("CURRENT INVENTORY: all Darma stock revalues at one effective current rate")
        self.stdout.write("RETURNS/ADJUSTMENTS: exact qty * canonical current Darma rate")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DARMA COST RULE V55 CHECK PASSED"))
