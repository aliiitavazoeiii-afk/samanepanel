import inspect

from django.core.management.base import BaseCommand, CommandError

from core import daily_order_import_v12 as v12
from core import daily_order_import_v23 as v23
from core import daily_order_views_v8
from core.models import ProductSize
from core.title_product_resolver_v27 import resolve_product_from_title


class Command(BaseCommand):
    help = "Verify delivery statuses and deterministic title-only product resolution."

    def handle(self, *args, **options):
        errors = []

        accepted = [
            "",
            "دریافت شده",
            "دریافت‌شده",
            "اماده ارسال/تحویل",
            "آماده ارسال/تحویل",
            "آماده ارسال / تحویل",
        ]
        rejected = [
            "مرجوع شده",
            "لغو ارسال/تحویل",
            "عدم تحویل",
            "عدم ارسال",
            "ارسال ناموفق",
            "رد شده",
        ]
        for value in accepted:
            if not v23._status_is_delivery(value):
                errors.append(f"should accept status: {value!r}")
        for value in rejected:
            if v23._status_is_delivery(value):
                errors.append(f"should reject status: {value!r}")

        module = getattr(daily_order_views_v8.apply_delivery_report, "__module__", "")
        if module != "core.daily_order_import_v23":
            errors.append(f"daily upload engine is {module}, expected core.daily_order_import_v23")

        conflict_title = (
            "شورت زنانه دارما مدل D-220 مجموعه 3 عددی | 46-48 | چند رنگ | "
            "گارانتی اصالت و سلامت فیزیکی کالا"
        )
        product = v12._resolve_product_v12("rah220", conflict_title, {"rah220": [object()]})
        size_name = v12._resolve_size(conflict_title)
        if not product or product.brand.name != "دارما" or product.code != "D 220":
            shown = None if not product else f"{product.brand.name}/{product.code}"
            errors.append(f"STRICT D-220 regression failed: expected دارما/D 220, got {shown}")
        if size_name != "4XL":
            errors.append(f"46-48 size regression failed: expected 4XL, got {size_name}")
        if product and size_name and not ProductSize.objects.filter(product=product, size__name=size_name, active=True).exists():
            errors.append("resolved target دارما/D 220/4XL is not active in ProductSize")

        rah_title = (
            "شورت زنانه دارما مدل rah-220 مجموعه 3 عددی | 3XL | چند رنگ | "
            "گارانتی اصالت و سلامت فیزیکی کالا"
        )
        rah_product = v12._resolve_product_v12("D220", rah_title, {"d220": [object()]})
        if not rah_product or rah_product.brand.name != "دارما" or rah_product.code != "rah-220":
            shown = None if not rah_product else f"{rah_product.brand.name}/{rah_product.code}"
            errors.append(f"STRICT rah-220 regression failed: expected دارما/rah-220, got {shown}")

        # Direct resolver must distinguish the two titles even when contradictory
        # seller-code/by-key data are supplied to the compatibility wrapper.
        direct_d = resolve_product_from_title(conflict_title)
        direct_rah = resolve_product_from_title(rah_title)
        if not direct_d or direct_d.code != "D 220":
            errors.append("direct title resolver does not map D-220 to D 220")
        if not direct_rah or direct_rah.code != "rah-220":
            errors.append("direct title resolver does not map rah-220 to rah-220")
        if direct_d and direct_rah and direct_d.id == direct_rah.id:
            errors.append("D-220 and rah-220 incorrectly resolve to the same ProductCode")

        # The current real export has Darma model 400 rows whose title omits the
        # brand word entirely. This still must resolve from title/model only when
        # the model is unique across marketplace brands; seller code stays unused.
        brandless_400_title = (
            "شورت زنانه مدل 400 مجموعه 4 عددی | XL | چند رنگ | "
            "گارانتی اصالت و سلامت فیزیکی کالا"
        )
        brandless_400 = v12._resolve_product_v12("WRONG-SELLER-CODE", brandless_400_title, {"wrong": [object()]})
        if not brandless_400 or brandless_400.brand.name != "دارما" or brandless_400.code != "400":
            shown = None if not brandless_400 else f"{brandless_400.brand.name}/{brandless_400.code}"
            errors.append(f"brandless title 400 failed: expected دارما/400, got {shown}")

        takvin_alias = "شورت زنانه تکوین مدل 1-654 مجموعه 5 عددی | M | چند رنگ"
        takvin = resolve_product_from_title(takvin_alias)
        if not takvin or takvin.brand.name != "تکوین" or takvin.code != "654-1":
            shown = None if not takvin else f"{takvin.brand.name}/{takvin.code}"
            errors.append(f"Takvin title alias failed: expected تکوین/654-1, got {shown}")

        no_model_title = "شورت زنانه دارما | 46-48 | چند رنگ | گارانتی اصالت و سلامت فیزیکی کالا"
        if v12._resolve_product_v12("rah220", no_model_title, {"rah220": [object()]}) is not None:
            errors.append("seller-code fallback is active when title has no model")
        unknown_title = "شورت زنانه دارما مدل UNKNOWN-999 مجموعه 3 عددی | 46-48 | چند رنگ"
        if v12._resolve_product_v12("rah220", unknown_title, {"rah220": [object()]}) is not None:
            errors.append("seller-code fallback is active for unknown title model")

        resolver_source = inspect.getsource(v12._resolve_product_v12)
        if "resolve_product_from_title" not in resolver_source:
            errors.append("active v12 resolver is not using strict v27 title resolver")
        parse_source = inspect.getsource(v23.parse_delivery_report)
        if 'seller_code=""' not in parse_source:
            errors.append("active v23 parser is not discarding seller-code metadata")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("V23 DELIVERY IMPORT CHECK FAILED")

        self.stdout.write("accepted current Digikala status: اماده ارسال/تحویل")
        self.stdout.write("negative return/cancel statuses remain blocked")
        self.stdout.write("D-220 title -> D 220; rah-220 title -> rah-220")
        self.stdout.write("contradictory seller code/by-key data cannot change title result")
        self.stdout.write("seller-code column is discarded at parse time")
        self.stdout.write("brandless title model 400 -> unique Darma/400")
        self.stdout.write("Takvin title 1-654 -> canonical 654-1")
        self.stdout.write(self.style.SUCCESS("V23 DELIVERY IMPORT CHECK OK"))
