#!/usr/bin/env python3
"""Read-only reconciliation: factory invoices, home-stock event traces, finance reports.
NO DDL/DML, no stock corrections, no real receipt changes.
"""
import os,sqlite3,sys
sys.path.insert(0,"/app")
from collections import defaultdict
from datetime import date

path=os.environ.get("SALES_DB_PATH","/data/sales.sqlite3")
db=sqlite3.connect("file:"+path+"?mode=ro",uri=True,timeout=30)
db.row_factory=sqlite3.Row
db.execute("PRAGMA query_only=ON")
db.execute("BEGIN")
problems=[]
def query(sql,args=()):return [dict(r) for r in db.execute(sql,args)]
def n(v):return f"{int(v or 0):,}"
def heading(t):print("\n"+"="*76+"\n"+t+"\n"+"="*76)
def audit(ok, text):
    print(("OK   " if ok else "CHECK ")+text)
    if not ok: problems.append(text)
def cols(table):
    return {r["name"] for r in db.execute("PRAGMA table_info("+table+")")}

try:
    from daily_sales_service.sister_finance_logic import sales_report, business_sales_report, overview, sale_lines
    from daily_sales_service.sister_invoices import mehr_balance, mehr_open_items

    heading("A. ALL CUSTOMER INVOICES / HOME INVENTORY IMPACT")
    invoices=query("""SELECT i.id,i.invoice_date,i.origin,i.status,i.is_void,i.version,
         c.name FROM sister_invoices i JOIN sister_invoice_customers c
         ON c.id=i.customer_id ORDER BY i.id""")
    active=[]
    for inv in invoices:
        iid=int(inv["id"])
        lines=query("""SELECT size,master_id,qty,purchase_unit,sale_unit FROM
             sister_invoice_lines WHERE invoice_id=? ORDER BY size""",(iid,))
        raw_events=query("""SELECT e.id,e.master_id,m.size,e.source,e.delta,e.reference
             FROM master_stock_events e LEFT JOIN master_products m
             ON m.id=e.master_id
             WHERE e.reference=? OR e.reference LIKE ? OR e.reference LIKE ?
             ORDER BY e.id""",
             ("sister-invoice:"+str(iid),
              "sister-invoice-correction:"+str(iid)+":%",
              "sister-invoice-origin-factory:"+str(iid)+":%"))
        home_by_sku=defaultdict(int)
        for ev in raw_events:
            if ev["source"]=="home":
                home_by_sku[int(ev["master_id"])]+=int(ev["delta"])
        home_by_sku={k:v for k,v in home_by_sku.items() if v}
        expected={}
        if inv["origin"]=="home" and inv["status"]=="dispatched" and not inv["is_void"]:
            for item in lines:
                if item["master_id"] is not None:
                    mid=int(item["master_id"])
                    expected[mid]=expected.get(mid,0)-int(item["qty"])
        expected={k:v for k,v in expected.items() if v}
        sale=sum(int(x["qty"])*int(x["sale_unit"]) for x in lines)
        cost=sum(int(x["qty"])*int(x["purchase_unit"]) for x in lines)
        refs=query("""SELECT id,kind,debt_delta,credit_delta FROM sister_mehr_ledger
             WHERE reference=?""",("factory-invoice:"+str(iid),))
        should_factory=(inv["origin"]=="factory" and inv["status"]=="dispatched"
                        and not inv["is_void"])
        print(f"\nINVOICE #{iid} {inv['name']} | {inv['invoice_date']} | {inv['origin']}/{inv['status']} void={inv['is_void']}")
        print(f"  Sales {n(sale)} | Procurement snapshot {n(cost)} | home_stock_events={len(raw_events)}")
        for event in raw_events:
            print(f"  STOCK_EVENT #{event['id']} master={event['master_id']} size={event['size']} source={event['source']} change={event['delta']:+} ref={event['reference']}")
        audit(home_by_sku==expected,
              f"invoice #{iid}: net home movements {home_by_sku} match required {expected}")
        if should_factory:
            if any(str(e["reference"]).startswith("sister-invoice-origin-factory:") for e in raw_events):
                original=[e for e in raw_events if str(e["reference"])=="sister-invoice:"+str(iid)]
                reversed_events=[e for e in raw_events if str(e["reference"]).startswith("sister-invoice-origin-factory:")]
                audit(bool(original) and bool(reversed_events),
                      f"invoice #{iid}: corrected factory origin has BOTH original home deduction and reversal events")
            audit(all(x["master_id"] is None for x in lines),
                  f"invoice #{iid}: factory lines do not retain home stock SKU IDs")
            audit(len(refs)==1 and refs[0]["kind"]=="factory_invoice" and
                  int(refs[0]["debt_delta"])==cost and int(refs[0]["credit_delta"])==0,
                  f"invoice #{iid}: EXACTLY ONE factory ledger debt for procurement {n(cost)}")
            active.append((iid,sale,cost))
        elif inv["origin"]=="home":
            audit(len(refs)==0,f"invoice #{iid}: home invoice has NO factory procurement ledger")
    heading("B. MEHR SETTLEMENT AND MODERNA CHECKS")
    ledger=mehr_balance(db)
    items=mehr_open_items(db)
    print("Mehr ledger debt after recorded paid/offset:",n(ledger["debt"]))
    print("Mehr ledger credited customer money:",n(ledger["credit"]))
    print("NET Mehr payable:",n(max(0,-int(ledger["net"]))))
    paid=query("""SELECT id,occurred_on,reference,debt_delta,notes
         FROM sister_mehr_ledger WHERE kind='paid_to_mehr' ORDER BY id""")
    print("All explicit payments to Mehr:",len(paid))
    for p in paid:
        print(f"  settlement #{p['id']} date={p['occurred_on']} amount={n(-int(p['debt_delta']))} ref={p['reference']} note={p['notes']}")
    moderna=query("""SELECT i.id,i.origin,i.status FROM sister_invoices i
      JOIN sister_invoice_customers c ON c.id=i.customer_id
      WHERE c.name LIKE '%مدرنا%'""")
    for inv in moderna:
        iid=int(inv["id"])
        print("MODERNA invoice",iid,"receipt rows:")
        rrs=query("""SELECT id,amount,paid_on,destination,account_id,notes
                      FROM sister_invoice_receipts WHERE invoice_id=? ORDER BY id""",(iid,))
        for r in rrs:
            print(f"  receipt #{r['id']} {r['paid_on']} amount={n(r['amount'])} destination={r['destination']} linked_bank={bool(r['account_id'])} note={r['notes']}")
        item=next((x for x in items if x["kind"]=="invoice" and x["id"]==iid),None)
        print("  Mehr invoice open:",n(item["remaining"]) if item else "not found")
    audit(not any(-int(x["debt_delta"])==35750000 for x in paid),
          "No separate 35,750,000 cash payment to Mehr is recorded (not proof unpaid)")

    heading("C. RECOGNIZED SALES / FINANCE / REPORT RECONCILIATION")
    actual=sale_lines(db)
    invoice_sale_rows=[r for r in actual if r["kind"]=="invoice"]
    ids=[x["sale_id"] for x in invoice_sale_rows]
    audit(len(ids)==len(set(ids)), "No duplicate invoice sale ID in finance sales ledger")
    audit(len(invoice_sale_rows)==len(active),
          f"All {len(active)} factory invoices appear once in finance sale lines")
    audit(sum(x["gross"] for x in invoice_sale_rows)==sum(x[1] for x in active),
          "Finance mold invoice gross matches original invoice sales")
    audit(sum(x["cogs"] or 0 for x in invoice_sale_rows)==sum(x[2] for x in active),
          "Finance mold COGS matches invoice purchase unit price snapshots")
    finance=sales_report(db)
    overall=overview(db)
    audit(finance["gross"]==overall["sales"]["gross"],"Finance home sales gross equals all sales report")
    audit(finance["net"]==overall["sales"]["net"],"Finance home net equals all sales report")
    audit(finance["profit"]==overall["sales"]["profit"],"Finance home profit equals all sales report")
    grouped=business_sales_report(db)
    audit(sum(b["gross"] for b in grouped)==finance["gross"],
          "Sum of business-specific sales equals all sales")
    audit(sum(b["net"] for b in grouped)==finance["net"],
          "Sum of business-specific net equals all sales")
    audit(int(overall["mehr_net_payable"])==max(0,-int(ledger["net"])),
          "Main financial payable to Mehr matches Mehr ledger NET once")
    audit(int(overall["mehr_net_receivable"])==max(0,int(ledger["net"])),
          "Main financial claim from Mehr matches Mehr ledger NET once")
    sums={}
    for r in actual:
        key=r["source"]
        sums[key]=sums.get(key,0)+int(r["gross"])
    print("All sales gross:",n(finance["gross"]))
    print("All sales recognized net:",n(finance["net"]))
    print("All sales COGS (known):",n(finance["cogs_known"]))
    print("All sales profit:",n(finance["profit"]) if finance["profit"] is not None else "UNKNOWN (missing costs)")
    print("Gross sales by channel:",", ".join(k+"="+n(v) for k,v in sorted(sums.items())))
    for b in grouped:
        print("BUSINESS",b["business"],"gross",n(b["gross"]),"cogs_known",
              n(b["cogs_known"]),"profit",n(b["profit"]) if b["profit"] is not None else "UNKNOWN")
    print("MOLD INVOICES count",len(invoice_sale_rows),
          "gross",n(sum(x["gross"] for x in invoice_sale_rows)),
          "procurement_cost",n(sum(x["cogs"] for x in invoice_sale_rows)))
    print("All customer outstanding (finance card):",n(overall["invoice_receivable"]))
    print("Bankless platform receipts are kept separate from customer invoice receipts.")
    print("Legacy Django/old PostgreSQL financial reports are NOT combined in this authoritative new finance ledger.")
    heading("D. SUMMARY")
    if problems:
        for idx,p in enumerate(problems,1):print(f"REVIEW #{idx}: {p}")
        print("AUDIT_HAS_DISCREPANCIES / NO CHANGES MADE")
    else:
        print("ALL_VERIFIED_INTERNAL_RECONCILIATIONS_PASS / NO CHANGES MADE")
    print("Note: This verifies CURRENT SQLite ledger, not external bank statements, historic opening balances or physical warehouse counts.")
finally:
    try:db.execute("ROLLBACK")
    except sqlite3.Error:pass
    db.close()
