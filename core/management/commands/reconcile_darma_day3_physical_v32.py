from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.brand_colors import norm
from core.dateutils import parse_jalali_date
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry, Brand, Color, ExcelManualRow, ExcelManualSetting,
    InventoryModelCost, InventoryMovement, SaleAllocation, SaleDay,
    SaleLine, SaleSnapshot, Size, StockBalance, StockLocation,
)
from core.report_v5 import _raw_material_context

BASELINE_JALALI = "1405/06/03"
REFERENCE = "day3-physical-files-v32"
SIZES = ("M", "L", "XL", "XXL", "3XL", "4XL")

# Exact values from the user's newly uploaded files:
# - موجودی خانه دارما(1).xlsx
# - موجودی انبار خورشید(2).xlsx
# Workbook label «راه راه سرمه ای» maps to internal Darma color «راه راه».
HOME = {
    "مشکی": {"M":54,"L":190,"XL":134,"XXL":134,"3XL":48,"4XL":78},
    "سفید": {"M":150,"L":168,"XL":101,"XXL":86,"3XL":93,"4XL":79},
    "سرمه ای": {"M":36,"L":149,"XL":157,"XXL":115,"3XL":110,"4XL":87},
    "صورتی": {"M":97,"L":225,"XL":68,"XXL":153,"3XL":33,"4XL":81},
    "کرم": {"M":169,"L":245,"XL":245,"XXL":212,"3XL":77,"4XL":79},
    "قرمز": {"M":150,"L":0,"XL":0,"XXL":0,"3XL":0,"4XL":0},
    "زرد": {"M":0,"L":80,"XL":0,"XXL":0,"3XL":0,"4XL":0},
    "طوسی": {"M":42,"L":17,"XL":43,"XXL":0,"3XL":0,"4XL":0},
    "راه راه": {"M":41,"L":15,"XL":22,"XXL":90,"3XL":36,"4XL":0},
    "راه راه طوسی": {"M":15,"L":6,"XL":48,"XXL":29,"3XL":31,"4XL":0},
    "برعکس مشکی": {"M":18,"L":12,"XL":16,"XXL":25,"3XL":14,"4XL":0},
    "برعکس سفید": {"M":16,"L":9,"XL":24,"XXL":23,"3XL":5,"4XL":0},
    "برعکس سرمه ای": {"M":0,"L":11,"XL":51,"XXL":29,"3XL":14,"4XL":0},
}
KHORSHID = {
    "مشکی": {"M":180,"L":460,"XL":350,"XXL":620,"3XL":0,"4XL":0},
    "سفید": {"M":120,"L":70,"XL":0,"XXL":200,"3XL":10,"4XL":0},
    "سرمه ای": {"M":0,"L":400,"XL":500,"XXL":730,"3XL":150,"4XL":0},
    "صورتی": {"M":120,"L":450,"XL":0,"XXL":250,"3XL":0,"4XL":0},
    "کرم": {"M":110,"L":600,"XL":300,"XXL":400,"3XL":0,"4XL":0},
    "قرمز": {"M":160,"L":0,"XL":0,"XXL":0,"3XL":0,"4XL":0},
    "زرد": {"M":0,"L":30,"XL":0,"XXL":0,"3XL":0,"4XL":0},
    "طوسی": {"M":40,"L":70,"XL":0,"XXL":0,"3XL":0,"4XL":0},
    "راه راه": {"M":170,"L":90,"XL":0,"XXL":0,"3XL":0,"4XL":0},
    "راه راه طوسی": {"M":200,"L":310,"XL":400,"XXL":410,"3XL":250,"4XL":0},
    "برعکس مشکی": {"M":30,"L":70,"XL":60,"XXL":60,"3XL":70,"4XL":0},
    "برعکس سفید": {"M":30,"L":70,"XL":10,"XXL":90,"3XL":70,"4XL":0},
    "برعکس سرمه ای": {"M":0,"L":60,"XL":0,"XXL":60,"3XL":60,"4XL":0},
}
TARGETS = {StockLocation.HOME: HOME, StockLocation.KHORSHID: KHORSHID}
EXPECTED_HOME = 4585
EXPECTED_KH = 8890
EXPECTED_TOTAL = 13475
EXPECTED_SIZE_TOTALS = {"M":1948,"L":3807,"XL":2529,"XXL":3716,"3XL":1071,"4XL":404}


def _sum_table(table):
    return sum(int(v) for row in table.values() for v in row.values())


def _capital():
    manual = ExcelManualRow.objects.filter(active=True)
    accounts = sum(int(x.amount or 0) for x in manual.filter(section__in=[ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS]))
    assets = sum(int(x.amount or 0) for x in manual.filter(section=ExcelManualRow.ASSETS))
    finished = int(finished_inventory_value_v17())
    raw = int(_raw_material_context()["materials_total"])
    digi = int(digikala_receivable_total())
    debt = ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value", flat=True).first() or 0
    debt = int(debt)
    return {"accounts":accounts,"assets":assets,"finished":finished,"raw":raw,"digi":digi,"debt":debt,
            "capital":accounts+assets+finished+raw+digi-debt}


def _sales_fingerprint():
    return (
        SaleDay.objects.count(), SaleLine.objects.count(), SaleSnapshot.objects.count(), SaleAllocation.objects.count(),
        int(SaleLine.objects.aggregate(v=Sum("quantity"))["v"] or 0),
        int(AccountEntry.objects.filter(reference__startswith="sale:").aggregate(v=Sum("delta"))["v"] or 0),
    )


def _catalog(brand):
    sizes = {s.name:s for s in Size.objects.filter(name__in=SIZES)}
    if set(sizes) != set(SIZES):
        raise CommandError("Missing Darma sizes: " + ", ".join(sorted(set(SIZES)-set(sizes))))
    colors = list(Color.objects.filter(stockbalance__brand=brand).distinct())
    by_norm = {}
    for c in colors:
        by_norm.setdefault(norm(c.name), []).append(c)
    resolved = {}
    for name in HOME:
        matches = by_norm.get(norm(name), [])
        if len(matches) != 1:
            raise CommandError(f"Darma color resolution failed for {name}: {[x.name for x in matches]}")
        resolved[name] = matches[0]
    locs = {
        StockLocation.HOME: StockLocation.objects.get(key=StockLocation.HOME),
        StockLocation.KHORSHID: StockLocation.objects.get(key=StockLocation.KHORSHID),
    }
    return sizes, resolved, locs


def _costs(brand):
    return {(r.color_id,r.size_id):int(r.unit_cost or 0) for r in InventoryModelCost.objects.filter(brand=brand)}


def _darma_value(brand, costs):
    total = 0
    for r in StockBalance.objects.filter(brand=brand).values("color_id","size_id").annotate(q=Sum("qty")):
        total += int(r["q"] or 0) * int(costs.get((r["color_id"],r["size_id"]),0))
    return total


class Command(BaseCommand):
    help = "Set Darma HOME and KHORSHID exactly to the user's physical end-of-day 1405/06/03 files. Default dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if _sum_table(HOME) != EXPECTED_HOME or _sum_table(KHORSHID) != EXPECTED_KH:
            raise CommandError("Embedded physical files totals are invalid")
        boundary = parse_jalali_date(BASELINE_JALALI)
        days = list(SaleDay.objects.filter(date__gte=parse_jalali_date("1405/06/01")).order_by("date").values_list("date", flat=True))
        if not days or days[-1] != boundary or SaleDay.objects.filter(date__gt=boundary).exists():
            raise CommandError(f"Expected sales only through {BASELINE_JALALI}; current Shahrivar days={days}")

        brand = Brand.objects.get(name="دارما")
        sizes, colors, locs = _catalog(brand)
        costs = _costs(brand)
        before_cap = _capital()
        before_value = _darma_value(brand, costs)
        before_sales = _sales_fingerprint()

        target_map = {}
        target_value = 0
        for loc_key, table in TARGETS.items():
            for cname, smap in table.items():
                c = colors[cname]
                for sname, qty in smap.items():
                    s = sizes[sname]
                    target_map[(loc_key,c.id,s.id)] = int(qty)
                    cost = int(costs.get((c.id,s.id),0))
                    if int(qty) > 0 and cost <= 0:
                        raise CommandError(f"Missing cost for positive target {cname}/{sname}")
                    target_value += int(qty)*cost

        current_rows = list(StockBalance.objects.filter(brand=brand, location__key__in=[StockLocation.HOME,StockLocation.KHORSHID]).select_related("location","color","size").order_by("location__key","color_id","size__sort_order"))
        current_map = {(r.location.key,r.color_id,r.size_id):r for r in current_rows}
        plan = []
        for key, target in target_map.items():
            row = current_map.get(key)
            current = int(row.qty or 0) if row else 0
            if current != target:
                loc_key,cid,sid = key
                plan.append((loc_key,colors[next(k for k,v in colors.items() if v.id==cid)],sizes[next(k for k,v in sizes.items() if v.id==sid)],current,target,target-current,row))
        for key,row in current_map.items():
            if key not in target_map and int(row.qty or 0) != 0:
                plan.append((row.location.key,row.color,row.size,int(row.qty or 0),0,-int(row.qty or 0),row))

        value_delta = target_value - before_value
        self.stdout.write("=== DARMA DAY-3 PHYSICAL RECONCILE V32 ===")
        self.stdout.write(f"Current capital       = {before_cap['capital']:,}")
        self.stdout.write(f"Current Darma value   = {before_value:,}")
        self.stdout.write(f"Target Darma value    = {target_value:,}")
        self.stdout.write(f"Inventory value delta = {value_delta:+,}")
        self.stdout.write(f"Expected capital after= {before_cap['capital'] + value_delta:,}")
        self.stdout.write(f"Changed cells         = {len(plan)}")
        self.stdout.write(f"Target HOME/KH/TOTAL  = {EXPECTED_HOME:,} / {EXPECTED_KH:,} / {EXPECTED_TOTAL:,}")
        self.stdout.write(f"Target size totals    = {EXPECTED_SIZE_TOTALS}")
        self.stdout.write("Key cells: Khorshid cream XXL=400; red XXL=0; HOME cream 3XL=77; HOME grey 4XL=0")
        for loc,c,s,current,target,delta,row in plan:
            self.stdout.write(f"{loc:8} {c.name:18} {s.name:4} {current:6} -> {target:6}  delta={delta:+6}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — no data changed."))
            return

        with transaction.atomic():
            list(StockBalance.objects.select_for_update().filter(brand=brand, location__key__in=[StockLocation.HOME,StockLocation.KHORSHID]))
            if _sales_fingerprint() != before_sales:
                raise CommandError("Sales changed before apply; rerun")
            for loc,c,s,current,target,delta,row in plan:
                if row is None:
                    row,_ = StockBalance.objects.get_or_create(brand=brand,color=c,size=s,location=locs[loc],defaults={"qty":0})
                    row = StockBalance.objects.select_for_update().get(pk=row.pk)
                else:
                    row = StockBalance.objects.select_for_update().get(pk=row.pk)
                actual = int(row.qty or 0)
                delta = int(target)-actual
                if not delta:
                    continue
                row.qty = int(target)
                row.save(update_fields=["qty"])
                InventoryMovement.objects.create(movement_type=InventoryMovement.ADJUST,brand=brand,color=c,size=s,location=locs[loc],delta=delta,reference=REFERENCE)

            actual = {}
            for r in StockBalance.objects.filter(brand=brand,location__key__in=[StockLocation.HOME,StockLocation.KHORSHID]).select_related("location"):
                actual[(r.location.key,r.color_id,r.size_id)] = int(r.qty or 0)
            mismatches = [(k,actual.get(k,0),v) for k,v in target_map.items() if actual.get(k,0) != v]
            extras = [(k,v) for k,v in actual.items() if k not in target_map and v != 0]
            if mismatches or extras:
                raise CommandError(f"Final exact-cell verification failed: mismatches={len(mismatches)} extras={len(extras)}")

            home_total = sum(v for (loc,_,_),v in actual.items() if loc==StockLocation.HOME)
            kh_total = sum(v for (loc,_,_),v in actual.items() if loc==StockLocation.KHORSHID)
            size_totals = {s:0 for s in SIZES}
            sid_to_name = {v.id:k for k,v in sizes.items()}
            for (_loc,_cid,sid),v in actual.items():
                if sid in sid_to_name:
                    size_totals[sid_to_name[sid]] += v
            if (home_total,kh_total,home_total+kh_total) != (EXPECTED_HOME,EXPECTED_KH,EXPECTED_TOTAL):
                raise CommandError(f"Final totals wrong: HOME={home_total} KH={kh_total} TOTAL={home_total+kh_total}")
            if size_totals != EXPECTED_SIZE_TOTALS:
                raise CommandError(f"Final size totals wrong: {size_totals}")
            if _sales_fingerprint() != before_sales:
                raise CommandError("Sale/finance history changed; rollback")
            after_cap = _capital()
            after_value = _darma_value(brand,costs)
            stable = ("accounts","assets","raw","digi","debt")
            if any(after_cap[k] != before_cap[k] for k in stable):
                raise CommandError("A non-inventory capital component changed; rollback")
            if after_value != target_value:
                raise CommandError(f"Darma target valuation mismatch {after_value} != {target_value}")
            if after_cap["capital"] != before_cap["capital"] + value_delta:
                raise CommandError(f"Capital delta mismatch {after_cap['capital']} != {before_cap['capital'] + value_delta}")

        self.stdout.write("")
        self.stdout.write("=== RECONCILE COMPLETE ===")
        self.stdout.write(f"FINAL HOME = {home_total}")
        self.stdout.write(f"FINAL KHORSHID = {kh_total}")
        self.stdout.write(f"FINAL TOTAL = {home_total+kh_total}")
        self.stdout.write(f"FINAL SIZE TOTALS = {size_totals}")
        self.stdout.write(f"CAPITAL BEFORE = {before_cap['capital']:,}")
        self.stdout.write(f"CAPITAL AFTER = {after_cap['capital']:,}")
        self.stdout.write(f"CAPITAL DELTA = {after_cap['capital']-before_cap['capital']:+,}")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DARMA HOME + KHORSHID SET EXACTLY TO DAY-3 PHYSICAL FILES V32"))
