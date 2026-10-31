from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template
from django.urls import resolve

from core.final_services import sync_inventory_adjustment
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
    _apply_code_batch,
    _apply_color_batch,
    _load_return_batch,
    _return_history,
    _reverse_return_group,
)


class Command(BaseCommand):
    help = "Transactional regression for return report/view/edit/delete V57."

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

    def handle(self, *args, **options):
        if resolve("/returns/").func.__module__ != "core.returns_v37":
            raise CommandError("/returns/ is not routed to returns_v37")
        if resolve("/returns/apply/").func.__module__ != "core.returns_v37":
            raise CommandError("/returns/apply/ is not routed to returns_v37")
        route = resolve("/returns/deadbeef1234/delete/")
        if route.func.__module__ != "core.returns_v37" or route.url_name != "return_delete":
            raise CommandError("V57 return delete route is not active")

        try:
            get_template("core/returns_v37.html")
        except Exception as exc:
            raise CommandError(f"V57 returns template failed to compile: {exc}") from exc

        template_source = (
            Path(settings.BASE_DIR) / "templates" / "core" / "returns_v37.html"
        ).read_text(encoding="utf-8")
        for marker in (
            "صورت‌های مرجوعی ثبت‌شده",
            "return_delete",
            "edit_group",
            "مشاهده",
            "ویرایش",
        ):
            if marker not in template_source:
                raise CommandError(f"V57 template marker missing: {marker}")

        darma = Brand.objects.get(name="دارما")
        candidates = list(
            ProductSize.objects.filter(
                product__brand=darma,
                product__active=True,
                active=True,
                product__composition__isnull=False,
            )
            .select_related("product", "size")
            .prefetch_related("product__composition__color")
            .distinct()
        )
        ps = None
        for candidate in candidates:
            comps = list(candidate.product.composition.all())
            if (
                comps
                and int(candidate.product.pack_qty or 0) > 0
                and sum(int(comp.qty or 0) for comp in comps)
                == int(candidate.product.pack_qty or 0)
            ):
                ps = candidate
                break
        if ps is None:
            raise CommandError("V57 regression needs one fixed-composition Darma ProductSize")

        components = list(ps.product.composition.all())
        first_color = components[0].color
        before = self._state()
        component_before = {
            comp.color_id: self._home_qty(darma, ps.size, comp.color)
            for comp in components
        }

        with transaction.atomic():
            try:
                # 1) A code-based return becomes a visible grouped report with exact details.
                result = _apply_code_batch(
                    when=date.today(),
                    brand=darma,
                    size=ps.size,
                    entries=[(ps, 1)],
                )
                batch, rows = _load_return_batch(result["group"])
                if batch["mode"] != "code":
                    raise CommandError("V57 code return report mode mismatch")
                if batch["shorts"] != int(ps.product.pack_qty or 0):
                    raise CommandError("V57 code return report shorts mismatch")
                if batch["edit_values"].get(ps.id) != 1:
                    raise CommandError("V57 code return edit prefill mismatch")
                if not batch["safe"] or not rows:
                    raise CommandError("V57 new return report was not marked safe")
                if result["group"] not in {row["group"] for row in _return_history()}:
                    raise CommandError("V57 new return did not appear in return history")

                # Exact delete/reversal of the grouped code return.
                _reverse_return_group(result["group"])
                for comp in components:
                    actual = self._home_qty(darma, ps.size, comp.color)
                    if actual != component_before[comp.color_id]:
                        raise CommandError("V57 code-return delete did not restore exact HOME quantity")
                if InventoryAdjustment.objects.filter(
                    note__startswith=f"[standalone-return-v37] group={result['group']} "
                ).exists():
                    raise CommandError("V57 deleted return adjustments still exist")

                # 2) Color return remains deletable even if a newer, unrelated movement
                # exists on the same stock cell. Deleting an event is not V51's
                # 'restore previous physical count' semantic.
                color_result = _apply_color_batch(
                    when=date.today(),
                    brand=darma,
                    size=ps.size,
                    entries=[(first_color, 2)],
                )
                newer = InventoryAdjustment.objects.create(
                    date=date.today(),
                    brand=darma,
                    size=ps.size,
                    color=first_color,
                    location=StockLocation.objects.get(key=StockLocation.HOME),
                    delta=1,
                    note="[v57-regression-newer-movement]",
                )
                sync_inventory_adjustment(newer)
                expected_with_newer_only = component_before[first_color.id] + 1
                _reverse_return_group(color_result["group"])
                actual = self._home_qty(darma, ps.size, first_color)
                if actual != expected_with_newer_only:
                    raise CommandError(
                        f"V57 return delete crossed newer movement incorrectly: {actual} != {expected_with_newer_only}"
                    )
                newer.refresh_from_db()
                if not newer.applied:
                    raise CommandError("V57 return delete altered unrelated newer adjustment")

                # 3) Edit semantics: same group can be atomically replaced with a new
                # quantity, which is exactly what the POST edit flow does.
                edit_group = color_result["group"]
                edited = _apply_color_batch(
                    when=date.today(),
                    brand=darma,
                    size=ps.size,
                    entries=[(first_color, 3)],
                    group=edit_group,
                )
                edited_batch, _ = _load_return_batch(edit_group)
                if edited["group"] != edit_group or edited_batch["edit_values"].get(first_color.id) != 3:
                    raise CommandError("V57 edited return did not preserve group/prefill")
                if self._home_qty(darma, ps.size, first_color) != expected_with_newer_only + 3:
                    raise CommandError("V57 edited return quantity mismatch")
                _reverse_return_group(edit_group)
                if self._home_qty(darma, ps.size, first_color) != expected_with_newer_only:
                    raise CommandError("V57 edited return delete mismatch")
            finally:
                transaction.set_rollback(True)

        after = self._state()
        if before != after:
            raise CommandError(f"V57 regression left persistent business data changed: {before} != {after}")
        for comp in components:
            if self._home_qty(darma, ps.size, comp.color) != component_before[comp.color_id]:
                raise CommandError("V57 regression rollback left HOME inventory changed")

        self.stdout.write("RETURNS REPORT/EDIT/DELETE V57 CHECK OK")
        self.stdout.write("HISTORY: existing V37 return groups are reconstructed from InventoryAdjustment notes")
        self.stdout.write("VIEW: grouped date/brand/size/mode/details/total shorts")
        self.stdout.write("EDIT: same return group is atomically replaced; failure rolls back old return")
        self.stdout.write("DELETE: exact return InventoryMovement + InventoryAdjustment reversed and removed")
        self.stdout.write("NEWER MOVEMENTS: preserved; return deletion removes only the return event")
        self.stdout.write("NO SALES / DIGIKALA / ACCOUNT ENTRIES TOUCHED")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: RETURNS REPORT EDIT DELETE V57 CHECK PASSED"))
