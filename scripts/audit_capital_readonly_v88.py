"""Read-only, privacy-minimized capital audit for the running Darma database.

Run inside Django's existing web container with:
    python manage.py shell -v 0 -c 'exec(__import__("sys").stdin.read())'
and pipe this file into stdin. Prints ONE JSON object on stdout.
No migrations, model saves, updates, raw notes, credentials or customer data.
PostgreSQL transaction is explicitly READ ONLY.
"""
import json
import os
import sys
from collections import defaultdict
from decimal import Decimal
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from core.dateutils import format_jalali, parse_jalali_date
from core.darma_cost_v55 import darma_cost_for
from core.novani_cost_v59 import novani_cost_for
from core.takvin_pricing_v17 import takvin_cost_for
from core.finance import sale_line_metrics
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.report_v5 import _raw_material_context
from core.self_spend_v62 import is_self_tracking_row
from core.dia_gallery_v45 import DIA_GALLERY_UNIT_PRICE
from core.material_purchase_v14 import purchase_data_for_payment
from core.business_tools_v60 import _invoice_value
from core.models import (
    Account, AccountEntry, AppSetting, BusinessPayment, DiaGallerySale,
    DigikalaSettlement, ExcelManualRow, ExcelManualSetting,
    InventoryAdjustment, InventoryModelCost, InventoryMovement,
    MaterialReportBlock, MoneyMovement, RawMaterialStock,
    SaleLine, SaleSnapshot, StockBalance, StockTransfer, TakvinPurchase,
    TailorBalanceEntry,
)


def iso(value):
    return value.isoformat() if value is not None else None


def i(value):
    return int(value or 0)


def dec(value):
    return str(value if value is not None else 0)


def brief_purchase(value):
    if not isinstance(value, dict):
        return None
    selected = ("k", "m", "t", "q", "p", "q16", "p16", "q25", "p25")
    payload = {k: value[k] for k in selected if k in value}
    if isinstance(value.get("items"), list):
        payload["items"] = [
            {k: item[k] for k in selected if k in item}
            for item in value["items"] if isinstance(item, dict)
        ]
    # Exclude notes and free-text bank/supplier information.
    return payload


def build_report(as_of):
    findings = []
    account_rows = []
    capital_accounts = 0
    capital_persons = 0
    capital_assets = 0
    by_title = defaultdict(list)
    rows = ExcelManualRow.objects.all().order_by("section", "sort_order", "id")
    for row in rows:
        included = bool(row.active and row.section in ("accounts", "persons", "assets") and not is_self_tracking_row(row))
        if included:
            if row.section == "accounts":
                capital_accounts += i(row.amount)
            elif row.section == "persons":
                capital_persons += i(row.amount)
            elif row.section == "assets":
                capital_assets += i(row.amount)
        account_rows.append({
            "id": row.id, "section": row.section, "title": row.title,
            "amount": i(row.amount), "active": bool(row.active),
            "included_in_capital": included,
            "system_self_tracker": bool(is_self_tracking_row(row)),
            "unit_price": i(row.unit_price), "quantity": dec(row.quantity),
            "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
        })
        if included:
            normalized = " ".join((row.title or "").replace("ي", "ی").replace("ك", "ک").split()).lower()
            by_title[(row.section, normalized)].append(row.id)
    for (section, title), ids in by_title.items():
        if title and len(ids) > 1:
            findings.append({"kind": "potential_duplicate_manual_title", "section": section, "title": title, "row_ids": ids})

    manual_settings = []
    manual_setting_map = {}
    for item in ExcelManualSetting.objects.all().order_by("key"):
        if item.key not in ("digikala_receivable", "takvin_debt"):
            continue
        manual_setting_map[item.key] = i(item.value)
        manual_settings.append({
            "key": item.key, "value": i(item.value),
            "updated_at": iso(item.updated_at),
        })
    debt = manual_setting_map.get("takvin_debt", 0)
    digikala_base = manual_setting_map.get("digikala_receivable", 0)

    app_settings = []
    allowed_financial = {
        "digikala_commission_percent", "digikala_processing_percent",
        "digikala_processing_floor", "digikala_vat_percent",
        "digikala_floor_taxable_part", "darma_accounting_unit_cost",
    }
    for row in AppSetting.objects.all().order_by("key"):
        if row.key in allowed_financial or row.key.startswith(("darma_cost_rule_", "novani_cost_rule_")):
            app_settings.append({"key": row.key, "value": row.value, "updated_at": iso(row.updated_at)})

    cost_map = {
        (r.brand_id, r.color_id, r.size_id): i(r.unit_cost)
        for r in InventoryModelCost.objects.all()
    }
    darma_cost = i(darma_cost_for())
    novani_cost = i(novani_cost_for())
    takvin_costs = {}
    stock_rows = []
    stock_total = 0
    stock_brand_totals = defaultdict(lambda: {"qty": 0, "capital_value": 0})
    stock_balances = StockBalance.objects.select_related(
        "brand", "color", "size", "location"
    ).order_by("brand__name", "color__name", "size__name", "location__key", "id")
    for row in stock_balances:
        brand, size = row.brand.name, row.size.name
        if brand == "دارما":
            cost = darma_cost
        elif brand == "Novani":
            cost = novani_cost
        elif brand == "تکوین":
            if size not in takvin_costs:
                takvin_costs[size] = i(takvin_cost_for(size))
            cost = takvin_costs[size]
        else:
            cost = cost_map.get((row.brand_id, row.color_id, row.size_id), 0)
        included = brand != "انبارش"
        value = i(row.qty) * cost if included else 0
        stock_total += value
        if included:
            stock_brand_totals[brand]["qty"] += i(row.qty)
        stock_brand_totals[brand]["capital_value"] += value
        stock_rows.append({
            "id": row.id, "brand": brand, "color": row.color.name,
            "size": size, "location": row.location.key, "qty": i(row.qty),
            "unit_cost": cost, "included_in_capital": included, "capital_value": value,
        })
    valuation_function_total = i(finished_inventory_value_v17())
    if stock_total != valuation_function_total:
        findings.append({
            "kind": "stock_valuation_mismatch", "independent": stock_total,
            "existing_function": valuation_function_total,
        })

    movement_rows = []
    movement_types = defaultdict(lambda: {"rows": 0, "net_qty": 0})
    for r in InventoryMovement.objects.select_related("brand", "color", "size", "location").all().order_by("id"):
        movement_types[r.movement_type]["rows"] += 1
        movement_types[r.movement_type]["net_qty"] += i(r.delta)
        movement_rows.append({
            "id": r.id, "created_at": iso(r.created_at),
            "type": r.movement_type, "brand": r.brand.name, "color": r.color.name,
            "size": r.size.name, "location": r.location.key,
            "delta": i(r.delta), "reference": r.reference,
        })
    movement_opening = []
    named_net = defaultdict(int)
    for r in movement_rows:
        named_net[(r["brand"], r["color"], r["size"], r["location"])] += r["delta"]
    for row in stock_rows:
        label = (row["brand"], row["color"], row["size"], row["location"])
        implied_opening = row["qty"] - named_net.get(label, 0)
        if implied_opening:
            movement_opening.append({
                "brand": row["brand"], "color": row["color"], "size": row["size"],
                "location": row["location"], "current_qty": row["qty"],
                "movement_net_since_history_start": named_net.get(label, 0),
                "implied_unlogged_opening": implied_opening,
            })
    for k, net in named_net.items():
        if not any(
            r["brand"] == k[0] and r["color"] == k[1] and
            r["size"] == k[2] and r["location"] == k[3]
            for r in stock_rows
        ) and net:
            movement_opening.append({
                "brand": k[0], "color": k[1], "size": k[2], "location": k[3],
                "current_qty": 0, "movement_net_since_history_start": net,
                "implied_unlogged_opening": -net,
            })

    raw_rows = []
    raw_total = 0
    raw_by_bucket = defaultdict(lambda: {"quantity_kg": Decimal("0"), "value": 0, "rows": 0})
    for row in RawMaterialStock.objects.all().order_by("kind", "location", "id"):
        active = bool(row.active)
        value = i(row.total_value) if active else 0
        raw_total += value
        if active:
            bucket = raw_by_bucket[(row.kind, row.location)]
            bucket["quantity_kg"] += Decimal(row.quantity or 0)
            bucket["value"] += value
            bucket["rows"] += 1
        raw_rows.append({
            "id": row.id, "kind": row.kind, "location": row.location,
            "material_key": row.material_key, "title": row.title,
            "variant": row.variant, "quantity_kg": dec(row.quantity),
            "unit_price": i(row.unit_price), "row_value": value,
            "active": active, "created_at": iso(row.created_at),
            "updated_at": iso(row.updated_at),
        })
    raw_function_total = i(_raw_material_context()["materials_total"])
    if raw_total != raw_function_total:
        findings.append({
            "kind": "raw_material_valuation_mismatch",
            "independent": raw_total, "existing_function": raw_function_total,
        })

    accounts = []
    account_by_key = {}
    for row in Account.objects.all().order_by("key"):
        account_by_key[row.key] = row
        accounts.append({
            "key": row.key, "title": row.title,
            "opening_balance": i(row.opening_balance),
        })

    all_entries = []
    ledger_totals = defaultdict(int)
    by_account_type = defaultdict(int)
    entry_index = defaultdict(list)
    for row in AccountEntry.objects.select_related("account").all().order_by("date", "id"):
        ledger_totals[row.account.key] += i(row.delta)
        by_account_type[(row.account.key, row.entry_type or "")] += i(row.delta)
        entry = {
            "id": row.id, "date": iso(row.date),
            "account": row.account.key, "delta": i(row.delta),
            "entry_type": row.entry_type, "reference": row.reference,
            "created_at": iso(row.created_at),
        }
        all_entries.append(entry)
        entry_index[(row.account.key, row.reference)].append(entry)
    digikala_included = sum(
        r["delta"] for r in all_entries if r["account"] == "digikala"
        and r["entry_type"] in ("sale", "receipt")
    )
    digikala_total = digikala_base + digikala_included
    dia_total = i(account_by_key.get("dia_gallery").opening_balance) if account_by_key.get("dia_gallery") else 0
    dia_total += ledger_totals.get("dia_gallery", 0)
    unrelated_digikala_entries = [
        r for r in all_entries if r["account"] == "digikala"
        and r["entry_type"] not in ("sale", "receipt")
    ]

    sales = []
    sale_gross = sale_fee = sale_cogs = sale_profit = 0
    sale_expected_receivable = 0
    all_sale_ids = set()
    for row in SaleLine.objects.filter(quantity__gt=0).select_related(
        "day", "product_size__product__brand", "product_size__size"
    ).prefetch_related("product_size__product__composition__color").order_by("day__date", "id"):
        metrics = sale_line_metrics(row)
        net = i(metrics["gross"]) - i(metrics["digikala_fee"])
        sale_gross += i(metrics["gross"])
        sale_fee += i(metrics["digikala_fee"])
        sale_cogs += i(metrics["cogs"])
        sale_profit += i(metrics["profit"])
        sale_expected_receivable += net
        ref = "sale:%s:digikala" % row.id
        recorded = entry_index.get(("digikala", ref), [])
        seen = sum(x["delta"] for x in recorded if x["entry_type"] == "sale")
        try:
            snap = row.snapshot
        except SaleSnapshot.DoesNotExist:
            snap = None
        item = {
            "id": row.id, "date": iso(row.day.date),
            "brand": row.product_size.product.brand.name,
            "product": row.product_size.product.code,
            "size": row.product_size.size.name,
            "packs": i(row.quantity), "shorts": i(metrics["shorts"]),
            "applied_packs": i(row.inventory_applied_quantity),
            "sale_price_per_pack": i(row.sale_price),
            "gross": i(metrics["gross"]), "fee": i(metrics["digikala_fee"]),
            "cogs": i(metrics["cogs"]), "profit": i(metrics["profit"]),
            "expected_digikala_receivable": net,
            "ledger_digikala_receivable": seen,
            "ledger_ids": [x["id"] for x in recorded],
            "snapshot": None if snap is None else {
                "pack_qty": i(snap.pack_qty),
                "unit_cost": i(snap.unit_cost),
                "digikala_fee_unit": i(snap.digikala_fee_unit),
            },
        }
        sales.append(item)
        all_sale_ids.add(row.id)
        if net != seen or len([x for x in recorded if x["entry_type"] == "sale"]) != (1 if net else 0):
            findings.append({
                "kind": "sale_digikala_ledger_mismatch",
                "sale_line_id": row.id, "expected": net,
                "recorded": seen, "entry_ids": item["ledger_ids"],
            })
        if row.inventory_applied_quantity != row.quantity:
            findings.append({
                "kind": "sale_inventory_applied_qty_mismatch",
                "sale_line_id": row.id, "quantity": i(row.quantity),
                "applied": i(row.inventory_applied_quantity),
            })
    orphan_digikala_sales = [
        row for row in all_entries if row["account"] == "digikala"
        and row["entry_type"] == "sale"
        and row["reference"].startswith("sale:")
        and (
            not row["reference"].endswith(":digikala")
            or not row["reference"][5:-9].isdigit()
            or int(row["reference"][5:-9]) not in all_sale_ids
        )
    ]

    dia_sales = []
    dia_expected_receivable = 0
    for row in DiaGallerySale.objects.filter(quantity__gt=0).select_related("day", "color", "size").order_by("day__date", "id"):
        expected = i(row.quantity) * i(DIA_GALLERY_UNIT_PRICE)
        recorded = entry_index.get(("dia_gallery", "dia-gallery:%s:receivable" % row.id), [])
        seen = sum(x["delta"] for x in recorded if x["entry_type"] == "dia_gallery_sale")
        dia_expected_receivable += expected
        dia_sales.append({
            "id": row.id, "date": iso(row.day.date),
            "color": row.color.name, "size": row.size.name,
            "quantity": i(row.quantity), "applied_quantity": i(row.inventory_applied_quantity),
            "unit_price": i(row.unit_price), "unit_cost": i(row.unit_cost),
            "expected_receivable": expected, "recorded_receivable": seen,
            "ledger_ids": [x["id"] for x in recorded],
        })
        if seen != expected:
            findings.append({
                "kind": "dia_ledger_mismatch", "dia_sale_id": row.id,
                "expected": expected, "recorded": seen,
            })
        if i(row.quantity) != i(row.inventory_applied_quantity):
            findings.append({"kind": "dia_inventory_applied_mismatch", "dia_sale_id": row.id})

    settlements = []
    for row in DigikalaSettlement.objects.all().order_by("date", "id"):
        source = row.source or "digikala"
        account_key = "dia_gallery" if source == "dia_gallery" else "digikala"
        suffix = "dia-gallery" if source == "dia_gallery" else "digikala"
        ref = "receipt:%s:%s" % (row.id, suffix)
        matching = entry_index.get((account_key, ref), [])
        net = sum(x["delta"] for x in matching if x["entry_type"] == "receipt")
        settlements.append({
            "id": row.id, "date": iso(row.date), "source": source,
            "amount": i(row.amount), "ledger_delta": net,
            "entry_ids": [x["id"] for x in matching],
        })
        if net != -i(row.amount) or len([x for x in matching if x["entry_type"] == "receipt"]) != 1:
            findings.append({
                "kind": "settlement_ledger_mismatch", "settlement_id": row.id,
                "expected_delta": -i(row.amount), "recorded_delta": net,
            })

    # Independently reconstruct each receivable from current active sales,
    # current settlement rows, and the explicitly entered opening/base amount.
    digikala_settled = sum(
        row["amount"] for row in settlements if row["source"] == "digikala"
    )
    dia_settled = sum(
        row["amount"] for row in settlements if row["source"] == "dia_gallery"
    )
    expected_digikala_total = (
        digikala_base + sale_expected_receivable - digikala_settled
    )
    dia_opening = (
        i(account_by_key["dia_gallery"].opening_balance)
        if "dia_gallery" in account_by_key else 0
    )
    expected_dia_total = dia_opening + dia_expected_receivable - dia_settled
    if digikala_total != expected_digikala_total:
        findings.append({
            "kind": "digikala_total_receivable_reconciliation",
            "actual": digikala_total,
            "expected_from_sales_and_settlements": expected_digikala_total,
            "difference": digikala_total - expected_digikala_total,
        })
    if dia_total != expected_dia_total:
        findings.append({
            "kind": "dia_total_receivable_reconciliation",
            "actual": dia_total,
            "expected_from_sales_and_settlements": expected_dia_total,
            "difference": dia_total - expected_dia_total,
        })
    for row in account_rows:
        if not row["included_in_capital"] or row["section"] != "accounts":
            continue
        normalized = (row["title"] or "").replace(" ", "").lower()
        if "دیجی" in normalized or "digikala" in normalized or "dia gallery" in normalized:
            findings.append({
                "kind": "possible_duplicate_receivable_in_manual_accounts",
                "row_id": row["id"], "title": row["title"],
                "amount": row["amount"],
                "warning": "This balance may overlap the separately calculated receivable.",
            })

    purchases = []
    purchase_totals = defaultdict(lambda: {"rows": 0, "invoice_value": 0, "cash_paid": 0})
    for row in BusinessPayment.objects.all().order_by("date", "id"):
        purchase = purchase_data_for_payment(row) if row.payee in ("fabric", "elastic") else None
        invoice = i(_invoice_value(purchase)) if purchase else 0
        purchase_totals[row.payee]["rows"] += 1
        purchase_totals[row.payee]["cash_paid"] += i(row.amount)
        purchase_totals[row.payee]["invoice_value"] += invoice
        purchases.append({
            "id": row.id, "date": iso(row.date),
            "payee": row.payee, "source_account": row.source_account,
            "cash_paid": i(row.amount), "invoice_value": invoice,
            "purchase": brief_purchase(purchase),
            "prepayment_without_invoice": bool(row.payee in ("fabric", "elastic") and not purchase),
            "created_at": iso(row.created_at),
        })
    takvin_purchases = [{
        "id": row.id, "date": iso(row.date),
        "size": row.size.name, "color": row.color.name,
        "qty": i(row.qty), "net_unit_price": i(row.net_unit_price),
        "total_cost": i(row.total_cost), "applied": bool(row.applied),
        "excel_web": bool((row.note or "").startswith("[excel-web]")),
        "created_at": iso(row.created_at),
    } for row in TakvinPurchase.objects.select_related("size", "color").all().order_by("date", "id")]

    production = []
    for row in MaterialReportBlock.objects.select_related("brand").prefetch_related(
        "stock_consumptions", "output_applications"
    ).all().order_by("date", "id"):
        inputs = {}
        for key, v in (row.input_data or {}).items():
            if not isinstance(v, dict) or key == "_meta":
                continue
            inputs[key] = {
                k: v.get(k) for k in (
                    "weight", "cut", "wage", "cost", "elastic16", "remain16",
                    "elastic25", "remain25", "elastic16_key", "elastic25_key",
                ) if k in v
            }
        outputs = {
            key: value for key, value in (row.output_data or {}).items()
            if isinstance(value, dict)
        }
        production.append({
            "id": row.id, "date": iso(row.date), "brand": row.brand.name,
            "delivery_wage": i(row.delivery_wage),
            "inputs": inputs, "outputs": outputs,
            "consumption": [{
                "kind": x.kind, "material_key": x.material_key,
                "variant": x.variant, "quantity": dec(x.quantity),
            } for x in row.stock_consumptions.all()],
            "applied_output": [{
                "model_key": x.model_key, "size_key": x.size_key,
                "quantity": i(x.quantity), "updated_at": iso(x.updated_at),
            } for x in row.output_applications.all()],
            "updated_at": iso(row.updated_at),
        })

    inventory_adjustments = [{
        "id": row.id, "date": iso(row.date), "brand": row.brand.name,
        "color": row.color.name, "size": row.size.name,
        "location": row.location.key, "delta": i(row.delta),
        "applied": bool(row.applied),
        "created_at": iso(row.created_at),
    } for row in InventoryAdjustment.objects.select_related(
        "brand", "color", "size", "location"
    ).all().order_by("date", "id")]
    stock_transfers = [{
        "id": row.id, "date": iso(row.date), "brand": row.brand.name,
        "color": row.color.name, "size": row.size.name,
        "from": row.from_location.key, "to": row.to_location.key,
        "qty": i(row.qty), "applied": bool(row.applied),
        "created_at": iso(row.created_at),
    } for row in StockTransfer.objects.select_related(
        "brand", "color", "size", "from_location", "to_location"
    ).all().order_by("date", "id")]

    money_movements = [{
        "id": row.id, "date": iso(row.date),
        "kind": row.kind, "amount": i(row.amount),
        "from_account": row.from_account.key if row.from_account_id else None,
        "to_account": row.to_account.key if row.to_account_id else None,
        "title": row.title if row.title.startswith(
            ("material-purchase:", "material-prepayment:", "material-settlement:")
        ) else "(redacted)",
        "affects_capital": bool(row.affects_capital),
        "created_at": iso(row.created_at),
    } for row in MoneyMovement.objects.select_related(
        "from_account", "to_account"
    ).all().order_by("date", "id")]
    tailor_entries = [{
        "id": row.id, "date": iso(row.date), "delta": i(row.delta),
        "reference": row.reference, "created_at": iso(row.created_at),
    } for row in TailorBalanceEntry.objects.all().order_by("date", "id")]

    current_formula = (
        capital_accounts + capital_persons + dia_total + stock_total
        + raw_total + digikala_total - debt + capital_assets
    )
    components = {
        "accounts_manual_excluding_self_tracker": capital_accounts,
        "persons_manual": capital_persons,
        "dia_gallery_receivable": dia_total,
        "accounts_total": capital_accounts + capital_persons + dia_total,
        "finished_inventory": stock_total,
        "raw_materials": raw_total,
        "digikala_receivable_base": digikala_base,
        "digikala_receivable_ledger": digikala_included,
        "digikala_receivable": digikala_total,
        "takvin_debt": debt,
        "capital_assets": capital_assets,
        "total_capital": current_formula,
    }
    report = {
        "audit_version": "v88-readonly-1",
        "generated_at": iso(timezone.now()),
        "as_of_jalali": format_jalali(as_of),
        "as_of_gregorian": iso(as_of),
        "database_engine": connection.vendor,
        "important_scope": (
            "All records are from the CURRENT live database. Current capital formula "
            "is reproduced independently. Historical values are not implied by "
            "dated records where manual balances were overwritten."
        ),
        "summary": components,
        "verification": {
            "independent_current_capital": current_formula,
            "existing_finished_inventory_function": valuation_function_total,
            "existing_raw_material_function": raw_function_total,
            "sale_totals": {
                "gross": sale_gross, "fee": sale_fee, "cogs": sale_cogs,
                "profit": sale_profit,
                "expected_gross_less_fee_receivable_from_active_sales": sale_expected_receivable,
            },
            "dia_active_sale_expected_receivable": dia_expected_receivable,
            "receivable_reconciliation": {
                "digikala": {
                    "opening_base": digikala_base,
                    "active_sales_net": sale_expected_receivable,
                    "recorded_settlements": digikala_settled,
                    "expected": expected_digikala_total,
                    "actual": digikala_total,
                    "difference": digikala_total - expected_digikala_total,
                },
                "dia_gallery": {
                    "account_opening": dia_opening,
                    "active_sales_gross": dia_expected_receivable,
                    "recorded_settlements": dia_settled,
                    "expected": expected_dia_total,
                    "actual": dia_total,
                    "difference": dia_total - expected_dia_total,
                },
            },
            "account_entry_totals": dict(ledger_totals),
            "account_entry_by_type": [
                {"account": k[0], "type": k[1], "delta": v}
                for k, v in sorted(by_account_type.items())
            ],
            "raw_material_by_bucket": [
                {"kind": k[0], "location": k[1],
                 "quantity_kg": dec(v["quantity_kg"]),
                 "value": v["value"], "rows": v["rows"]}
                for k, v in sorted(raw_by_bucket.items())
            ],
            "finished_stock_by_brand": dict(stock_brand_totals),
            "inventory_movements_by_type": dict(movement_types),
            "business_payments_by_payee": dict(purchase_totals),
            "implied_unlogged_stock_opening": movement_opening,
            "unrelated_digikala_entries": unrelated_digikala_entries,
            "orphan_digikala_sale_ledger_entries": orphan_digikala_sales,
            "findings": findings,
        },
        "details": {
            "manual_capital_rows": account_rows,
            "manual_financial_settings": manual_settings,
            "cost_and_fee_rules": app_settings,
            "accounts_legacy": accounts,
            "finished_stock": stock_rows,
            "raw_material_stock": raw_rows,
            "inventory_movements": movement_rows,
            "inventory_adjustments": inventory_adjustments,
            "stock_transfers": stock_transfers,
            "account_entries": all_entries,
            "sales": sales,
            "dia_sales": dia_sales,
            "settlements": settlements,
            "business_payments": purchases,
            "takvin_purchases": takvin_purchases,
            "material_reports": production,
            "money_movements": money_movements,
            "tailor_balance_entries": tailor_entries,
        },
    }
    # Historical V87 estimates may NOT include changes to manually overwritten
    # balances, materials production, valuation revisions or pre-deployment data.
    if "digikala" in account_by_key and "digikala_receivable" in manual_setting_map:
        try:
            from core.capital_history_v87 import capital_as_of
            previous = capital_as_of(as_of)
            report["historical_v87_estimate"] = {
                "capital_total": i(previous["capital_total"]),
                "post_period_delta": i(previous.get("post_period_delta")),
                "delta_parts": previous.get("delta_parts", {}),
                "warnings": previous.get("warnings", []),
                "warning": "V87 is an unverified estimate; a zero warning count does not prove historical accuracy.",
            }
        except ImportError:
            report["historical_v87_estimate"] = {
                "available": False,
                "warning": "The running web image does not include the V87 historical resolver.",
            }
        except Exception as exc:
            report["historical_v87_estimate"] = {
                "available": False, "error": str(exc),
                "warning": "Could not calculate the unverified V87 estimate.",
            }
    else:
        report["historical_v87_estimate"] = {
            "available": False,
            "warning": "Missing Digikala account or receivable baseline; historical V87 would try to create records.",
        }
    return report


def main():
    raw_date = os.environ.get("CAPITAL_AUDIT_DATE", "1405/06/15")
    as_of = parse_jalali_date(raw_date)
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
        payload = build_report(as_of)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    print(
        "READ_ONLY_AUDIT_OK capital=%s findings=%s date=%s"
        % (
            payload["summary"]["total_capital"],
            len(payload["verification"]["findings"]),
            payload["as_of_jalali"],
        ),
        file=sys.stderr,
    )


main()
