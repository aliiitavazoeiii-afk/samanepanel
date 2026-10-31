from .brand_colors import norm
from .models import Brand, Color, ProductCode, ProductComposition, ProductSize, Size


TAKVIN_UNIT_COST = {"M": 108000, "L": 126000, "XL": 139500, "XXL": 153000}
DARMA_UNIT_COST = {"M": 61000, "L": 61000, "XL": 61000, "XXL": 61000, "3XL": 61000, "4XL": 61000}

# Final user-confirmed Darma selling prices. Any Darma product whose composition
# totals 3/4/5/6 pieces uses this table, regardless of product code.
DARMA_PRICE_BY_PACK = {
    3: {"M": 385000, "L": 405000, "XL": 430000, "XXL": 455000, "3XL": 470000, "4XL": 495000},
    4: {"M": 485000, "L": 515000, "XL": 545000, "XXL": 570000, "3XL": 610000, "4XL": 630000},
    5: {"M": 570000, "L": 618000, "XL": 658000, "XXL": 701000, "3XL": 743000, "4XL": 790000},
    6: {"M": 699000, "L": 755000, "XL": 795000, "XXL": 860000, "3XL": 920000, "4XL": 980000},
}

# Canonical current product catalog reconstructed from the workbook's product rows,
# pack-size formulas and per-color sales formulas. Composition is invariant by size.
# User-confirmed removals from Darma: legacy codes `rah` and `blk` are intentionally absent.
CATALOG = {
    "تکوین": {
        "12": {"composition": {"طوسی راه راه": 1}, "prices": {"M": 300000, "L": 330000, "XL": 360000, "XXL": 390000}},
        "987": {"composition": {"طوسی راه راه": 1, "بنفش": 1, "طوسی": 1, "سرمه ای": 1, "چرک روشن": 1, "مشکی": 1}, "prices": {"M": 1400000, "L": 1650000, "XL": 1900000, "XXL": 2000000}},
        "06مشکی": {"composition": {"مشکی": 1}, "prices": {"M": 300000, "L": 330000, "XL": 360000, "XXL": 390000}},
        "سفید 09": {"composition": {"سفید": 1}, "prices": {"M": 300000, "L": 330000, "XL": 360000, "XXL": 390000}},
        "502": {"composition": {"طوسی راه راه": 1, "طوسی": 1, "سرمه ای": 1}, "prices": {"M": 730000, "L": 860000, "XL": 960000, "XXL": 1050000}},
        "4444": {"composition": {"بنفش": 1, "سرمه ای": 1, "چرک روشن": 1}, "prices": {"M": 730000, "L": 860000, "XL": 960000, "XXL": 1050000}},
        "654-1": {"composition": {"بنفش": 1, "طوسی": 1, "سرمه ای": 1, "سفید": 1, "چرک روشن": 1}, "prices": {"M": 1200000, "L": 1400000, "XL": 1600000, "XXL": 1800000}},
        "555-1": {"composition": {"طوسی": 1, "سرمه ای": 1, "سفید": 1, "چرک روشن": 1, "مشکی": 1}, "prices": {"M": 1200000, "L": 1400000, "XL": 1600000, "XXL": 1800000}},
        "2222": {"composition": {"طوسی": 1, "چرک روشن": 1, "راه راه بنفش": 1}, "prices": {"M": 730000, "L": 860000, "XL": 960000, "XXL": 1050000}},
        "1010": {"composition": {"طوسی": 1, "سفید": 1, "مشکی": 1}, "prices": {"M": 730000, "L": 860000, "XL": 960000, "XXL": 1050000}},
        "787": {"composition": {"بنفش": 1, "طوسی": 1, "سرمه ای": 1, "سفید": 1, "چرک روشن": 1, "مشکی": 1}, "prices": {"M": 1400000, "L": 1650000, "XL": 1900000, "XXL": 2000000}},
        "23": {"composition": {"راه راه سفید مشکی": 1}, "prices": {"L": 600000}},
        "16": {"composition": {"راه راه زرد": 1}, "prices": {"L": 100000}},
        "gg": {"composition": {"طوسی راه راه": 1, "سرمه ای": 1}, "prices": {"L": 400000}},
        "403": {"composition": {"راه راه سفید": 1, "راه راه مشکی": 1}, "prices": {"XL": 550000, "XXL": 550000}},
    },
    "دارما": {
        "D 110": {"composition": {"سرمه ای": 1, "سفید": 1, "کرم": 1}},
        "D 220": {"composition": {"سفید": 1, "صورتی": 1, "کرم": 1}},
        "D 330": {"composition": {"مشکی": 1, "سفید": 1, "صورتی": 1}},
        "D 440": {"composition": {"مشکی": 1, "سفید": 1, "سرمه ای": 1}},
        "D 550": {"composition": {"مشکی": 1, "سرمه ای": 1, "صورتی": 1}},
        "D 660": {"composition": {"مشکی": 1, "سرمه ای": 1, "کرم": 1}},
        "pack 5": {"composition": {"مشکی": 1, "سفید": 1, "سرمه ای": 1, "صورتی": 1, "کرم": 1}},
        "880": {"composition": {"مشکی": 1, "سفید": 1, "کرم": 1}},
        "990": {"composition": {"مشکی": 1, "قرمز": 1, "زرد": 1}},
        "770": {"composition": {"سفید": 1, "سرمه ای": 1, "صورتی": 1}},
        "p12": {"composition": {"مشکی": 2, "سفید": 2, "سرمه ای": 2, "صورتی": 2, "کرم": 2, "طوسی": 2}, "prices": {"M": 1380000, "L": 1500000, "XL": 1600000, "XXL": 1700000, "3XL": 1800000}},
        "400": {"composition": {"مشکی": 1, "سرمه ای": 1, "صورتی": 1, "طوسی": 1}},
        "06": {"composition": {"مشکی": 1, "سفید": 1, "سرمه ای": 1, "صورتی": 1, "کرم": 1, "طوسی": 1}},
        "rah-110": {"composition": {"راه راه": 1, "سفید": 1, "سرمه ای": 1}},
        "pgw": {"composition": {"سفید": 1, "صورتی": 1, "طوسی": 1}},
        "rah-220": {"composition": {"راه راه طوسی": 1, "سفید": 1, "طوسی": 1}},
        "op": {"composition": {"برعکس مشکی": 1, "برعکس سفید": 1, "برعکس سرمه ای": 1}},
    },
}


def _color_for_name(name):
    wanted = norm(name)
    for color in Color.objects.filter(active=True).order_by("id"):
        if norm(color.name) == wanted:
            return color
    return Color.objects.create(name=name, active=True)


def sync_catalog():
    summary = {}
    for brand_name, products in CATALOG.items():
        brand = Brand.objects.get(name=brand_name)
        created_count = 0
        updated_count = 0
        for code, spec in products.items():
            composition = spec["composition"]
            pack_qty = sum(int(qty) for qty in composition.values())
            product, created = ProductCode.objects.get_or_create(
                brand=brand, code=code,
                defaults={"pack_qty": pack_qty, "active": True, "note": "[excel-catalog]"},
            )
            product.pack_qty = pack_qty
            product.active = True
            product.note = "[excel-catalog] ترکیب ثابت استخراج‌شده از اکسل"
            product.save(update_fields=["pack_qty", "active", "note"])

            ProductComposition.objects.filter(product=product).delete()
            for color_name, qty in composition.items():
                ProductComposition.objects.create(
                    product=product, color=_color_for_name(color_name), qty=int(qty)
                )

            if brand_name == "دارما" and pack_qty in DARMA_PRICE_BY_PACK:
                prices = DARMA_PRICE_BY_PACK[pack_qty]
            else:
                prices = spec.get("prices", {})

            configured_size_ids = []
            for size_name, sale_price in prices.items():
                size = Size.objects.get(name=size_name)
                if brand_name == "تکوین":
                    unit_cost = TAKVIN_UNIT_COST[size_name]
                else:
                    unit_cost = int(spec.get("unit_cost", DARMA_UNIT_COST.get(size_name, 61000)))
                ProductSize.objects.update_or_create(
                    product=product, size=size,
                    defaults={
                        "default_sale_price": int(sale_price),
                        "unit_cost": unit_cost,
                        "active": True,
                    },
                )
                configured_size_ids.append(size.id)

            ProductSize.objects.filter(product=product).exclude(size_id__in=configured_size_ids).update(active=False)
            if created:
                created_count += 1
            else:
                updated_count += 1
        summary[brand_name] = {"created": created_count, "updated": updated_count, "total": len(products)}
    return summary