from collections import defaultdict
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template

from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry,
    Brand,
    InventoryAdjustment,
    InventoryMovement,
    ProductSize,
    SaleLine,
    StockBalance,
    StockLocation,
)
from core.returns_v37 import (
    _apply_multi_size_return,
    _load_return_batch,
    _multi_size_sections,
    _return_history,
    _reverse_return_group,
)


class Command(BaseCommand):
    help = "Transactional regression for one-submit multi-size standalone returns V58."

    def _state(self):
        return {
            "finished": int(finished_inventory_value_v17()),
            "adjustments": InventoryAdjustment.objects.count(),
            "movements": InventoryMovement.objects.count(),
            "sales": SaleLine.objects.count(),
            "entries": AccountEntry.objects.count(),
        }

    def _home_qty(self, brand, size, color):
        return int(
            StockBalance.objects.filter(
                brand=brand,
                size=size,
                color=color,
                location__key=StockLocation.HOME,
            ).aggregate(v=Sum("qty"))["v"]
            or 0
        )

    def _pick_two_sizes(self, darma):
        rows = list(
            ProductSize.objects.filter(
                product__brand=darma,
                product__active=True,
                active=True,
                product__composition__isnull=False,
            )
            .select_related("product", "size")
            .prefetch_related("product__composition__color")
            .order_by("product_id", "size__sort_order", "id")
            .distinct()
        )
        by_product = defaultdict(list)
        for ps in rows:
            comps = list(ps.product.composition.all())
            if (
                comps
                and int(ps.product.pack_qty or 0) > 0
                and sum(int(comp.qty or 0) for comp in comps)
                == int(ps.product.pack_qty or 0)
            ):
                by_product[ps.product_id].append(ps)
        for group in by_product.values():
            unique_sizes = []
            seen = set()
            for ps in group:
                if ps.size_id in seen:
                    continue
                seen.add(ps.size_id)
                unique_sizes.append(ps)
            if len(unique_sizes) >= 2:
                return unique_sizes[0], unique_sizes[1]
        raise CommandError("V58 regression needs one fixed-composition Darma product active in at least two sizes")

    def handle(self, *args, **options):
        try:
            get_template("core/returns_v37.html")
        except Exception as exc:
            raise CommandError(f"V58 returns template failed to compile: {exc}") from exc

        template_source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "returns_v37.html"
        ).read_text(encoding="utf-8")
        for marker in (
            "ثبت یکجای همه سایزها",
            "qty_code_{{ section.size.id }}_{{ row.ps.id }}",
            "qty_color_{{ section.size.id }}_{{ color.id }}",
            "تاریخ مشترک همه سایزها",
        ):
            if marker not in template_source:
                raise CommandError(f"V58 template marker missing: {marker}")

        darma = Brand.objects.get(name="دارما")
        ps1, ps2 = self._pick_two_sizes(darma)
        if ps1.product_id != ps2.product_id:
            raise CommandError("V58 regression selection unexpectedly crossed products")

        sizes = [ps1.size, ps2.size]
        sections = _multi_size_sections(mode="code", brand=darma, sizes=sizes)
        if [section["size"].id for section in sections] != [ps1.size_id, ps2.size_id]:
            raise CommandError("V58 size sections do not preserve both requested sizes")
        if not all(section["products"] for section in sections):
            raise CommandError("V58 code sections missing products")

        components = list(ps1.product.composition.all())
        before = self._state()
        qty_before = {
            (ps.size_id, comp.color_id): self._home_qty(darma, ps.size, comp.color)
            for ps in (ps1, ps2)
            for comp in components
        }

        with transaction.atomic():
            try:
                result = _apply_multi_size_return(
                    when=date.today(),
                    mode="code",
                    brand=darma,
                    size_entries=[
                        (ps1.size, [(ps1, 2)]),
                        (ps2.size, [(ps2, 3)]),
                    ],
                )
                expected_shorts = int(ps1.product.pack_qty or 0) * 5
                if result["sizes"] != 2 or result["shorts"] != expected_shorts:
                    raise CommandError(f"V58 multi-size totals mismatch: {result}")
                groups = [row["group"] for row in result["results"]]
                if len(set(groups)) != 2:
                    raise CommandError("V58 must keep one independent report group per populated size")

                expected_packs = {ps1.size_id: 2, ps2.size_id: 3}
                for item in result["results"]:
                    batch, rows = _load_return_batch(item["group"])
                    if batch["size"].id != item["size"].id or batch["mode"] != "code":
                        raise CommandError("V58 generated report has wrong size/mode")
                    ps = ps1 if item["size"].id == ps1.size_id else ps2
                    if batch["edit_values"].get(ps.id) != expected_packs[item["size"].id]:
                        raise CommandError("V58 generated report edit prefill mismatch")
                    if not rows or not batch["safe"]:
                        raise CommandError("V58 generated report is not safely reconstructable")

                history_groups = {row["group"] for row in _return_history()}
                if not set(groups).issubset(history_groups):
                    raise CommandError("V58 generated groups did not appear in return history")

                for ps, packs in ((ps1, 2), (ps2, 3)):
                    for comp in components:
                        expected = qty_before[(ps.size_id, comp.color_id)] + packs * int(comp.qty or 0)
                        actual = self._home_qty(darma, ps.size, comp.color)
                        if actual != expected:
                            raise CommandError(
                                f"V58 HOME quantity mismatch for size={ps.size.name} color={comp.color.name}: {actual} != {expected}"
                            )

                for group in groups:
                    _reverse_return_group(group)
                for ps in (ps1, ps2):
                    for comp in components:
                        actual = self._home_qty(darma, ps.size, comp.color)
                        if actual != qty_before[(ps.size_id, comp.color_id)]:
                            raise CommandError("V58 grouped delete did not restore exact pre-return HOME stock")

                # All-or-nothing semantics: first size is valid, second intentionally uses
                # a ProductSize that belongs to the wrong size. The outer atomic block
                # must leave neither size applied when the second part fails.
                before_failed_submit = {
                    (ps.size_id, comp.color_id): self._home_qty(darma, ps.size, comp.color)
                    for ps in (ps1, ps2)
                    for comp in components
                }
                try:
                    with transaction.atomic():
                        _apply_multi_size_return(
                            when=date.today(),
                            mode="code",
                            brand=darma,
                            size_entries=[
                                (ps1.size, [(ps1, 1)]),
                                (ps2.size, [(ps1, 1)]),
                            ],
                        )
                    raise CommandError("V58 invalid second-size submit unexpectedly succeeded")
                except ValueError:
                    pass
                for ps in (ps1, ps2):
                    for comp in components:
                        actual = self._home_qty(darma, ps.size, comp.color)
                        expected = before_failed_submit[(ps.size_id, comp.color_id)]
                        if actual != expected:
                            raise CommandError("V58 failed multi-size submit was not fully rolled back")
            finally:
                transaction.set_rollback(True)

        after = self._state()
        if before != after:
            raise CommandError(f"V58 regression left persistent business data changed: {before} != {after}")
        for ps in (ps1, ps2):
            for comp in components:
                if self._home_qty(darma, ps.size, comp.color) != qty_before[(ps.size_id, comp.color_id)]:
                    raise CommandError("V58 regression rollback left HOME inventory changed")

        self.stdout.write("RETURNS MULTI-SIZE V58 CHECK OK")
        self.stdout.write("ENTRY UI: all allowed sizes rendered simultaneously under one date/form")
        self.stdout.write("ONE SUBMIT: populated sizes apply together; blanks are ignored")
        self.stdout.write("ATOMICITY: an invalid later size rolls back earlier sizes from the same submit")
        self.stdout.write("HISTORY: each populated size keeps its own V57 view/edit/delete report")
        self.stdout.write("DELETE: each generated size report reverses exact HOME inventory only")
        self.stdout.write("NO SALES / DIGIKALA / ACCOUNT ENTRIES TOUCHED")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: RETURNS MULTI-SIZE V58 CHECK PASSED"))
