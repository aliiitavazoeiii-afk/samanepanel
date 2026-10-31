from django.core.management.base import BaseCommand, CommandError

from core import daily_order_import_v12 as v12


class Command(BaseCommand):
    help = "Read-only regression audit for known title patterns in the current Digikala delivery export."

    def handle(self, *args, **options):
        cases = [
            ("D-220 4XL", "WRONG", "شورت زنانه دارما مدل D-220 مجموعه 3 عددی | 46-48 | چند رنگ | گارانتی اصالت و سلامت فیزیکی کالا", "دارما", "D 220", "4XL"),
            ("rah-220 3XL", "D220", "شورت زنانه دارما مدل rah-220 مجموعه 3 عددی | 3XL | چند رنگ | گارانتی اصالت و سلامت فیزیکی کالا", "دارما", "rah-220", "3XL"),
            ("brandless 400 XL", "SOMETHING", "شورت زنانه مدل 400 مجموعه 4 عددی | XL | چند رنگ | گارانتی اصالت و سلامت فیزیکی کالا", "دارما", "400", "XL"),
            ("Takvin 1-654 M", "", "شورت زنانه تکوین مدل 1-654 مجموعه 5 عددی | M | چند رنگ | گارانتی اصالت و سلامت فیزیکی کالا", "تکوین", "654-1", "M"),
        ]
        errors = []
        for label, seller, title, brand, code, size in cases:
            product = v12._resolve_product_v12(seller, title, {"junk": [object()]})
            resolved_size = v12._resolve_size(title)
            got = None if not product else (product.brand.name, product.code, resolved_size)
            expected = (brand, code, size)
            if got != expected:
                errors.append(f"{label}: expected={expected!r} got={got!r}")
            else:
                self.stdout.write(f"OK {label}: {brand}/{code}/{size}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("CURRENT DELIVERY TITLE AUDIT FAILED")
        self.stdout.write(self.style.SUCCESS("CURRENT DELIVERY TITLE AUDIT OK"))
