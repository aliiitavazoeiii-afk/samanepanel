from django.core.management.base import BaseCommand
from core.models import Account, AppSetting, Brand, Color, ElasticBalance, ExpenseCategory, ProductSize, Size, StockLocation


class Command(BaseCommand):
    help = "Create stable base master data without fake sales or inventory."

    def handle(self, *args, **kwargs):
        Brand.objects.get_or_create(name="تکوین")
        Brand.objects.get_or_create(name="دارما")
        for i, name in enumerate(["M", "L", "XL", "XXL", "3XL", "4XL"]):
            Size.objects.get_or_create(name=name, defaults={"sort_order": i})

        # Union of the real Darma and Takvin model/color catalogs from the user's
        # inventory workbooks. Brand-specific visibility is controlled by stock rows.
        colors = [
            # shared / Darma
            ("مشکی", "B"), ("سفید", "W"), ("سرمه ای", "S"), ("صورتی", "P"),
            ("کرم", "K"), ("قرمز", "R"), ("زرد", "Y"), ("طوسی", "G"),
            ("راه راه", "STR"), ("راه راه طوسی", "GSTR"),
            ("برعکس مشکی", "RB"), ("برعکس سفید", "RW"), ("برعکس سرمه ای", "RS"),
            # Takvin-only models/colors
            ("طوسی راه راه", "TGSTR"), ("بنفش", "V"), ("چرک روشن", "CR"),
            ("راه راه بنفش", "VSTR"), ("متفرقه", "MISC"),
            ("راه راه سفید مشکی", "WBSTR"), ("راه راه زرد", "YSTR"),
            ("راه راه سفید", "WSTR"), ("راه راه مشکی", "BSTR"),
        ]
        for name, code in colors:
            Color.objects.get_or_create(name=name, defaults={"code": code, "active": True})

        StockLocation.objects.get_or_create(key="home", defaults={"title": "خانه"})
        StockLocation.objects.get_or_create(key="khorshid", defaults={"title": "انبار خورشید"})
        for key, title in [
            ("melat", "ملت"), ("mofid", "مفید"), ("digikala", "طلب دیجی‌کالا"),
            ("pedram", "حساب پدرام"), ("takvin", "بدهی تکوین"),
        ]:
            Account.objects.get_or_create(key=key, defaults={"title": title})

        defaults = {
            "digikala_commission_percent": ("24", "کمیسیون دیجی‌کالا (%)"),
            "digikala_processing_percent": ("7", "پردازش و ارسال (%)"),
            "digikala_processing_floor": ("36000", "حداقل پردازش و ارسال"),
            "digikala_vat_percent": ("10", "مالیات ارزش افزوده (%)"),
            "digikala_floor_taxable_part": ("18000", "بخش مشمول مالیات در کف پردازش"),
            "pedram_dozen_wage": ("110000", "مزد هر جین پدرام"),
            "darma_accounting_unit_cost": ("61000", "بهای محاسباتی هر شورت دارما"),
            "takvin_discount_percent": ("10", "تخفیف خرید تکوین (%)"),
        }
        for key, (value, label) in defaults.items():
            AppSetting.objects.get_or_create(key=key, defaults={"value": value, "label": label})

        for name in ["16cm", "25cm"]:
            ElasticBalance.objects.get_or_create(name=name)
        for name in ["خوراک", "خودرو و بنزین", "دفتر و انبار", "اینترنت و ارتباطات", "خرید شخصی", "بسته‌بندی و حمل", "سایر"]:
            ExpenseCategory.objects.get_or_create(name=name)

        ProductSize.objects.filter(product__brand__name="تکوین", size__name__in=["3XL", "4XL"]).update(active=False)
        self.stdout.write(self.style.SUCCESS("Base ERP data ready"))
