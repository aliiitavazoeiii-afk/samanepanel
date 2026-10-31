from datetime import date
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.cost_accounting_v14 import snapshot_sale_line
from core.daily_report_actions_v21 import SaleDayDeleteError, delete_sale_day
from core.dia_gallery_v45 import (
    DIA_GALLERY_UNIT_PRICE,
    dia_gallery_receivable_total,
    sync_dia_gallery_sale,
)
from core.finance_excel_v9 import digikala_receivable_total, sync_sale_receivable
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    Account,
    AccountEntry,
    Brand,
    Color,
    DiaGallerySale,
    ProductCode,
    ProductComposition,
    ProductSize,
    SaleDay,
    SaleLine,
    SaleSnapshot,
    Size,
    StockBalance,
    StockLocation,
)
from core.sale_inventory_v19 import sync_sale_inventory_v19
from core.variant_sale_v12 import ensure_variant_product, sync_variant_inventory


class Command(BaseCommand):
    help = "Transactional regression for V54 full daily sale report deletion."

    def _brand_qty(self, name):
        brand = Brand.objects.get(name=name)
        return int(StockBalance.objects.filter(brand=brand).aggregate(v=Sum("qty"))["v"] or 0)

    def _global_snapshot(self):
        return {
            "finished": int(finished_inventory_value_v17()),
            "digi": int(digikala_receivable_total()),
            "dia": int(dia_gallery_receivable_total()),
            "darma": self._brand_qty("دارما"),
            "sale_days": SaleDay.objects.count(),
            "sale_lines": SaleLine.objects.count(),
            "dia_lines": DiaGallerySale.objects.count(),
            "snapshots": SaleSnapshot.objects.count(),
            "account_entries": AccountEntry.objects.count(),
        }

    def _free_test_date(self):
        for day_number in range(31, 0, -1):
            candidate = date(2099, 12, day_number)
            if not SaleDay.objects.filter(date=candidate).exists():
                return candidate
        raise CommandError("could not find a free V54 regression date")

    def handle(self, *args, **options):
        route = reverse("daily_sale_day_delete", kwargs={"day_id": 123})
        if route != "/sales/123/report/delete/":
            raise CommandError(f"V54 delete route mismatch: {route}")
        resolved = resolve(route)
        if resolved.func.__module__ != "core.daily_report_actions_v21" or resolved.func.__name__ != "sale_day_delete":
            raise CommandError(
                f"V54 route resolver mismatch: {resolved.func.__module__}.{resolved.func.__name__}"
            )

        try:
            get_template("core/daily_report_v45.html")
        except Exception as exc:
            raise CommandError(f"daily report template does not compile: {exc}") from exc

        template_source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "daily_report_v21.html"
        ).read_text(encoding="utf-8")
        for marker in (
            "daily_sale_day_delete",
            "حذف صورت روز",
            "کل صورت این روز حذف شود؟",
        ):
            if marker not in template_source:
                raise CommandError(f"V54 template marker missing: {marker}")

        before = self._global_snapshot()

        with transaction.atomic():
            try:
                darma = Brand.objects.get(name="دارما")
                anbaresh = Brand.objects.get(name="انبارش")
                home = StockLocation.objects.get(key=StockLocation.HOME)
                size = Size.objects.get(name="M")
                color = (
                    Color.objects.filter(
                        stockbalance__brand=darma,
                        stockbalance__size=size,
                        stockbalance__location=home,
                        active=True,
                    )
                    .distinct()
                    .order_by("id")
                    .first()
                )
                if color is None:
                    raise CommandError("V54 regression needs one active Darma M HOME color")

                balance, _ = StockBalance.objects.get_or_create(
                    brand=darma,
                    size=size,
                    color=color,
                    location=home,
                    defaults={"qty": 0},
                )
                start_home = int(balance.qty or 0)
                start_finished = int(finished_inventory_value_v17())
                start_digi = int(digikala_receivable_total())
                start_dia = int(dia_gallery_receivable_total())

                test_date = self._free_test_date()
                day = SaleDay.objects.create(date=test_date)

                # 1) Normal Darma line: fixed composition, exact SaleAllocation,
                # Digikala receivable and SaleSnapshot.
                normal_product = ProductCode.objects.create(
                    code=f"__V54_NORMAL_{uuid4().hex[:10]}__",
                    brand=darma,
                    pack_qty=1,
                    active=True,
                    note="[v54-regression]",
                )
                ProductComposition.objects.create(product=normal_product, color=color, qty=1)
                normal_ps = ProductSize.objects.create(
                    product=normal_product,
                    size=size,
                    default_sale_price=100_000,
                    unit_cost=61_000,
                    active=True,
                )
                normal = SaleLine.objects.create(
                    day=day,
                    product_size=normal_ps,
                    quantity=2,
                    sale_price=100_000,
                )
                sync_sale_inventory_v19(normal)
                snapshot_sale_line(normal, normal_ps, normal.sale_price)
                sync_sale_receivable(normal)
                normal_id = normal.id

                # 2) Anbaresh channel: its SaleLine belongs to Anbaresh while the
                # physical allocation is Darma HOME and must roundtrip there.
                anbaresh_product = ProductCode.objects.create(
                    code=f"__V54_ANBARESH_{uuid4().hex[:10]}__",
                    brand=anbaresh,
                    pack_qty=1,
                    active=True,
                    note="[v54-regression]",
                )
                ProductComposition.objects.create(product=anbaresh_product, color=color, qty=1)
                anbaresh_ps = ProductSize.objects.create(
                    product=anbaresh_product,
                    size=size,
                    default_sale_price=100_000,
                    unit_cost=61_000,
                    active=True,
                )
                anbaresh_line = SaleLine.objects.create(
                    day=day,
                    product_size=anbaresh_ps,
                    quantity=1,
                    sale_price=100_000,
                )
                sync_sale_inventory_v19(anbaresh_line)
                snapshot_sale_line(anbaresh_line, anbaresh_ps, anbaresh_line.sale_price)
                sync_sale_receivable(anbaresh_line)
                anbaresh_id = anbaresh_line.id

                # 3) Variable-color s3: no fixed composition; deletion must use the
                # variant engine and return the exact allocated color.
                variant_product = ensure_variant_product()
                variant_ps = ProductSize.objects.get(product=variant_product, size=size)
                variant = SaleLine.objects.create(
                    day=day,
                    product_size=variant_ps,
                    quantity=1,
                    sale_price=max(1, int(variant_ps.default_sale_price or 100_000)),
                )
                sync_variant_inventory(variant, {color.name: 1})
                snapshot_sale_line(variant, variant_ps, variant.sale_price)
                sync_sale_receivable(variant)
                variant_id = variant.id

                # 4) Dia Gallery: exact color/size + its own receivable.
                dia = DiaGallerySale.objects.create(
                    day=day,
                    size=size,
                    color=color,
                    quantity=1,
                    unit_price=DIA_GALLERY_UNIT_PRICE,
                )
                sync_dia_gallery_sale(dia)
                dia_id = dia.id

                # Same-date non-sale finance data must NOT be removed by day delete.
                unrelated_account = Account.objects.get(key=Account.MELAT)
                unrelated_ref = f"v54-unrelated:{uuid4().hex}"
                AccountEntry.objects.create(
                    date=test_date,
                    account=unrelated_account,
                    delta=123,
                    title="V54 unrelated same-date regression entry",
                    reference=unrelated_ref,
                    entry_type="v54_test",
                )

                applied_home = int(
                    StockBalance.objects.get(
                        brand=darma, size=size, color=color, location=home
                    ).qty
                )
                if applied_home != start_home - 5:
                    raise CommandError(
                        f"V54 setup stock mismatch: {applied_home} != {start_home - 5}"
                    )
                if int(digikala_receivable_total()) <= start_digi:
                    raise CommandError("V54 setup did not increase Digikala receivable")
                if int(dia_gallery_receivable_total()) <= start_dia:
                    raise CommandError("V54 setup did not increase Dia receivable")

                result = delete_sale_day(day.id)
                if result["sale_lines"] != 3 or result["dia_lines"] != 1:
                    raise CommandError(f"V54 deletion count mismatch: {result}")
                if SaleDay.objects.filter(id=day.id).exists():
                    raise CommandError("V54 SaleDay still exists after deletion")
                if SaleLine.objects.filter(id__in=[normal_id, anbaresh_id, variant_id]).exists():
                    raise CommandError("V54 SaleLine survived full day deletion")
                if DiaGallerySale.objects.filter(id=dia_id).exists():
                    raise CommandError("V54 DiaGallerySale survived full day deletion")
                if SaleSnapshot.objects.filter(
                    sale_line_id__in=[normal_id, anbaresh_id, variant_id]
                ).exists():
                    raise CommandError("V54 SaleSnapshot survived SaleLine cascade deletion")
                if not AccountEntry.objects.filter(reference=unrelated_ref).exists():
                    raise CommandError("V54 removed unrelated same-date AccountEntry")

                final_home = int(
                    StockBalance.objects.get(
                        brand=darma, size=size, color=color, location=home
                    ).qty
                )
                if final_home != start_home:
                    raise CommandError(
                        f"V54 stock did not roundtrip: {final_home} != {start_home}"
                    )
                if int(finished_inventory_value_v17()) != start_finished:
                    raise CommandError("V54 finished inventory value did not roundtrip")
                if int(digikala_receivable_total()) != start_digi:
                    raise CommandError("V54 Digikala receivable did not roundtrip")
                if int(dia_gallery_receivable_total()) != start_dia:
                    raise CommandError("V54 Dia receivable did not roundtrip")

                # Remove only the unrelated test entry so the within-transaction
                # state matches the exact pre-test business state before rollback.
                AccountEntry.objects.filter(reference=unrelated_ref).delete()

                # Guard test: an applied historical line with no authoritative
                # allocations must block the whole destructive action.
                guard_date = date(2099, 11, 30)
                if SaleDay.objects.filter(date=guard_date).exists():
                    guard_date = date(2099, 11, 29)
                guard_day = SaleDay.objects.create(date=guard_date)
                guard_line = SaleLine.objects.create(
                    day=guard_day,
                    product_size=normal_ps,
                    quantity=1,
                    inventory_applied_quantity=1,
                    sale_price=100_000,
                )
                try:
                    delete_sale_day(guard_day.id)
                except SaleDayDeleteError:
                    pass
                else:
                    raise CommandError("V54 unsafe no-allocation line was not blocked")
                if not SaleDay.objects.filter(id=guard_day.id).exists():
                    raise CommandError("V54 guard failure partially deleted SaleDay")
                if not SaleLine.objects.filter(id=guard_line.id).exists():
                    raise CommandError("V54 guard failure partially deleted SaleLine")
            finally:
                transaction.set_rollback(True)

        after = self._global_snapshot()
        if before != after:
            raise CommandError(f"V54 regression changed persistent business data: {before} != {after}")

        self.stdout.write("V54 DAILY SALE DAY DELETE CHECK OK")
        self.stdout.write("DARMA + ANBARESH + s3 + DIA: inventory and receivables roundtrip")
        self.stdout.write("SALE SNAPSHOTS: removed with deleted SaleLines")
        self.stdout.write("SAME-DATE NON-SALE DATA: preserved")
        self.stdout.write("UNSAFE APPLIED LINE WITHOUT ALLOCATIONS: blocked atomically")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DAILY SALE DAY DELETE V54 CHECK PASSED"))
