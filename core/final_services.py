from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Avg, Sum

from .darma_cost_v55 import darma_cost_for
from .finance import sale_line_metrics
from .inventory_valuation_v17 import finished_inventory_value_v17
from .models import (
    Account, AccountEntry, AppSetting, BankTransfer, Brand, DigikalaSettlement,
    ElasticBalance, ElasticMovement, Expense, FabricRoll, InventoryAdjustment,
    InventoryMovement, PedramPayment, ProductComposition, ProductSize,
    ProductionBatch, ProductionReceipt, ReturnRecord, SaleAllocation, SaleLine,
    SaleShortage, StockBalance, StockLocation, StockTransfer, SupplierAccount,
    SupplierEntry, TakvinPayment, TakvinPurchase,
)


def setting_decimal(key, default=0):
    value = AppSetting.objects.filter(key=key).values_list("value", flat=True).first()
    try: return Decimal(str(value if value not in (None, "") else default))
    except Exception: return Decimal(str(default))


def _round(value): return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def account_balance(account_or_key):
    account = account_or_key if isinstance(account_or_key, Account) else Account.objects.get(key=account_or_key)
    entries = account.entries.aggregate(v=Sum("delta"))["v"] or 0
    legacy_in = account.in_movements.aggregate(v=Sum("amount"))["v"] or 0
    legacy_out = account.out_movements.aggregate(v=Sum("amount"))["v"] or 0
    return int(account.opening_balance or 0) + int(entries) + int(legacy_in) - int(legacy_out)


def supplier_balance(supplier): return int(supplier.opening_balance or 0) + int(supplier.entries.aggregate(v=Sum("delta"))["v"] or 0)


def _replace_account_entry(*, account_key, date, delta, title, reference, entry_type="", note=""):
    account = Account.objects.get(key=account_key)
    AccountEntry.objects.filter(account=account, reference=reference).delete()
    if delta:
        AccountEntry.objects.create(account=account,date=date,delta=int(delta),title=title,reference=reference,entry_type=entry_type,note=note or "")


def _stock(*, brand, size, color, location):
    obj, _ = StockBalance.objects.get_or_create(brand=brand,size=size,color=color,location=location,defaults={"qty":0})
    return StockBalance.objects.select_for_update().get(pk=obj.pk)


def _record_stock(*, movement_type, brand, size, color, location, delta, reference):
    InventoryMovement.objects.create(movement_type=movement_type,brand=brand,size=size,color=color,location=location,delta=int(delta),reference=reference[:120])


def _transfer_for_need(*, brand, size, color, needed, reference):
    """Return HOME stock only; sales must never move KHORSHID automatically.

    Negative HOME stock is intentional. Physical KHORSHID -> HOME movement happens
    only through an explicit StockTransfer entered by the user.
    """
    home = StockLocation.objects.get(key=StockLocation.HOME)
    return _stock(brand=brand,size=size,color=color,location=home)


@transaction.atomic
def sync_sale_inventory(line):
    line = SaleLine.objects.select_for_update().select_related("day","product_size__product__brand","product_size__size").get(pk=line.pk)
    product=line.product_size.product; brand=product.brand; size=line.product_size.size
    home=StockLocation.objects.get(key=StockLocation.HOME); ref=f"sale:{line.id}"
    previous_choices={s.source_color_id:(s.resolved,s.target_color_id) for s in line.shortages.all().order_by("id")}
    for alloc in list(line.allocations.select_related("color","location").all()):
        bal=_stock(brand=brand,size=size,color=alloc.color,location=alloc.location); bal.qty += alloc.qty; bal.save(update_fields=["qty"])
        _record_stock(movement_type=InventoryMovement.ADJUST,brand=brand,size=size,color=alloc.color,location=alloc.location,delta=alloc.qty,reference=f"{ref}:recalc")
    line.allocations.all().delete(); line.shortages.all().delete()
    if line.quantity <= 0:
        line.inventory_applied_quantity=0; line.save(update_fields=["inventory_applied_quantity"]); return {"shortages":[],"transferred":0}
    transferred=0; created_shortages=[]
    for comp in ProductComposition.objects.filter(product=product).select_related("color"):
        needed=int(line.quantity)*int(comp.qty)
        before=_stock(brand=brand,size=size,color=comp.color,location=home).qty
        source_bal=_transfer_for_need(brand=brand,size=size,color=comp.color,needed=needed,reference=f"{ref}:auto-transfer:{comp.color_id}")
        transferred += max(0, source_bal.qty-before)
        available=max(0,source_bal.qty)
        if available >= needed:
            source_bal.qty -= needed; source_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(sale_line=line,color=comp.color,location=home,qty=needed)
            _record_stock(movement_type=InventoryMovement.SALE,brand=brand,size=size,color=comp.color,location=home,delta=-needed,reference=ref); continue
        source_take=available; shortage=needed-source_take; choice=previous_choices.get(comp.color_id)
        if source_take:
            source_bal.qty -= source_take; source_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(sale_line=line,color=comp.color,location=home,qty=source_take)
            _record_stock(movement_type=InventoryMovement.SALE,brand=brand,size=size,color=comp.color,location=home,delta=-source_take,reference=ref)
        if choice and choice[0] and choice[1]:
            target=comp.color.__class__.objects.get(pk=choice[1])
            target_bal=_transfer_for_need(brand=brand,size=size,color=target,needed=shortage,reference=f"{ref}:replacement-transfer:{target.id}")
            target_available=max(0,target_bal.qty); target_bal.qty -= shortage; target_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(sale_line=line,color=target,location=home,qty=shortage,is_replacement=True)
            _record_stock(movement_type=InventoryMovement.SALE,brand=brand,size=size,color=target,location=home,delta=-shortage,reference=f"{ref}:replacement")
            if target_available < shortage:
                extra=SaleShortage.objects.create(sale_line=line,source_color=target,qty=shortage-target_available,resolved=False); created_shortages.append(extra)
        else:
            source_bal.qty -= shortage; source_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(sale_line=line,color=comp.color,location=home,qty=shortage)
            _record_stock(movement_type=InventoryMovement.SALE,brand=brand,size=size,color=comp.color,location=home,delta=-shortage,reference=ref)
            resolved_none=bool(choice and choice[0] and not choice[1])
            shortage_obj=SaleShortage.objects.create(sale_line=line,source_color=comp.color,qty=shortage,resolved=resolved_none,target_color=None)
            if not resolved_none: created_shortages.append(shortage_obj)
    line.inventory_applied_quantity=line.quantity; line.save(update_fields=["inventory_applied_quantity"])
    return {"shortages":created_shortages,"transferred":transferred}


def sync_sale_finance(line):
    ref=f"sale:{line.id}:digikala"
    if line.quantity <= 0: AccountEntry.objects.filter(reference=ref).delete(); return
    metrics=sale_line_metrics(line); net_receivable=metrics["gross"]-metrics["digikala_fee"]
    _replace_account_entry(account_key=Account.DIGIKALA,date=line.day.date,delta=net_receivable,title=f"طلب فروش {line.product_size.product.code} / {line.product_size.size.name}",reference=ref,entry_type="sale")


@transaction.atomic
def sync_sale(line):
    result=sync_sale_inventory(line); sync_sale_finance(line); return result


@transaction.atomic
def resolve_shortage(shortage,target_color=None,keep_negative=False):
    shortage=SaleShortage.objects.select_for_update().select_related("sale_line").get(pk=shortage.pk)
    shortage.resolved=True; shortage.target_color=None if keep_negative else target_color; shortage.save(update_fields=["resolved","target_color"])
    return sync_sale(shortage.sale_line)


@transaction.atomic
def sync_stock_transfer(obj):
    if obj.applied: return
    src=_stock(brand=obj.brand,size=obj.size,color=obj.color,location=obj.from_location); dst=_stock(brand=obj.brand,size=obj.size,color=obj.color,location=obj.to_location)
    src.qty -= obj.qty; dst.qty += obj.qty; src.save(update_fields=["qty"]); dst.save(update_fields=["qty"]); ref=f"manual-transfer:{obj.id}"
    _record_stock(movement_type=InventoryMovement.TRANSFER,brand=obj.brand,size=obj.size,color=obj.color,location=obj.from_location,delta=-obj.qty,reference=ref)
    _record_stock(movement_type=InventoryMovement.TRANSFER,brand=obj.brand,size=obj.size,color=obj.color,location=obj.to_location,delta=obj.qty,reference=ref)
    obj.applied=True; obj.save(update_fields=["applied"])


@transaction.atomic
def sync_inventory_adjustment(obj):
    if obj.applied: return
    bal=_stock(brand=obj.brand,size=obj.size,color=obj.color,location=obj.location); bal.qty += obj.delta; bal.save(update_fields=["qty"])
    _record_stock(movement_type=InventoryMovement.ADJUST,brand=obj.brand,size=obj.size,color=obj.color,location=obj.location,delta=obj.delta,reference=f"adjust:{obj.id}")
    obj.applied=True; obj.save(update_fields=["applied"])


@transaction.atomic
def sync_takvin_purchase(obj):
    if obj.applied: return
    obj.net_unit_price=_round(Decimal(obj.list_unit_price)*(Decimal("1")-Decimal(obj.discount_percent)/Decimal("100"))); obj.total_cost=int(obj.qty)*int(obj.net_unit_price)
    brand=Brand.objects.get(name="تکوین"); home=StockLocation.objects.get(key=StockLocation.HOME); bal=_stock(brand=brand,size=obj.size,color=obj.color,location=home)
    bal.qty += obj.qty; bal.save(update_fields=["qty"]); _record_stock(movement_type=InventoryMovement.PURCHASE,brand=brand,size=obj.size,color=obj.color,location=home,delta=obj.qty,reference=f"takvin-purchase:{obj.id}")
    _replace_account_entry(account_key=Account.TAKVIN,date=obj.date,delta=obj.total_cost,title=f"خرید تکوین {obj.color.name} / {obj.size.name}",reference=f"takvin-purchase:{obj.id}",entry_type="purchase")
    obj.applied=True; obj.save(update_fields=["net_unit_price","total_cost","applied"])


def sync_takvin_payment(obj):
    ref=f"takvin-payment:{obj.id}"
    _replace_account_entry(account_key=Account.MELAT,date=obj.date,delta=-obj.amount,title="پرداخت به تکوین",reference=ref+":melat",entry_type="payment",note=obj.note)
    _replace_account_entry(account_key=Account.TAKVIN,date=obj.date,delta=-obj.amount,title="تسویه تکوین",reference=ref+":takvin",entry_type="payment",note=obj.note)


def sync_expense(obj): _replace_account_entry(account_key=Account.MELAT,date=obj.date,delta=-obj.amount,title=f"خرج: {obj.title}",reference=f"expense:{obj.id}",entry_type="expense",note=obj.note)

def sync_bank_transfer(obj):
    _replace_account_entry(account_key=obj.from_account.key,date=obj.date,delta=-obj.amount,title=f"انتقال به {obj.to_account.title}",reference=f"bank-transfer:{obj.id}:out",entry_type="transfer",note=obj.note)
    _replace_account_entry(account_key=obj.to_account.key,date=obj.date,delta=obj.amount,title=f"انتقال از {obj.from_account.title}",reference=f"bank-transfer:{obj.id}:in",entry_type="transfer",note=obj.note)


def sync_digikala_settlement(obj):
    _replace_account_entry(account_key=Account.DIGIKALA,date=obj.date,delta=-obj.amount,title="تسویه دیجی‌کالا",reference=f"digikala-settlement:{obj.id}:dg",entry_type="settlement",note=obj.note)
    _replace_account_entry(account_key=Account.MELAT,date=obj.date,delta=obj.amount,title="واریز دیجی‌کالا",reference=f"digikala-settlement:{obj.id}:melat",entry_type="settlement",note=obj.note)


def sync_pedram_payment(obj):
    _replace_account_entry(account_key=Account.MELAT,date=obj.date,delta=-obj.amount,title="پرداخت به پدرام",reference=f"pedram-payment:{obj.id}:melat",entry_type="advance",note=obj.note)
    _replace_account_entry(account_key=Account.PEDRAM,date=obj.date,delta=obj.amount,title="پیش‌پرداخت/طلب از پدرام",reference=f"pedram-payment:{obj.id}:pedram",entry_type="advance",note=obj.note)


@transaction.atomic
def sync_fabric_roll(obj):
    if obj.finance_applied: return
    value=obj.total_value
    if obj.paid_from_mellat: _replace_account_entry(account_key=Account.MELAT,date=obj.purchase_date,delta=-value,title=f"خرید پارچه {obj.code}",reference=f"fabric:{obj.id}:melat",entry_type="material_purchase",note=obj.note)
    elif obj.supplier_name:
        supplier,_=SupplierAccount.objects.get_or_create(name=obj.supplier_name); SupplierEntry.objects.create(date=obj.purchase_date,supplier=supplier,delta=value,title=f"خرید پارچه {obj.code}",reference=f"fabric:{obj.id}",note=obj.note)
    obj.finance_applied=True; obj.save(update_fields=["finance_applied"])


@transaction.atomic
def sync_elastic_movement(obj):
    if obj.applied: return
    elastic=ElasticBalance.objects.select_for_update().get(pk=obj.elastic_id); q=Decimal(obj.qty_kg)
    if obj.kind==ElasticMovement.PURCHASE:
        elastic.warehouse_kg += q
        if obj.unit_cost: elastic.unit_cost=obj.unit_cost
        cost=_round(q*Decimal(obj.unit_cost or elastic.unit_cost or 0))
        if cost: _replace_account_entry(account_key=Account.MELAT,date=obj.date,delta=-cost,title=f"خرید کش {elastic.name}",reference=f"elastic:{obj.id}:melat",entry_type="material_purchase",note=obj.note)
    elif obj.kind==ElasticMovement.TRANSFER: elastic.warehouse_kg -= q; elastic.pedram_kg += q
    elif obj.kind==ElasticMovement.CONSUME: elastic.pedram_kg -= q
    else: elastic.warehouse_kg += q
    elastic.save(update_fields=["warehouse_kg","pedram_kg","unit_cost"]); obj.applied=True; obj.save(update_fields=["applied"])


@transaction.atomic
def prepare_batch(batch):
    if batch.fabric_roll and batch.fabric_roll.location==FabricRoll.WAREHOUSE: batch.fabric_roll.location=FabricRoll.PEDRAM; batch.fabric_roll.save(update_fields=["location"])


@transaction.atomic
def close_batch(batch):
    batch.closed=True; batch.save(update_fields=["closed"])
    if batch.fabric_roll: batch.fabric_roll.location=FabricRoll.CONSUMED; batch.fabric_roll.save(update_fields=["location"])


@transaction.atomic
def sync_production_receipt(obj):
    if obj.applied: return
    brand=Brand.objects.get(name="دارما"); bal=_stock(brand=brand,size=obj.size,color=obj.color,location=obj.destination); bal.qty += obj.qty; bal.save(update_fields=["qty"])
    _record_stock(movement_type=InventoryMovement.PRODUCTION,brand=brand,size=obj.size,color=obj.color,location=obj.destination,delta=obj.qty,reference=f"production:{obj.id}")
    obj.labor_total=_round(Decimal(obj.qty)*setting_decimal("pedram_dozen_wage",110000)/Decimal("12"))
    _replace_account_entry(account_key=Account.PEDRAM,date=obj.date,delta=-obj.labor_total,title=f"مزد تولید {obj.batch.code}",reference=f"production:{obj.id}:pedram",entry_type="labor",note=obj.note)
    obj.applied=True; obj.save(update_fields=["labor_total","applied"])


@transaction.atomic
def sync_return(obj):
    if obj.applied: return
    ps=obj.product_size
    if obj.add_back_inventory:
        home=StockLocation.objects.get(key=StockLocation.HOME)
        for comp in ProductComposition.objects.filter(product=ps.product).select_related("color"):
            units=int(obj.qty)*int(comp.qty); bal=_stock(brand=ps.product.brand,size=ps.size,color=comp.color,location=home); bal.qty += units; bal.save(update_fields=["qty"])
            _record_stock(movement_type=InventoryMovement.ADJUST,brand=ps.product.brand,size=ps.size,color=comp.color,location=home,delta=units,reference=f"return:{obj.id}")
    if obj.refund_amount: _replace_account_entry(account_key=Account.DIGIKALA,date=obj.date,delta=-obj.refund_amount,title=f"مرجوعی {ps.product.code}",reference=f"return:{obj.id}:digikala",entry_type="return",note=obj.note)
    obj.applied=True; obj.save(update_fields=["applied"])


def inventory_unit_cost(brand,size):
    if brand.name=="دارما": return int(darma_cost_for())
    latest=TakvinPurchase.objects.filter(size=size).order_by("-date","-id").values_list("net_unit_price",flat=True).first()
    if latest: return int(latest)
    avg=ProductSize.objects.filter(product__brand=brand,size=size,active=True).aggregate(v=Avg("unit_cost"))["v"]; return int(avg or 0)


def finished_inventory_value(): return int(finished_inventory_value_v17())


def raw_material_value():
    fabric=sum(r.total_value for r in FabricRoll.objects.exclude(location=FabricRoll.CONSUMED)); elastic=0
    for e in ElasticBalance.objects.all(): elastic += _round((Decimal(e.warehouse_kg)+Decimal(e.pedram_kg))*Decimal(e.unit_cost or 0))
    return int(fabric+elastic)


def production_batch_metrics(batch):
    receipts=batch.receipts.all(); actual_qty=receipts.aggregate(v=Sum("qty"))["v"] or 0; labor=receipts.aggregate(v=Sum("labor_total"))["v"] or 0; fabric=batch.fabric_roll.total_value if batch.fabric_roll else 0
    elastic=_round(Decimal(batch.elastic16_used_kg)*Decimal(batch.elastic16_unit_cost or 0)+Decimal(batch.elastic25_used_kg)*Decimal(batch.elastic25_unit_cost or 0)); actual_cost=(fabric+elastic+labor)/actual_qty if actual_qty else 0
    return {"actual_qty":actual_qty,"labor":labor,"fabric":fabric,"elastic":elastic,"actual_unit_cost":actual_cost,"variance":actual_qty-int(batch.expected_qty or 0)}