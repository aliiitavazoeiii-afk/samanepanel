from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.models import Brand, Color, InventoryModelCost, Size, StockBalance, StockLocation


DARMA_STOCK = {
    "M": {"مشکی": 312, "سفید": 240, "سرمه ای": 146, "صورتی": 263, "کرم": 348, "قرمز": 153, "زرد": -4, "طوسی": 100, "راه راه": 218, "راه راه طوسی": 218, "برعکس مشکی": 47, "برعکس سفید": 45, "برعکس سرمه ای": 0},
    "L": {"مشکی": 664, "سفید": 251, "سرمه ای": 656, "صورتی": 690, "کرم": 1009, "قرمز": -34, "زرد": 80, "طوسی": 101, "راه راه": 107, "راه راه طوسی": 313, "برعکس مشکی": 83, "برعکس سفید": 72, "برعکس سرمه ای": 71},
    "XL": {"مشکی": 716, "سفید": 164, "سرمه ای": 1270, "صورتی": 94, "کرم": 616, "قرمز": -29, "زرد": 0, "طوسی": 32, "راه راه": 39, "راه راه طوسی": 444, "برعکس مشکی": 79, "برعکس سفید": 38, "برعکس سرمه ای": 67},
    "XXL": {"مشکی": 791, "سفید": 351, "سرمه ای": 903, "صورتی": 547, "کرم": 702, "قرمز": -39, "زرد": 0, "طوسی": -3, "راه راه": 105, "راه راه طوسی": 439, "برعکس مشکی": 85, "برعکس سفید": 121, "برعکس سرمه ای": 72},
    "3XL": {"مشکی": 95, "سفید": 152, "سرمه ای": 298, "صورتی": 53, "کرم": 124, "قرمز": 0, "زرد": 0, "طوسی": 10, "راه راه": 41, "راه راه طوسی": 100, "برعکس مشکی": 87, "برعکس سفید": 84, "برعکس سرمه ای": 76},
}

TAKVIN_STOCK = {
    "M": {"طوسی راه راه": 8, "زرد": 11, "بنفش": 8, "طوسی": 41, "سرمه ای": 32, "سفید": 43, "چرک روشن": 35, "مشکی": 51, "راه راه بنفش": 1, "متفرقه": 21, "راه راه طوسی": 10},
    "L": {"طوسی راه راه": 44, "زرد": 0, "بنفش": 34, "طوسی": 43, "سرمه ای": 56, "سفید": 39, "چرک روشن": 50, "مشکی": 23, "راه راه بنفش": 37, "راه راه سفید مشکی": 1, "راه راه زرد": 60, "متفرقه": 13, "راه راه طوسی": 10},
    "XL": {"طوسی راه راه": 36, "زرد": 0, "بنفش": 32, "طوسی": 23, "سرمه ای": 25, "سفید": 42, "چرک روشن": 16, "مشکی": 56, "راه راه بنفش": 37, "متفرقه": 6, "راه راه طوسی": 10, "راه راه سفید": 7, "راه راه مشکی": 21},
    "XXL": {"طوسی راه راه": 26, "زرد": 0, "بنفش": 23, "طوسی": 9, "سرمه ای": 12, "سفید": 20, "چرک روشن": 34, "مشکی": 58, "راه راه بنفش": 27, "متفرقه": 3, "راه راه طوسی": 6, "راه راه سفید": 35, "راه راه مشکی": 75},
}

DARMA_EXPECTED = {"M": 2086, "L": 4063, "XL": 3530, "XXL": 4074, "3XL": 1120, "4XL": 0}
TAKVIN_EXPECTED = {"M": 261, "L": 410, "XL": 311, "XXL": 328}
DARMA_TOTAL = 14873
TAKVIN_TOTAL = 1310

DARMA_COST_BY_SIZE = {"M": 61000, "L": 61000, "XL": 61000, "XXL": 61000, "3XL": 61000, "4XL": 61000}
TAKVIN_COST_BY_SIZE = {"M": 108000, "L": 126000, "XL": 139500, "XXL": 153000}


class Command(BaseCommand):
    help = "Delete all business data, rebuild base masters, and load supplied Darma + Takvin opening stock into Home."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Required acknowledgement for destructive reset")

    @transaction.atomic
    def handle(self, *args, **options):
        if not options.get("yes"):
            raise CommandError("This command deletes ALL business data. Run again with --yes.")

        tables = [t for t in connection.introspection.table_names() if t.startswith("core_")]
        if not tables:
            raise CommandError("No core_* tables were found; refusing to continue.")

        quoted = ", ".join(connection.ops.quote_name(t) for t in tables)
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")

        call_command("seed_base", verbosity=0)

        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)

        def load_brand(brand_name, stock, expected_by_size, expected_total, cost_by_size, include_khorshid=False):
            brand = Brand.objects.get(name=brand_name)
            model_names = sorted({name for values in stock.values() for name in values.keys()})
            total = 0

            for size_name in expected_by_size.keys():
                size = Size.objects.get(name=size_name)
                unit_cost = int(cost_by_size.get(size_name, 0))
                size_values = stock.get(size_name, {})
                size_total = 0

                for color_name in model_names:
                    qty = int(size_values.get(color_name, 0))
                    color = Color.objects.get(name=color_name)

                    StockBalance.objects.update_or_create(
                        brand=brand, size=size, color=color, location=home,
                        defaults={"qty": qty},
                    )
                    if include_khorshid:
                        StockBalance.objects.update_or_create(
                            brand=brand, size=size, color=color, location=khorshid,
                            defaults={"qty": 0},
                        )

                    InventoryModelCost.objects.update_or_create(
                        brand=brand, color=color, size=size,
                        defaults={"unit_cost": unit_cost},
                    )

                    size_total += qty
                    total += qty

                expected = expected_by_size[size_name]
                if size_total != expected:
                    raise CommandError(f"{brand_name} inventory validation failed for {size_name}: {size_total} != {expected}")

            if total != expected_total:
                raise CommandError(f"{brand_name} inventory validation failed: {total} != {expected_total}")

            expected_cost_rows = len(model_names) * len(expected_by_size)
            actual_cost_rows = InventoryModelCost.objects.filter(brand=brand).count()
            if actual_cost_rows != expected_cost_rows:
                raise CommandError(
                    f"{brand_name} cost matrix incomplete: {actual_cost_rows} != {expected_cost_rows}"
                )

            return total, len(model_names), actual_cost_rows

        darma_total, darma_models, darma_cost_rows = load_brand(
            "دارما", DARMA_STOCK, DARMA_EXPECTED, DARMA_TOTAL,
            DARMA_COST_BY_SIZE, include_khorshid=True,
        )
        takvin_total, takvin_models, takvin_cost_rows = load_brand(
            "تکوین", TAKVIN_STOCK, TAKVIN_EXPECTED, TAKVIN_TOTAL,
            TAKVIN_COST_BY_SIZE, include_khorshid=False,
        )

        # Keep product codes/compositions available after any future destructive reset.
        call_command("sync_excel_product_catalog", verbosity=0)

        self.stdout.write(self.style.SUCCESS("Business data reset complete."))
        self.stdout.write(self.style.SUCCESS("Darma + Takvin opening inventory loaded into Home."))
        for name, value in DARMA_EXPECTED.items():
            self.stdout.write(f"  Darma {name}: {value}")
        self.stdout.write(self.style.SUCCESS(f"Darma Home total: {darma_total}"))
        self.stdout.write(self.style.SUCCESS(f"Darma models: {darma_models} | cost rows: {darma_cost_rows}"))
        self.stdout.write(self.style.SUCCESS("Darma Khorshid total: 0"))
        for name, value in TAKVIN_EXPECTED.items():
            self.stdout.write(f"  Takvin {name}: {value}")
        self.stdout.write(self.style.SUCCESS(f"Takvin Home total: {takvin_total}"))
        self.stdout.write(self.style.SUCCESS(f"Takvin models: {takvin_models} | cost rows: {takvin_cost_rows}"))
        self.stdout.write(self.style.SUCCESS("Inventory valuation costs loaded."))
        self.stdout.write(self.style.SUCCESS("Excel product catalog loaded."))
        self.stdout.write(self.style.WARNING("Negative Darma quantities from the workbook were preserved exactly."))
